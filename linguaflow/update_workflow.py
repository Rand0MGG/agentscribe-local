"""Native update lifecycle, independent of desktop widgets and IPC."""
from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateActivity:
    unsaved_edits: bool = False
    recording: bool = False
    unsaved_recording: bool = False
    files: bool = False
    preparation: bool = False
    knowledge_closing: bool = False
    checks: bool = False

    def wait_reason(self):
        if self.unsaved_edits:
            return '更新等待名称、课程术语或笔记编辑保存，请保存或取消修改。'
        if any((self.recording, self.unsaved_recording, self.files, self.preparation, self.knowledge_closing)):
            return '更新等待录音结束与文件保存，应用仍可使用。'
        if self.checks:
            return '更新等待后台检查结束。'
        return ''


class UpdateWorkflow:
    """One gate/release/cancel owner; desktops supply state and presentation callbacks."""
    def __init__(self, updater, *, activity, close_knowledge, runtime, fence, restore, notify):
        self.updater = updater
        self.activity, self.close_knowledge, self.runtime = activity, close_knowledge, runtime
        self.fence, self.restore, self.notify = fence, restore, notify
        self.fenced = False
        updater.event.connect(self.observe)
        updater.shutdown_complete.connect(self.released)

    def observe(self, event):
        if event.get('stage') == 'waiting':
            self.try_install()
        elif event.get('stage') in ('error', 'cancelled'):
            self.updater.pending = self.updater.installing = False
            self.updater.ready.clear()
            if self.updater.shutdown_job is None:
                self.resume()

    def try_install(self):
        self.updater.pending = True
        if self.fenced:
            if (self.updater.shutdown_job is None and not self.updater.installing
                    and not self.activity().wait_reason()):
                self.updater.install()
            return
        reason = self.activity().wait_reason()
        if not reason and not self.close_knowledge():
            reason = '更新等待资料保存与后台释放。'
        if reason:
            self.notify(reason, False)
            return
        # close_knowledge can dispatch nested events: recheck all ownership gates.
        if not self.updater.pending:
            return
        reason = self.activity().wait_reason()
        if reason:
            self.notify(reason, False)
            return
        self.fenced = True
        self.fence()
        self.notify('正在保留旧版并准备重启更新', True)
        self.updater.release_runtime(self.runtime())

    def cancel_wait(self):
        if not self.updater.pending:
            return
        if self.fenced:
            self.updater.cancel()
        else:
            self.updater.pending = False
            self.updater.last_event = {'stage': 'ready', 'text': '已取消等待，下载的更新可稍后安装。'}
            self.updater.event.emit(self.updater.last_event)

    def released(self, error):
        if not self.updater.pending:
            self.resume()
        elif error:
            self.updater.event.emit({'stage': 'error', 'text': '更新准备失败，当前版本保留。', 'details': error})
        else:
            reason = self.activity().wait_reason()
            if reason:
                self.notify(reason, False)
            else:
                self.updater.install()

    def resume(self):
        self.fenced = False
        self.restore()
