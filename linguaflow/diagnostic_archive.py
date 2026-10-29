"""Lossless support-log archives, shared byte budget, and closed-file recovery."""
import gzip
import hashlib
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

HISTORY_BYTES = 128 * 1024 * 1024
_BASE = r'support-[a-z-]+-\d{8}T\d{6}-(\d+)-[a-f0-9]{8}\.jsonl'
_RAW = re.compile(_BASE + r'(?:\.\d+)?$')
_PENDING = re.compile(_BASE + r'\.\d{20}-[a-f0-9]{8}\.pending$')
_ARCHIVE = re.compile(_BASE + r'(?:\.\d+|\.\d{20}-[a-f0-9]{8})?\.gz$')
_BLOCK = 1024 * 1024


@contextmanager
def _history_lock(root, wait_seconds):
    # The inode persists so all processes lock the same object. No psutil
    # dependency: model workers also enforce the compressed-history budget.
    lock = root / '.support-history.lock'
    if lock.is_symlink():
        raise OSError('history lock is a symbolic link')
    with lock.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
        else:
            import fcntl
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(.01)
        try:
            yield True
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _compress(source):
    """Publish only verified gzip bytes; interrupted attempts retain the source."""
    target = source.with_suffix('.gz') if _PENDING.fullmatch(source.name) else Path(str(source) + '.gz')
    temporary = Path(str(target) + '.tmp')
    if target.is_symlink() or temporary.is_symlink():
        raise OSError('archive path is a symbolic link')
    stat = source.stat()
    digest = hashlib.sha256()
    try:
        with source.open('rb') as original, temporary.open('wb') as output:
            with gzip.GzipFile(filename='', fileobj=output, mode='wb', compresslevel=6, mtime=0) as compressed:
                while block := original.read(_BLOCK):
                    digest.update(block)
                    compressed.write(block)
            output.flush()
            os.fsync(output.fileno())
        verified = hashlib.sha256()
        with gzip.open(temporary, 'rb') as compressed:
            while block := compressed.read(_BLOCK):
                verified.update(block)
        after = source.stat()
        if (verified.digest() != digest.digest()
                or (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
            raise OSError('archive verification failed')
        # Age means the last original write, not the later compression time.
        os.utime(temporary, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        os.replace(temporary, target)
        source.unlink()
    finally:
        # A failed attempt never replaces a valid archive or removes its source.
        # If killed mid-write, the next attempt replaces this temporary file.
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def maintain(root, budget, report_error, *, wait_seconds=0.):
    """Serialize recovery/publication/pruning; never touch live raw logs.

    Pending chunks are sealed/immutable, even if their owner is still alive.
    Legacy or crash-left raw files require a dead-PID check; uncertainty keeps
    them intact. Only committed .gz files count toward the history budget.
    """
    root = Path(root)
    try:
        with _history_lock(root, wait_seconds) as acquired:
            if not acquired:
                return False
            try:
                import psutil
            except ImportError:
                psutil = None
            successful = True
            for path in sorted(root.glob('support-*.jsonl*')):
                if path.is_symlink() or not path.is_file():
                    continue
                pending = _PENDING.fullmatch(path.name)
                raw = _RAW.fullmatch(path.name)
                if not pending and not raw:
                    continue
                if raw and (psutil is None or int(raw[1]) <= 0 or psutil.pid_exists(int(raw[1]))):
                    continue
                try:
                    _compress(path)
                except (OSError, EOFError):
                    successful = False
                    report_error('诊断日志压缩失败，原始记录已保留；请检查磁盘空间和目录权限。')
            archives = []
            for path in root.glob('support-*.jsonl*.gz'):
                if _ARCHIVE.fullmatch(path.name) and not path.is_symlink() and path.is_file():
                    stat = path.stat()
                    archives.append((stat.st_mtime_ns, path.name, stat.st_size, path))
            total = sum(item[2] for item in archives)
            for _modified, _name, size, path in sorted(archives):
                if total <= budget:
                    break
                try:
                    path.unlink()
                    total -= size
                except OSError:
                    successful = False
                    report_error('历史诊断日志清理失败，可能暂时超过容量；请检查目录权限。')
                    break  # Keep newer evidence if the oldest file cannot be removed.
            return successful
    except Exception:
        report_error('诊断日志归档维护失败，原始记录已保留；请检查日志目录权限。')
        return False
