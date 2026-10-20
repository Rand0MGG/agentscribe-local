"""Short owned checks in isolated Python processes; Qt callbacks stay on its thread."""
import json

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal

from . import diagnostic_log as diag
from .runtime_paths import installation_command, python_environment, resource_root


class BackgroundCheck(QProcess):
    result = Signal(object)
    completed = Signal()

    def __init__(self, module, arguments=(), parent=None):
        super().__init__(parent)
        self.delivered = False
        self.failure_reason = ""
        self.check_module = module
        self.check_failure = None
        environment = QProcessEnvironment()
        for key, value in python_environment().items():
            environment.insert(key, value)
        self.setProcessEnvironment(environment)
        self.setWorkingDirectory(str(resource_root()))
        command = installation_command(module, *arguments)
        self.setProgram(str(command[0]))
        self.setArguments([str(part) for part in command[1:]])
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.timed_out)
        self.finished.connect(self.finish)
        self.errorOccurred.connect(self.failed)

    def begin(self):
        diag.event('background_check_started', check=self.check_module)
        self.timeout.start(30000)
        self.start()

    def timed_out(self):
        self.check_failure = 'timeout'
        self.failure_reason = "检查超时，请稍后重试。"
        self.kill()

    def failed(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.check_failure = 'failed_to_start'
            self.failure_reason = "检查进程无法启动，请检查应用安装与运行环境。"
            self.deliver(None)

    def finish(self, code, status):
        value = None
        if code == 0 and status == QProcess.ExitStatus.NormalExit:
            try:
                value = json.loads(bytes(self.readAllStandardOutput()).decode('utf-8'))
            except (ValueError, UnicodeError):
                self.check_failure = 'invalid_output'
                self.failure_reason = "检查返回内容无法解析，请重试；若持续出现，请检查应用与运行环境。"
        elif not self.failure_reason:
            self.check_failure = 'abnormal_exit'
            self.failure_reason = f"检查进程异常结束（退出码 {code}），请重试或检查运行环境。"
        self.deliver(value)

    def deliver(self, value):
        if self.delivered:
            return
        self.delivered = True
        diag.event('background_check_finished', check=self.check_module,
                   failure=self.check_failure, success=value is not None)
        self.timeout.stop()
        self.result.emit(value)
        self.completed.emit()
