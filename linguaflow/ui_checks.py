"""Short owned checks in isolated Python processes, dispatched by the backend."""
import json
import subprocess
from threading import Event

from . import diagnostic_log as diag
from .events import Signal, Worker
from .process_platform import close_process_pipes, start_worker, stop_worker
from .runtime_paths import installation_command, python_environment, resource_root


class BackgroundCheck(Worker):
    result = Signal(object)
    completed = Signal()

    def __init__(self, module, arguments=(), parent=None):
        super().__init__(parent)
        self.check_module, self.arguments = module, arguments
        self.failure_reason = ''
        self.check_failure = None
        self.delivered = False
        self.cancelled = Event()
        self.process = self.job = None
        self.value = None
        self.timeout_seconds = 30
        self.finished.connect(self._completed)

    def begin(self):
        diag.event('background_check_started', check=self.check_module)
        self.start()

    def kill(self):
        self.cancelled.set()

    def run(self):
        try:
            if self.cancelled.is_set():
                return
            command = installation_command(self.check_module, *self.arguments)
            target = list(command[1:])
            while target and target[0] in ('-u', '-m'):
                target.pop(0)
            self.process, self.job = start_worker(command[0], target[0] if target else self.check_module, arguments=target[1:],
                cwd=resource_root(), env=python_environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            import time
            deadline = time.monotonic()+self.timeout_seconds
            while True:
                try:
                    output, _ = self.process.communicate(timeout=.05)
                    break
                except subprocess.TimeoutExpired:
                    if self.cancelled.is_set() or time.monotonic() >= deadline:
                        self.check_failure = 'cancelled' if self.cancelled.is_set() else 'timeout'
                        self.failure_reason = '检查已取消。' if self.cancelled.is_set() else '检查超时，请稍后重试。'
                        return
            if self.process.returncode:
                self.check_failure = 'abnormal_exit'
                self.failure_reason = f'检查进程异常结束（退出码 {self.process.returncode}），请重试或检查运行环境。'
            else:
                try:
                    self.value = json.loads(output.decode('utf-8'))
                except (ValueError, UnicodeError):
                    self.check_failure = 'invalid_output'
                    self.failure_reason = '检查返回内容无法解析，请重试。'
        except OSError:
            self.check_failure = 'failed_to_start'
            self.failure_reason = '检查进程无法启动，请检查应用安装与运行环境。'
        finally:
            if self.process is not None:
                stop_worker(self.process, self.job, (), force=True)
                close_process_pipes(self.process)

    def _completed(self):
        if self.isRunning():
            self.dispatcher.call(self._completed, .01)
            return
        if not self.delivered:
            self.delivered = True
            diag.event('background_check_finished', check=self.check_module,
                       failure=self.check_failure, success=self.value is not None)
            self.result.emit(None if self.cancelled.is_set() else self.value)
            self.completed.emit()
