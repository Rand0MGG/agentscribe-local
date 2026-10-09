"""Qt transport for one owned knowledge process; no API/SQLite work on the UI thread."""
import json
import subprocess
from collections import deque
from dataclasses import asdict
from threading import Condition, Thread
from uuid import uuid4

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal, Slot

from ..process_platform import close_process_pipes, spawn_options, stop_tree
from ..runtime_paths import knowledge_python, python_environment, resource_root


class KnowledgeClient(QObject):
    changed = Signal(dict)
    _received = Signal(str, dict)
    _closed = Signal(str)
    closed = Signal()
    closing_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.epoch = ''
        self.identifier = ''
        self.pending = deque()
        self.condition = Condition()
        self.threads = []
        self.closing = False
        self.close_job = None
        self.close_error = ''
        self.retiring_process = None
        self.retiring_threads = []
        self._received.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self._closed.connect(self._finish_close, Qt.ConnectionType.QueuedConnection)

    @Slot(str, dict)
    def _deliver(self, epoch, value):
        if epoch == self.epoch:
            self.changed.emit(value)

    def open(self, library, item, captions=None):
        if self.process is not None and self.identifier == item['id'] and self.process.poll() is None:
            self.send('view')
            return
        if not self.close():
            return
        epoch = self.epoch = uuid4().hex
        self.identifier = item['id']
        self.process = subprocess.Popen([str(knowledge_python()), '-m', 'linguaflow.knowledge.worker'],
            cwd=resource_root(), env=python_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1, **spawn_options())
        process = self.process
        def read():
            try:
                for line in process.stdout:
                    if epoch != self.epoch:
                        break
                    if len(line) > 12 * 1024**2:
                        raise ValueError('课程显示数据过大，请拆分课程。')
                    self._received.emit(epoch, json.loads(line))
            except (OSError, ValueError):
                pass
            finally:
                if epoch == self.epoch:
                    self._received.emit(epoch, {'type': 'error', 'message': '课程后台已停止，请重新打开课程资料。', 'busy': False})
        def write():
            try:
                while True:
                    with self.condition:
                        self.condition.wait_for(lambda: self.pending or epoch != self.epoch)
                        if epoch != self.epoch:
                            return
                        value = self.pending.popleft()
                    process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
                    process.stdin.flush()
            except (OSError, ValueError):
                pass
        self.threads = [Thread(target=read, daemon=True), Thread(target=write, daemon=True)]
        for thread in self.threads:
            thread.start()
        self.send('open', root=str(library.root), identifier=item['id'], folder_id=item['folder'], epoch=epoch,
                  live=None if captions is None else [asdict(caption) for caption in captions])

    def send(self, operation, **value):
        if self.process is None or self.process.poll() is not None:
            return False
        command = {'operation': operation, **value}
        with self.condition:
            if operation in ('caption', 'saved', 'view'):
                self.pending = deque(row for row in self.pending if not (
                    row['operation'] == operation and (operation != 'caption' or row['caption']['id'] == value['caption']['id'])))
            self.pending.append(command)
            self.condition.notify()
        return True

    def observe(self, caption):
        self.send('caption', caption=asdict(caption))

    def saved(self, captions, final=False):
        self.send('saved', captions=[asdict(caption) for caption in captions], final=final)

    def close(self):
        """Reap resources off the UI thread; dispatch Qt events until safe to proceed.

        Return False on reentry/timeout/error so callers cannot mutate files
        while the old worker may still use them. Closing invalidates replies first.
        """
        if self.closing:
            return False
        process = self.process
        threads = self.threads
        with self.condition:
            self.epoch = self.identifier = ''
            self.pending.clear()
            self.condition.notify_all()
        if process is None and not threads:
            return True
        self.process, self.threads = None, []
        self.retiring_process, self.retiring_threads = process, threads
        self.closing, self.close_error = True, ''
        self.closing_changed.emit(True)
        def reap():
            error = ''
            try:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        stop_tree(process, force=True)
                        process.wait(timeout=5)
                for thread in threads:
                    thread.join(timeout=1)
            except Exception as exc:
                error = f'课程后台清理失败：{exc}'
            finally:
                try:
                    if process is not None:
                        close_process_pipes(process)
                except Exception as exc:
                    error = error or f'课程后台管道清理失败：{exc}'
                self._closed.emit(error)
        self.close_job = Thread(target=reap, daemon=True)
        loop, timer = QEventLoop(), QTimer()
        timer.setSingleShot(True)
        self.closed.connect(loop.quit)
        timer.timeout.connect(loop.quit)
        timer.start(10000)
        try:
            try:
                self.close_job.start()
            except RuntimeError as exc:
                self.process, self.threads = process, threads
                self.retiring_process, self.retiring_threads = None, []
                self.close_job, self.closing = None, False
                self.close_error = f'无法启动课程清理任务：{exc}'
                self.closing_changed.emit(False)
                return False
            loop.exec()
            return not self.closing and not self.close_error
        finally:
            timer.stop()
            self.closed.disconnect(loop.quit)

    @Slot(str)
    def _finish_close(self, error):
        self.close_job.join()
        self.close_job = None
        self.closing, self.close_error = False, error
        if error and self.retiring_process is not None and self.retiring_process.poll() is None:
            self.process, self.threads = self.retiring_process, self.retiring_threads
        self.retiring_process, self.retiring_threads = None, []
        self.closing_changed.emit(False)
        if error:
            self.changed.emit({'type': 'error', 'message': error, 'busy': False})
        self.closed.emit()
