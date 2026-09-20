"""Qt file-lock adapter. Library owns paths; this module owns lock lifetimes."""
from PySide6.QtCore import QLockFile


def acquire_recording_lock(directory):
    lock = QLockFile(str(directory / '.recording.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise ValueError('这段录音正在另一个窗口中使用。')
    return lock


def check_library_access(library, item):
    for path in library.recording_locks(item):
        lock = acquire_recording_lock(path.parent)
        lock.unlock()
