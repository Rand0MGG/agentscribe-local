"""Backend-owned playback state and bounded media delivery to the desktop adapter."""
import math
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from threading import Thread

from .events import Owner, Signal
from .playback import PlaybackIndex
from .playback_stream import PlaybackStream


class _LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # Playback uses a numeric loopback URL. HTTPServer's reverse DNS lookup
        # is unnecessary and can block the backend owner thread on macOS.
        TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]


class PlaybackController(Owner):
    available_changed = Signal(bool)
    duration_changed = Signal(int)
    position_changed = Signal(int)
    state_changed = Signal(str)
    seeked = Signal(int)
    failed = Signal(str)
    notice = Signal(str)
    command = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stream = None
        self.server = self.server_thread = None
        self.index = PlaybackIndex()
        self.duration_ms = 0
        self.position = 0
        self.epoch = ''
        self.playing = False

    def release(self):
        self.command.emit({'operation': 'release', 'epoch': self.epoch})
        self.epoch = ''
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server_thread.join(timeout=3)
            self.server = self.server_thread = None
        if self.stream:
            self.stream.close()
            self.stream = None
        self.duration_ms = self.position = 0
        self.playing = False
        self.available_changed.emit(False)
        self.duration_changed.emit(0)
        self.position_changed.emit(0)
        self.state_changed.emit('StoppedState')

    def load(self, path, captions, *, recover_recording=False):
        self.release()
        self.index = PlaybackIndex(captions)
        if not path or not path.is_file() or path.stat().st_size <= 44:
            return
        try:
            stream = self.stream = PlaybackStream(path, recover_recording=recover_recording)
            self.duration_ms = stream.duration_ms
            self.epoch = token = secrets.token_urlsafe(32)
            controller = self

            class Handler(BaseHTTPRequestHandler):
                def setup(self):
                    self.request.settimeout(2)
                    super().setup()

                def log_message(self, *_):
                    pass

                def do_GET(self):
                    if self.path != '/' + token or controller.epoch != token:
                        self.send_error(404)
                        return
                    size = stream.size()
                    start, end, status = 0, size - 1, 200
                    requested = self.headers.get('Range')
                    if requested:
                        import re
                        match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                        if not match:
                            self.send_error(416)
                            return
                        start = int(match[1])
                        end = min(size - 1, int(match[2])) if match[2] else size - 1
                        if not 0 <= start <= end < size:
                            self.send_error(416)
                            return
                        status = 206
                    self.send_response(status)
                    self.send_header('Content-Type', 'audio/wav')
                    self.send_header('Content-Length', str(end - start + 1))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    if status == 206:
                        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    try:
                        position = start
                        while position <= end and controller.epoch == token:
                            with stream._lock:
                                if not stream.seek(position):
                                    return
                                data = stream.readData(min(256*1024, end-position+1))
                            if not data:
                                return
                            self.wfile.write(data)
                            position += len(data)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return

            self.server = _LoopbackHTTPServer(('127.0.0.1', 0), Handler)
            self.server.daemon_threads = True
            self.server_thread = Thread(target=lambda: self.server.serve_forever(poll_interval=.02),
                                        name='recording-playback', daemon=True)
            self.server_thread.start()
            self.command.emit({'operation': 'load', 'epoch': token,
                               'url': f'http://127.0.0.1:{self.server.server_port}/{token}'})
            self.available_changed.emit(True)
            self.duration_changed.emit(self.duration_ms)
            if stream.recovered:
                self.notice.emit('已恢复可读取的完整音频采样；原文件未修改，未落盘的尾部无法恢复。')
        except (OSError, ValueError) as exc:
            self.release()
            self.failed.emit(f'无法加载录音，请重新打开后重试：{exc}')

    def seek(self, milliseconds, *, play=False):
        if self.stream is None:
            return
        self.position = max(0, min(round(milliseconds), self.duration_ms))
        self.playing = self.playing or bool(play)
        self.command.emit({'operation': 'seek', 'epoch': self.epoch, 'position': self.position, 'play': self.playing})
        self.seeked.emit(self.position)

    def set_volume(self, value):
        if self.stream is None:
            return
        if value > 100 and not self.stream.supports_gain:
            raise ValueError('该录音格式不支持增益放大。')
        self.command.emit({'operation': 'volume', 'epoch': self.epoch, 'value': value})

    def toggle(self):
        if self.stream is not None:
            self.playing = not self.playing
            self.command.emit({'operation': 'play' if self.playing else 'pause', 'epoch': self.epoch})

    def receive(self, epoch, state, position=0, error=''):
        if epoch != self.epoch or not self.stream:
            return
        if state not in ('PlayingState', 'PausedState', 'StoppedState', 'Error'):
            raise ValueError('无效的播放器状态。')
        if type(position) not in (int, float) or not math.isfinite(position) or position < 0:
            raise ValueError('无效的播放位置。')
        self.position = min(round(position), self.duration_ms)
        self.playing = state == 'PlayingState'
        self.position_changed.emit(self.position)
        self.state_changed.emit('StoppedState' if state == 'Error' else state)
        if state == 'Error':
            self.failed.emit(str(error)[:500] or '录音播放失败，请重新打开录音。')
