"""Owned preparation task: subprocess supervision, progress and cancellation."""
import json
import subprocess
from collections import deque
from threading import Event, Thread

from PySide6.QtCore import QThread, Signal

from .download_progress import PREFIX
from .process_platform import spawn_options, stop_tree
from .runtime_paths import installation_command, python_environment, resource_root


class Preparation(QThread):
    result = Signal(str)
    progress = Signal(str)
    download = Signal(dict)

    def __init__(self, action, parent, *, affects_runtime=True, beta_only=False):
        super().__init__(parent)
        self.action = action
        self.affects_runtime = affects_runtime
        self.beta_only = beta_only
        self.process = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            result = self.action()
            self.result.emit('准备已取消；已完成文件保留。' if self.cancelled else result)
        except Exception as exc:
            self.result.emit(f"未完成：{exc}")

    def run_command(self, command, *, show_progress=True):
        if self.cancelled:
            raise RuntimeError('准备已取消。')
        tail = deque(maxlen=20)
        if show_progress:
            self.download.emit(dict(label='准备组件', unit='stage'))
        # The supervisor owns descendants even when the desktop exits unexpectedly.
        command = installation_command('linguaflow.managed_process', *command)
        with subprocess.Popen(command, cwd=resource_root(), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              env=python_environment(),
                              **spawn_options()) as process:
            self.process = process
            finished = Event()
            def watch():
                while not finished.wait(.05):
                    if self.cancelled:
                        process.stdin.close()  # EOF lets the supervisor reap its tree.
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            stop_tree(process, force=True)
                        return
            watcher = Thread(target=watch, daemon=True)
            watcher.start()
            try:
                for line in process.stdout:
                    if line.strip():
                        if line.startswith(PREFIX):
                            try:
                                event = json.loads(line[len(PREFIX):])
                                if isinstance(event, dict):
                                    self.download.emit(event)
                                    continue
                            except ValueError:
                                pass
                        tail.append(line.strip())
                        if show_progress:
                            self.progress.emit(line.strip()[-350:])
                code = process.wait(timeout=10)
                if self.cancelled:
                    raise RuntimeError('准备已取消；已有文件保留，可稍后继续。')
                if code:
                    raise RuntimeError("\n".join(tail)[-1500:])
            finally:
                finished.set()
                watcher.join(timeout=10)
                self.process = None
        return tail[-1] if tail else "准备完成"
