"""Shared activity gates and ordered, nonblocking application shutdown."""
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, QTimer, Signal


@dataclass(frozen=True)
class Activity:
    recording: bool = False
    saving: bool = False
    unsaved: bool = False
    reader: bool = False
    migration: bool = False
    preparation: bool = False
    checks: bool = False
    fenced: bool = False
    update_release: bool = False
    update_pending: bool = False
    knowledge: bool = False
    edits: bool = False

    def switch_reason(self):
        if self.recording:
            return '请先结束聆听并保存，再切换界面。'
        if self.saving or self.unsaved:
            return '请先完成保存或文字恢复，再切换界面。'
        if self.reader or self.migration or self.preparation or self.checks or self.fenced or self.update_release or self.update_pending:
            return '请先完成或取消当前后台任务，再切换界面。'
        if self.knowledge:
            return '课程仍有进行中后台任务，请完成或取消后再切换。'
        if self.edits:
            return '请先保存或取消名称、术语及笔记编辑，再切换界面。'
        return ''


class RuntimeRelease(QThread):
    def __init__(self, runtime, parent):
        super().__init__(parent)
        self.runtime, self.error = runtime, ''

    def run(self):
        try:
            self.runtime.close()
        except Exception as exc:
            self.error = str(exc)


class ShutdownWorkflow(QObject):
    closing = property(lambda self: self.recording.data.closing,
                       lambda self, value: setattr(self.recording.data, 'closing', value))
    retry = Signal()
    failed = Signal(str)

    def __init__(self, *, recording, activity, cancel, save, resources, runtime, released, confirm=lambda: True, parent=None):
        super().__init__(parent)
        self.recording = recording
        self.activity, self.cancel, self.save = activity, cancel, save
        self.resources, self.runtime, self.released, self.confirm = resources, runtime, released, confirm
        self.closing = False
        self.release_job = None
        self.advancing = False
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.retry)

    def abort(self, error=''):
        self.closing = False
        self.timer.stop()
        if error:
            self.failed.emit(error)

    def advance(self):
        if self.advancing:
            return False
        self.closing = True
        self.timer.start()
        self.advancing = True
        try:
            # Re-read after each action: cancellation can dispatch nested events.
            pending = False
            for name in ('checks', 'reader', 'migration', 'preparation', 'recording', 'update_release'):
                if getattr(self.activity(), name):
                    self.cancel[name]()
                    pending = True
            if pending:
                return False
            if self.activity().saving or self.release_job is not None:
                return False
            if not self.save():
                if not self.activity().saving:
                    self.abort('保存未完成，不能退出。请重试保存或备份全部文字。')
                return False
            if self.activity().unsaved:
                self.abort('字幕尚未保存，不能退出。请重试保存或备份全部文字。')
                return False
            if not self.confirm():
                self.abort()
                return False
            if not self.resources():
                return False
            current = self.activity()
            if any((current.recording, current.saving, current.unsaved, current.reader,
                    current.migration, current.preparation, current.checks, current.update_release)):
                return False
            runtime = self.runtime()
            if runtime is not None:
                job = self.release_job = RuntimeRelease(runtime, self)
                job.finished.connect(lambda: QTimer.singleShot(0, lambda: self._released(job)))
                job.start()
                return False
            self.timer.stop()
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            self.abort(str(exc))
            return False
        finally:
            self.advancing = False

    def _released(self, job):
        if job.isRunning():
            QTimer.singleShot(20, lambda: self._released(job))
            return
        self.release_job = None
        job.deleteLater()
        if job.error:
            self.abort('推理环境未能退出，请重试关闭：' + job.error)
        else:
            self.released(job.runtime)
            self.retry.emit()
