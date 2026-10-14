"""Native update adapters. Download/install/verification belong to Sparkle.

    Only immutable messages cross a native callback thread. The shared gate is
    a threading.Event; no WinSparkle callback reads Qt or recording objects.
"""
import ctypes
import json
import sys
import time
from pathlib import Path
from threading import Event, Lock, Thread

from PySide6.QtCore import QObject, Qt, Signal

from . import __version__
from .runtime_paths import packaged, resource_root
from .update_config import bundle_version, update_identity


class UpdateEventRelay:
    """Bound native progress traffic before it reaches Qt's event queue."""
    def __init__(self, notify, clock=time.monotonic):
        self.notify, self.clock = notify, clock
        self.stage = None
        self.last = 0
        self.lock = Lock()

    def __call__(self, event):
        with self.lock:
            now, stage = self.clock(), event.get('stage')
            if (stage in ('downloading', 'verifying') and stage == self.stage
                    and event.get('progress') != 100 and now - self.last < .1):
                return
            self.last, self.stage = now, stage
        self.notify(event)


class NativeUpdater(QObject):
    event = Signal(dict)
    request_install = Signal()
    shutdown_complete = Signal(str)
    _shutdown_finished = Signal(str)

    def __init__(self, parent=None, *, installed=None):
        super().__init__(parent)
        self.installed = packaged() if installed is None else installed
        self.adapter = None
        self.ready = Event()
        self.pending = False
        self.installing = False
        self.error = ''
        self.shutdown_job = None
        self.active = False
        self.recovery = None
        self.cancelled = Event()
        self.relay = UpdateEventRelay(self.event.emit)
        self.event.connect(self._observe)
        self.request_install.connect(self._requested, Qt.ConnectionType.QueuedConnection)
        self._shutdown_finished.connect(self._shutdown_done, Qt.ConnectionType.QueuedConnection)

    def initialize(self):
        if not self.installed or self.adapter:
            return self.adapter is not None
        try:
            root = resource_root()
            config = json.loads((root / 'update-config.json').read_text())
            # Validate the bundled immutable identity, never a remote override.
            identity = update_identity({'feed_base': config['feed_url'].rsplit('/', 2)[0],
                        'targets': {config['target']: {'public_key': config['public_key']}}},
                        config['target'], __version__)
            if identity != config:
                raise ValueError('更新身份与安装包版本不一致。')
            if sys.platform == 'darwin' and config['target'] == 'macos-arm64':
                self.adapter = SparkleAdapter(root, self.relay)
            elif sys.platform == 'win32' and config['target'] == 'windows-x64':
                self.adapter = WinSparkleAdapter(root, config, self.relay, self.ready, self.request_install.emit)
            else:
                raise ValueError('安装包更新组件与平台不一致。')
            return True
        except (OSError, ValueError, KeyError, AttributeError) as exc:
            self.error = str(exc)
            return False

    def check(self, *, manual=True):
        if self.active or self.pending or self.installing or self.shutdown_job is not None:
            return False
        if not self.initialize():
            self.event.emit({'stage': 'error', 'text': '此安装包尚未配置应用内更新，请安装含更新器的过渡版本。',
                             'details': self.error})
            return False
        self.active = True
        self.cancelled.clear()
        self.ready.clear()
        self.event.emit({'stage': 'checking', 'text': '正在检查更新'})
        self.adapter.check(manual)
        return True

    def _observe(self, event):
        if event.get('stage') in ('latest', 'error', 'cancelled', 'installed'):
            self.active = False
        if event.get('stage') in ('error', 'cancelled'):
            self.cancelled.set()
            if self.recovery:
                self.recovery.cancel()

    def _requested(self):
        if self.shutdown_job is not None or self.cancelled.is_set():
            return
        self.pending = True
        self.event.emit({'stage': 'waiting', 'text': '录音与文件保存完成后可重启更新。'})

    def confirm_install(self):
        if self.shutdown_job is not None:
            return
        self.cancelled.clear()
        self.pending = True
        self.request_install.emit()

    def install(self):
        """Called only after shared shutdown preparation has completed."""
        if self.adapter and self.pending:
            self.ready.set()
            self.installing = True
            self.adapter.install()

    def release_runtime(self, runtime):
        if self.shutdown_job is not None:
            return
        def run():
            error = ''
            try:
                if runtime is not None:
                    runtime.close(wait=True)
                if self.installed and not self.cancelled.is_set():
                    from .update_recovery import UpdateRecovery
                    root = resource_root()
                    config = json.loads((root / 'update-config.json').read_text())
                    self.recovery = UpdateRecovery(root, config['target'], __version__)
                    self.recovery.prepare()
                    if self.cancelled.is_set():
                        self.recovery.cancel()
            except Exception as exc:
                error = str(exc)
            finally:
                self._shutdown_finished.emit(error)
        self.shutdown_job = Thread(target=run)
        self.shutdown_job.start()

    def _shutdown_done(self, error):
        self.shutdown_job.join()
        self.shutdown_job = None
        self.shutdown_complete.emit(error)

    def cancel(self):
        self.cancelled.set()
        if self.recovery:
            self.recovery.cancel()
        self.pending = False
        self.active = False
        self.ready.clear()
        if self.adapter:
            self.adapter.cancel()
        self.event.emit({'stage': 'cancelled', 'text': '更新已取消，当前版本保留。'})

    def close(self):
        if self.adapter and not self.installing:
            if self.recovery:
                self.recovery.cancel()
            self.adapter.close()


class SparkleAdapter:
    def __init__(self, root, notify):
        bridge = root.parent / 'Frameworks/AgentScribeUpdater.dylib'
        self.library = ctypes.CDLL(str(bridge))
        callback_type = ctypes.CFUNCTYPE(None, ctypes.c_char_p)
        self.callback = callback_type(lambda data: notify(json.loads(data.decode('utf-8'))))
        self.library.ASUpdaterStart.argtypes = [callback_type]
        self.library.ASUpdaterStart.restype = ctypes.c_int
        self.library.ASUpdaterCheck.argtypes = [ctypes.c_int]
        self.library.ASUpdaterChoose.argtypes = [ctypes.c_int]
        if not self.library.ASUpdaterStart(self.callback):
            raise ValueError('原生 Mac 更新器启动失败。')

    def check(self, manual):
        self.library.ASUpdaterCheck(int(manual))

    def download(self):
        self.library.ASUpdaterChoose(1)

    def install(self):
        self.library.ASUpdaterChoose(2)

    def cancel(self):
        self.library.ASUpdaterChoose(0)

    def close(self):
        self.library.ASUpdaterStop()


class WinSparkleAdapter:
    def __init__(self, root, config, notify, ready, request_install):
        dll = Path(root) / 'WinSparkle.dll'
        # WinSparkle exports cdecl, even on 32-bit; CDLL is intentional.
        self.library = ctypes.CDLL(str(dll))
        self.callbacks = []
        self.library.win_sparkle_set_appcast_url.argtypes = [ctypes.c_char_p]
        self.library.win_sparkle_set_eddsa_public_key.argtypes = [ctypes.c_char_p]
        self.library.win_sparkle_set_eddsa_public_key.restype = ctypes.c_int
        self.library.win_sparkle_set_app_details.argtypes = [ctypes.c_wchar_p]*3
        self.library.win_sparkle_set_app_build_version.argtypes = [ctypes.c_wchar_p]
        self.library.win_sparkle_set_automatic_check_for_updates.argtypes = [ctypes.c_int]
        for name in ('set_app_details', 'set_app_build_version', 'set_appcast_url',
                     'set_automatic_check_for_updates', 'init', 'cleanup',
                     'check_update_without_ui', 'check_update_with_ui', 'check_update_with_ui_and_install'):
            getattr(self.library, 'win_sparkle_' + name).restype = None
        self.library.win_sparkle_set_app_details('Rand0MGG', 'AgentScribe', __version__)
        self.library.win_sparkle_set_app_build_version(bundle_version(__version__))
        self.library.win_sparkle_set_appcast_url(config['feed_url'].encode('utf-8'))
        if not self.library.win_sparkle_set_eddsa_public_key(config['public_key'].encode('ascii')):
            raise ValueError('WinSparkle 拒绝更新公钥。')
        self.library.win_sparkle_set_automatic_check_for_updates(0)
        for name, stage, text in (
                ('error', 'error', '更新失败，当前版本与用户数据保留。'),
                ('did_not_find_update', 'latest', f'当前已是最新版本（{__version__}）。'),
                ('did_find_update', 'native', '发现新版本，可在更新窗口中下载。'),
                ('update_cancelled', 'cancelled', '更新已取消，当前版本保留。')):
            self._callback(name, ctypes.CFUNCTYPE(None), lambda stage=stage, text=text: notify({'stage': stage, 'text': text}))
        def can_shutdown():
            if ready.is_set():
                return 1
            request_install()
            return 0
        self._callback('can_shutdown', ctypes.CFUNCTYPE(ctypes.c_int), can_shutdown)
        self._callback('shutdown_request', ctypes.CFUNCTYPE(None), lambda: notify({'stage': 'quit'}))
        self.library.win_sparkle_init()

    def _callback(self, name, prototype, callback):
        value = prototype(callback)
        setter = getattr(self.library, 'win_sparkle_set_' + name + '_callback')
        setter.argtypes = [prototype]
        setter.restype = None
        setter(value)
        self.callbacks.append(value)

    def check(self, manual):
        # Checking feedback stays in Qt; WinSparkle only opens its window when
        # an update is found. Native download/installation UI is not duplicated.
        self.library.win_sparkle_check_update_without_ui()

    def download(self):
        self.library.win_sparkle_check_update_with_ui()

    def install(self):
        self.library.win_sparkle_check_update_with_ui_and_install()

    def cancel(self):
        self.library.win_sparkle_cleanup()
        self.library.win_sparkle_init()

    def close(self):
        self.library.win_sparkle_cleanup()
