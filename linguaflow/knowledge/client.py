"""Qt transport for one owned knowledge process; no API/SQLite work on the UI thread."""
import json
import subprocess
from collections import deque
from dataclasses import asdict
from pathlib import Path
from threading import Condition, Thread
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal, Slot

from ..process_platform import spawn_options, stop_tree
from ..runtime_paths import knowledge_python


class KnowledgeClient(QObject):
    changed = Signal(dict)
    _received = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.epoch = ''
        self.identifier = ''
        self.pending = deque()
        self.condition = Condition()
        self.threads = []
        self._received.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    @Slot(str, dict)
    def _deliver(self, epoch, value):
        if epoch == self.epoch:
            self.changed.emit(value)

    def open(self, library, item, captions=None):
        if self.process is not None and self.identifier == item['id'] and self.process.poll() is None:
            self.send('view')
            return
        self.close()
        epoch = self.epoch = uuid4().hex
        self.identifier = item['id']
        self.process = subprocess.Popen([str(knowledge_python()), '-m', 'linguaflow.knowledge.worker'],
            cwd=Path(__file__).resolve().parents[2], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1, **spawn_options())
        process = self.process
        def read():
            try:
                for line in process.stdout:
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
        process = self.process
        with self.condition:
            self.epoch = self.identifier = ''
            self.pending.clear()
            self.condition.notify_all()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    stop_tree(process, force=True)
                    process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        for thread in self.threads:
            thread.join(timeout=1)
        self.threads = []
        self.process = None
