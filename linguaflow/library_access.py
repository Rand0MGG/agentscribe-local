"""File ownership adapter. Library owns paths; this module owns lock lifetimes."""
from .file_lock import FileLock


def acquire_library_migration_lock(root):
    lock = FileLock(str(root / '.library-migration.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise ValueError('这个保存目录正在其他窗口迁移，请等待迁移完成。')
    return lock


def check_library_migration(root):
    lock = acquire_library_migration_lock(root)
    lock.unlock()


def acquire_recording_lock(directory):
    lock = FileLock(str(directory / '.recording.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise ValueError('这段录音正在另一个窗口中使用。')
    return lock


def check_library_access(library, item):
    for path in library.recording_locks(item):
        lock = acquire_recording_lock(path.parent)
        lock.unlock()
