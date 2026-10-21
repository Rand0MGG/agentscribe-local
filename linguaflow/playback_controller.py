"""Own playback resources without depending on the main window or audio discovery."""
from PySide6.QtCore import QObject, QUrl, Signal

from .playback import PlaybackIndex


class PlaybackController(QObject):
    available_changed = Signal(bool)
    duration_changed = Signal('qlonglong')
    position_changed = Signal('qlonglong')
    state_changed = Signal(str)
    failed = Signal(str)
    notice = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = self.stream = self.audio_output = None
        self.index = PlaybackIndex()
        self.duration_ms = 0

    def close_stream(self):
        if self.stream is not None:
            self.stream.close()
            self.stream.deleteLater()
            self.stream = None

    def release(self):
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.close_stream()
        self.duration_ms = 0
        self.available_changed.emit(False)
        self.duration_changed.emit(0)
        self.position_changed.emit(0)

    def load(self, path, captions, *, recover_recording=False):
        self.release()
        self.index = PlaybackIndex(captions)
        available = bool(path and path.exists() and path.stat().st_size > 44)
        self.available_changed.emit(available)
        if not available:
            return
        # Import only on an explicit attempt to play an existing recording.
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        from .playback_stream import PlaybackStream
        try:
            if self.player is None:
                self._create_player(QMediaPlayer, QAudioOutput)
            self.stream = PlaybackStream(path, self.player, recover_recording=recover_recording)
            self.player.setSourceDevice(self.stream, QUrl.fromLocalFile(str(path)))
        except (OSError, ValueError, RuntimeError) as exc:
            self.release()
            self.failed.emit(f'无法加载录音，请重新打开后重试：{exc}')
            return
        if self.stream.recovered:
            self.notice.emit('已恢复可读取的完整音频采样；原文件未修改，未落盘的尾部无法恢复。')
        if not self.stream.supports_gain:
            self.notice.emit('该录音格式可正常回放，但暂不支持超过 100% 的放大。')

    def _create_player(self, player_type, output_type):
        player = output = None
        try:
            player = player_type(self)
            output = output_type(self)
            player.setAudioOutput(output)
            player.durationChanged.connect(self.duration_changed)
            player.positionChanged.connect(self.position_changed)
            player.playbackStateChanged.connect(lambda state: self.state_changed.emit(state.name))
            player.errorOccurred.connect(lambda *_: self.failed.emit(player.errorString()))
        except Exception:
            if player is not None:
                player.deleteLater()
            if output is not None:
                output.deleteLater()
            raise
        self.player, self.audio_output = player, output

    def set_volume(self, value):
        if self.audio_output is not None:
            self.audio_output.setVolume(min(1., value / 100))
        if self.stream is not None:
            gain = max(1., value / 100)
            previous = self.stream.gain
            self.stream.set_gain(gain)
            if gain != previous and self.player is not None:
                self.player.setPosition(self.player.position())

    def toggle(self):
        if self.player:
            if self.player.playbackState().name == 'PlayingState':
                self.player.pause()
            else:
                self.player.play()
