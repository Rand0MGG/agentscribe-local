"""Serial background recording saves; Qt signals return results to the UI thread."""
from collections import deque
from dataclasses import dataclass, replace
from threading import Thread

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal, Slot

from .core import Caption


@dataclass(frozen=True)
class SaveSnapshot:
    token: tuple[int, str]
    revision: int
    item: dict
    captions: tuple[Caption, ...]
    state: str | None


class _SaveJob(Thread):
    def __init__(self, write, snapshot, notify):
        super().__init__()
        self.write = write
        self.snapshot = snapshot
        self.notify = notify
        self.saved_state = None
        self.error = ''

    def run(self):
        item = self.snapshot.item.copy()
        try:
            self.write(item, self.snapshot.captions, self.snapshot.state)
            self.saved_state = item['state']
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
        finally:
            self.notify()


class RecordingSaver(QObject):
    completed = Signal(object, str, str)
    idle = Signal()
    _job_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.job = None
        self.pending = deque()
        self.waiting = False
        self._job_finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)

    @property
    def busy(self):
        return self.job is not None or bool(self.pending)

    def submit(self, write, token, revision, item, captions, state=None):
        """Freeze UI data and queue a save; coalesce pending revisions of one recording.

        write(item, captions, state) runs in a worker and must raise on failure.
        A started write completes before another starts; final saves cannot be
        superseded by an automatic save lacking an explicit completion state.
        """
        if self.job is not None and self.job.snapshot.token == token and revision < self.job.snapshot.revision:
            return
        snapshot = SaveSnapshot(token, revision, item.copy(), tuple(replace(c) for c in captions), state)
        for index, (_write, old) in enumerate(self.pending):
            if old.token == token:
                if revision < old.revision:
                    return
                if old.state is not None and state is None:
                    snapshot = replace(snapshot, state=old.state)
                self.pending[index] = (write, snapshot)
                break
        else:
            self.pending.append((write, snapshot))
        self._start()

    def _start(self):
        if self.job is not None or not self.pending:
            return
        write, snapshot = self.pending.popleft()
        # Disk IO needs no Qt thread object. Repeated QThread construction can
        # crash in PySide on Windows; the saver owns and joins this Python job.
        self.job = _SaveJob(write, snapshot, self._job_finished.emit)
        try:
            self.job.start()
        except RuntimeError as exc:
            self.job.error = f'无法启动后台保存线程：{exc}'
            self._job_finished.emit()

    @Slot()
    def _finished(self):
        # A queued signal can arrive before run() returns. Idle/completed must
        # not release ownership until the writer has actually exited.
        if self.job.ident is not None:
            self.job.join()
        job, self.job = self.job, None
        self.completed.emit(job.snapshot, job.saved_state or '', job.error)
        self._start()
        if not self.busy:
            self.idle.emit()

    def flush(self, timeout_ms=30000):
        """Wait for queued disk writes while Qt continues dispatching events.

        Return False on timeout/reentrant waits; a timed-out job stays owned and
        must finish before navigation or application shutdown can proceed.
        """
        if self.waiting:
            return False
        if not self.busy:
            return True
        self.waiting = True
        loop, timer = QEventLoop(), QTimer()
        timer.setSingleShot(True)
        self.idle.connect(loop.quit)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        try:
            loop.exec()
            return not self.busy
        finally:
            timer.stop()
            self.idle.disconnect(loop.quit)
            self.waiting = False
