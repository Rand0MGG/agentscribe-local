"""Short owned checks in isolated Python processes; Qt callbacks stay on its thread."""
import json

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal

from .runtime_paths import installation_command, python_environment, resource_root


class BackgroundCheck(QProcess):
    result = Signal(object)
    completed = Signal()

    def __init__(self, module, arguments=(), parent=None):
        super().__init__(parent)
        self.delivered = False
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
        self.timeout.timeout.connect(self.kill)
        self.finished.connect(self.finish)
        self.errorOccurred.connect(self.failed)

    def begin(self):
        self.timeout.start(30000)
        self.start()

    def failed(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.deliver(None)

    def finish(self, code, status):
        value = None
        if code == 0 and status == QProcess.ExitStatus.NormalExit:
            try:
                value = json.loads(bytes(self.readAllStandardOutput()).decode('utf-8'))
            except (ValueError, UnicodeError):
                pass
        self.deliver(value)

    def deliver(self, value):
        if self.delivered:
            return
        self.delivered = True
        self.timeout.stop()
        self.result.emit(value)
        self.completed.emit()
