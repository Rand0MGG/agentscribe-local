"""Own migration locks, durable preference switch and old-copy cleanup."""
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal

from .library_access import (
    acquire_library_migration_lock,
    acquire_recording_lock,
    check_library_access,
    check_library_migration,
)
from .library_migration import LibraryMigration


class LibraryWorkflow(QObject):
    adopted = Signal(object)
    finished = Signal(list, str)

    def __init__(self, recording, prefs, parent=None):
        super().__init__(parent)
        self.recording, self.prefs = recording, prefs
        self.locks = []
        self.source = None
        self.worker = LibraryMigration(self)
        self.worker.copied.connect(self.copied)
        self.worker.cleaned.connect(self.completed)

    def contains_current(self, item):
        data = self.recording.data
        if not data.item:
            return False
        path, current = data.library.directory(item['id']), data.library.directory(data.item['id'])
        return path == current or path in current.parents

    def ensure_edit(self, item, *, activity, close_resources, rename_current=False):
        data = self.recording.data
        if data.closing:
            raise ValueError('正在退出，请等待当前任务结束。')
        if activity.reader or activity.migration or activity.fenced or activity.update_release:
            raise ValueError('正在读取、迁移或更新，请完成当前操作后重试。')
        check_library_migration(data.library.root)
        if data.session is not None or data.state.active:
            if item is None:
                raise ValueError('正在聆听，请先停止录音再切换。')
            if self.contains_current(item):
                if not (rename_current and item['id'] == data.item['id'] and data.lock):
                    raise ValueError('请先停止录音再移动或删除当前录音及其文件夹。')
                if not self.recording.flush():
                    raise ValueError('请等待字幕成功保存后再改名。')
                return
        else:
            if not self.recording.flush():
                raise ValueError('字幕尚未保存，请先重试保存或备份全部文字。')
            if close_resources() is False:
                raise ValueError('课程后台正在释放文件，请稍后重试。')
        if item is not None:
            check_library_access(data.library, item)

    def start(self, path):
        data = self.recording.data
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError('请选择有效的保存目录。')
        if Path(path).resolve() == data.library.root:
            return False
        if self.worker.busy or self.locks:
            raise ValueError('录音库正在迁移，请完成或取消后重试。')
        if data.session or data.state.active or self.recording.saver.busy or data.dirty or data.save_error:
            raise ValueError('请先结束录音并完成保存，再迁移录音库。')
        try:
            self.locks.append(acquire_library_migration_lock(data.library.root))
            data.library.refresh()
            for item in data.library.index['sessions']:
                self.locks.append(acquire_recording_lock(data.library.directory(item['id'])))
            self.source = data.library
            self.worker.start(data.library, path)
        except Exception:
            self.release()
            raise
        return True

    def release(self):
        for lock in self.locks:
            lock.unlock()
        self.locks = []
        self.source = None

    def copied(self, library, verified, error):
        if error:
            self.completed([], '迁移未完成，原录音保留：' + error)
            return
        data = self.recording.data
        old_root = data.library.root
        self.prefs.setValue('library_directory', str(library.root))
        self.prefs.sync()
        if self.prefs.status() != QSettings.Status.NoError:
            self.prefs.setValue('library_directory', str(old_root))
            self.completed([], '无法保存新位置，原录音保留；新位置有已校验副本。')
            return
        data.library = library
        if data.item:
            data.item = next((item for item in library.index['sessions'] if item['id'] == data.item['id']), None)
        self.adopted.emit(library)
        self.worker.cleanup(old_root, verified)

    def completed(self, retained, error=''):
        self.release()
        self.finished.emit(retained, error)
