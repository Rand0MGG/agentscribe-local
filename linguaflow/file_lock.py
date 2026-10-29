"""Exclusive file ownership; understand live legacy QLockFile owners on upgrade."""
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path

import psutil


class FileLock:
    def __init__(self, path):
        self.path = Path(path)
        self.identity = None

    def setStaleLockTime(self, _milliseconds):
        # Age alone never revokes an active recording or a slow migration.
        pass

    @contextmanager
    def _guard(self):
        # A persistent OS-locked sidecar serializes reclaim/create/unlink. Never
        # unlink this inode: waiters must continue to share the same lock.
        with self.path.with_name(self.path.name + ".guard").open("a+b") as stream:
            if os.name == "nt":
                import msvcrt
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def _acquire(self):
        try:
            with self.path.open("xb") as stream:
                stream.write(f"{os.getpid()}\n{psutil.Process().name()}\n{socket.gethostname()}\n".encode())
                stream.flush()
                os.fsync(stream.fileno())
                self.identity = os.fstat(stream.fileno()).st_ino
            return True
        except FileExistsError:
            # Unknown, incomplete and foreign-host locks are deliberately retained.
            try:
                stat = self.path.stat()
                rows = self.path.read_text().splitlines()
                if len(rows) >= 3 and rows[2] == socket.gethostname() and int(rows[0]) > 0:
                    if not psutil.pid_exists(int(rows[0])) and self.path.stat().st_ino == stat.st_ino:
                        self.path.unlink()
                        return self._acquire()
            except (OSError, ValueError, UnicodeError):
                pass
            return False

    def tryLock(self, milliseconds=0):
        if self.identity is not None:
            return False
        deadline = time.monotonic() + milliseconds / 1000
        while True:
            try:
                with self._guard():
                    if self._acquire():
                        return True
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(.01)

    @property
    def locked(self):
        return self.identity is not None

    def unlock(self):
        if self.identity is not None:
            try:
                if self.path.stat().st_ino == self.identity:
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self.identity = None

    def __del__(self):
        self.unlock()
