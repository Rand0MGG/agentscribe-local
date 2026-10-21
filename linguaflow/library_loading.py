"""Owned library reads; workers use a detached index and never update widgets."""
from copy import copy
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, Signal


class LibraryReader(QObject):
    completed = Signal(object, str)
    _finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.job = None
        self.cancelled = Event()
        self.result, self.error = None, ''
        self._finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    @property
    def busy(self):
        return self.job is not None

    def start(self, library, *, refresh=False, identifier=None):
        if self.busy:
            return False
        snapshot = copy(library)
        snapshot.index, snapshot.paths = dict(library.index), dict(library.paths)
        self.cancelled.clear()
        self.result, self.error = None, ''

        def read():
            try:
                if refresh:
                    snapshot.refresh()
                    if not snapshot.index['folders'] and snapshot.warnings:
                        raise OSError('录音目录暂不可用，请检查磁盘连接和目录权限；原视图保留。')
                item = next((row for row in snapshot.index['sessions'] if row['id'] == identifier), None)
                if identifier is not None and item is None and not refresh:
                    raise ValueError('录音已移动或删除，请刷新列表；原视图保留。')
                loaded = snapshot.load(item) if item is not None and not self.cancelled.is_set() else None
                self.result = snapshot, item, loaded
            except Exception as exc:
                self.error = str(exc)
            finally:
                self._finished.emit()

        self.job = Thread(target=read)
        try:
            self.job.start()
        except RuntimeError as exc:
            self.error = f'无法启动后台读取线程，请重试：{exc}'
            self._finished.emit()
        return True

    def cancel(self):
        self.cancelled.set()

    def _deliver(self):
        if self.job.ident is not None:
            self.job.join()
        self.job = None
        result = None if self.cancelled.is_set() else self.result
        self.result = None
        self.completed.emit(result, self.error)
