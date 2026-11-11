"""Owned temporary writes and directory-bound storage operations."""
import ctypes
import hashlib
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def identity(info):
    return [info.st_dev, info.st_ino]


class Directory:
    """Pin an unmapped directory; POSIX operations stay relative to its fd.

    Windows directory handles exclude delete sharing, preventing ancestor moves
    while path-based operations are in progress. Reparse points are rejected.
    """
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.fd = None
        self.handles = []
        try:
            if os.name == 'nt':
                from ctypes import wintypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                create = kernel.CreateFileW
                create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                create.restype = wintypes.HANDLE
                self.create_file = create
                self.set_file_info = kernel.SetFileInformationByHandle
                self.set_file_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
                self.set_file_info.restype = wintypes.BOOL
                self.close_handle = kernel.CloseHandle
                self.close_handle.argtypes = [wintypes.HANDLE]
                for p in reversed([self.path, *self.path.parents]):
                    # Attribute-only handles do not enforce delete sharing.
                    # FILE_LIST_DIRECTORY makes the no-delete share effective.
                    handle = create(str(p), 0x81, 3, None, 3, 0x02200000, None)
                    if handle == ctypes.c_void_p(-1).value:
                        raise ctypes.WinError(ctypes.get_last_error())
                    self.handles.append(handle)
                    info = p.lstat()
                    if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                        raise OSError('保存目录包含快捷映射或已被替换。')
                self.info = self.path.stat()
            else:
                self.fd = os.open(self.path.anchor, os.O_RDONLY | os.O_DIRECTORY)
                for part in self.path.parts[1:]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                    os.close(self.fd)
                    self.fd = child
                self.info = os.fstat(self.fd)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        for handle in reversed(self.handles):
            self.close_handle(handle)
        self.handles = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def name(self, name):
        if Path(name).name != str(name) or name in ('.', '..', ''):
            raise ValueError('无效的存储文件名')
        return self.path / name if self.fd is None else name

    def kwargs(self):
        return {} if self.fd is None else {'dir_fd': self.fd}

    def stat(self, name):
        return os.stat(self.name(name), follow_symlinks=False, **self.kwargs())

    def open(self, name, flags, mode=0o600):
        if self.fd is None:
            try:
                info = self.stat(name)
                if getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise OSError('不通过快捷映射操作文件。')
            except FileNotFoundError:
                pass
        return os.open(self.name(name), flags | getattr(os, 'O_NOFOLLOW', 0), mode, **self.kwargs())

    def unlink(self, name, directory=False):
        (os.rmdir if directory else os.unlink)(self.name(name), **self.kwargs())

    def create_temporary(self, name):
        """Keep the export object owned through publication, not just its name."""
        if self.fd is not None:
            return self.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL)
        import msvcrt
        # READ | WRITE | DELETE, sharing reads only. Other handles cannot modify,
        # rename or delete this object before its owned handle publishes it.
        handle = self.create_file(str(self.name(name)), 0xC0010000, 1, None, 1, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            self.close_handle(handle)
            raise

    def publish(self, source, target, fd, *, exclusive=False):
        if self.fd is not None:
            return self.rename(source, target, exclusive=exclusive)
        import msvcrt
        from ctypes import wintypes
        # FileRenameInfo renames the still-open object, avoiding a second source
        # path lookup. Filename length is UTF-16 bytes (including surrogate pairs).
        encoded = str(self.name(target)).encode('utf-16-le')
        class RenameInfo(ctypes.Structure):
            _fields_ = [('ReplaceIfExists', ctypes.c_ubyte), ('RootDirectory', wintypes.HANDLE),
                        ('FileNameLength', wintypes.DWORD), ('FileName', ctypes.c_byte * (len(encoded) + 2))]
        info = RenameInfo()
        info.ReplaceIfExists = not exclusive
        info.FileNameLength = len(encoded)
        ctypes.memmove(ctypes.addressof(info) + RenameInfo.FileName.offset, encoded, len(encoded))
        if not self.set_file_info(msvcrt.get_osfhandle(fd), 3, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())

    def rename(self, source, target, *, exclusive=False):
        a, b = self.name(source), self.name(target)
        if self.fd is None:
            (os.rename if exclusive else os.replace)(a, b)
        elif not exclusive:
            os.replace(a, b, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        else:
            # Both platforms provide atomic no-replace rename (also on exFAT).
            libc = ctypes.CDLL(None, use_errno=True)
            name, flag = ('renameatx_np', 4) if sys.platform == 'darwin' else ('renameat2', 1)
            fn = getattr(libc, name, None)
            if fn is None:
                raise OSError('此平台不支持安全发布文件，请保留原目录。')
            fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            fn.restype = ctypes.c_int
            if fn(self.fd, os.fsencode(a), self.fd, os.fsencode(b), flag):
                code = ctypes.get_errno()
                raise OSError(code, os.strerror(code), str(self.path / target))


def file_digest(directory, name):
    with os.fdopen(directory.open(name, os.O_RDONLY), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise OSError('不是普通文件。')
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise OSError('文件在读取时发生变化。')
        return identity(after), digest


def remove_owned(directory, name, expected, digest=None, is_directory=False, validate=None):
    """Quarantine before checking ownership; never unlink a raced-in object."""
    try:
        if identity(directory.stat(name)) != expected:
            return False
    except FileNotFoundError:
        return True
    quarantine = '.agentscribe-clean-' + uuid4().hex
    directory.rename(name, quarantine, exclusive=True)
    try:
        info = directory.stat(quarantine)
        if identity(info) != expected or stat.S_ISDIR(info.st_mode) != is_directory:
            raise OSError('文件归属已变化')
        if digest is not None and file_digest(directory, quarantine) != (expected, digest):
            raise OSError('文件内容已变化')
        if validate is not None:
            validate()
        directory.unlink(quarantine, directory=is_directory)
        return True
    except OSError:
        # Atomic no-replace restore cannot overwrite a concurrent new entry.
        try:
            directory.rename(quarantine, name, exclusive=True)
        except OSError as exc:
            raise OSError(f'未删除变化的文件，请检查保留项：{directory.path / quarantine}') from exc
        return False


def atomic_write(path, content, *, exclusive=False, expected_parent=None):
    path = Path(path)
    with Directory(path.parent) as directory:
        if expected_parent is not None and identity(directory.info) != expected_parent:
            raise OSError('目标目录已变化，请重新选择保存位置。')
        temporary = '.agentscribe-write-' + uuid4().hex + '.tmp'
        owned = None
        try:
            fd = (directory.create_temporary(temporary) if expected_parent is not None
                  else directory.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL))
            with os.fdopen(fd, 'w+b' if expected_parent is not None else 'wb') as stream:
                owned = identity(os.fstat(stream.fileno()))
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                if expected_parent is not None:
                    stream.seek(0)
                    if (identity(directory.stat(temporary)) != owned
                            or hashlib.file_digest(stream, 'sha256').hexdigest() != hashlib.sha256(content).hexdigest()):
                        raise OSError('临时文件已变化，导出未完成。')
                    directory.publish(temporary, path.name, stream.fileno(), exclusive=exclusive)
                    return owned
            if identity(directory.stat(temporary)) != owned:
                raise OSError('临时文件已被替换，保存未完成。')
            directory.rename(temporary, path.name, exclusive=exclusive)
            return owned
        finally:
            if owned is not None:
                try:
                    if not remove_owned(directory, temporary, owned):
                        raise OSError('临时文件变化或无法清理，已保留。')
                except OSError as exc:
                    from . import diagnostic_log as diag
                    diag.exception('storage_temporary_cleanup_failed', exc)


@contextmanager
def checked_parent(root, relative, directories):
    root, relative = Path(root), Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('迁移记录无效')
    # Opening each level without following mappings also pins the final parent.
    with Directory(root) as base:
        if identity(base.info) != directories['.']:
            raise OSError('迁移根目录已被替换')
        with Directory(root / relative.parent) as parent:
            if identity(parent.info) != directories.get(str(relative.parent)):
                raise OSError('迁移目录已被替换')
            for ancestor in [relative.parent, *relative.parent.parents]:
                if str(ancestor) not in directories:
                    raise OSError('迁移目录未记录')
                with Directory(root / ancestor) as current:
                    if identity(current.info) != directories[str(ancestor)]:
                        raise OSError('迁移目录已被替换')
            yield parent
