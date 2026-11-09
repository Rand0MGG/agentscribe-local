"""OS locking primitive only; callers own paths, deadlines and recovery policy."""
import os
from contextlib import contextmanager


@contextmanager
def exclusive_lock(stream):
    """Take a nonblocking exclusive lock, released even when the body fails."""
    if os.name == 'nt':
        import msvcrt
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield
    finally:
        if os.name == 'nt':
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream, fcntl.LOCK_UN)
