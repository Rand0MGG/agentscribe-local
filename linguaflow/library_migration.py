"""Verified relocation with owned publication and identity-bound cleanup."""
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from .events import Connection, Owner, Signal
from .library import Library
from .storage_io import Directory, atomic_write, checked_parent, file_digest, identity, remove_owned


class MigrationCancelled(Exception):
    pass


class VerifiedCopy(list):
    def __init__(self, files, record):
        super().__init__(files)
        self.record = record


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def library_entries(root, cancelled):
    directories, files = [], {}
    for path in sorted(root.rglob('*')):
        if cancelled():
            raise MigrationCancelled('迁移已取消，原录音保留。')
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('保存目录包含快捷映射，请移除映射后重试；原文件未修改。')
        if path.name.removesuffix('.guard') in ('.recording.lock', '.knowledge.lock', '.library-migration.lock'):
            continue
        relative = path.relative_to(root)
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            files[relative] = path.stat().st_size
    return directories, files


def directory_ids(root, directories):
    result = {}
    for relative in [Path('.'), *directories]:
        with Directory(root / relative) as directory:
            result[str(relative)] = identity(directory.info)
    return result


def read_verified(root, relative, directories):
    with checked_parent(root, relative, directories) as parent:
        return file_digest(parent, Path(relative).name)


def checked_library_copy(source, target):
    library = Library(target)
    if set(source.paths) - set(library.paths):
        raise ValueError('新目录中的录音索引不完整，原目录仍保留。')
    return library


def migrate_library(source, destination, *, cancelled=lambda: False, progress=lambda value: None):
    root, target = source.root, Path(destination).expanduser().resolve()
    if root == target:
        return source, []
    if root in target.parents or target in root.parents:
        raise ValueError('新保存位置不能是原目录的子目录或父目录，请选择独立目录。')
    target.mkdir(parents=True, exist_ok=True)
    with Directory(target) as target_handle:
        return _copy(source, target, target_handle, cancelled, progress)


def _copy(source, target, target_handle, cancelled, progress):
    root = source.root
    journal = target / '.agentscribe-migration.json'
    if (root / journal.name).exists() or (root / journal.name).is_symlink():
        raise ValueError('原目录包含迁移记录同名文件，请先保留并移出该文件再重试；不会覆盖。')
    directories, snapshot_files = library_entries(root, cancelled)
    source_dirs = directory_ids(root, directories)
    target_dirs = {'.': identity(target_handle.info)}
    if journal.is_file() and not journal.is_symlink():
        with os.fdopen(target_handle.open(journal.name, os.O_RDONLY), 'r', encoding='utf-8') as stream:
            saved = json.load(stream)
            journal_id = identity(os.fstat(stream.fileno()))
        if saved.get('source') == str(root) and saved.get('state') == 'copied':
            files = saved['verified']
            if (set(snapshot_files) != {Path(relative) for relative, _ in files}
                    or saved.get('directories') != [str(p) for p in directories]
                    or not all(k in saved for k in ('source_dirs', 'target_dirs', 'source_ids', 'target_ids'))):
                raise ValueError('原目录内容已变化或迁移记录不完整，请选择其他空目录；原文件和副本均保留。')
            for relative, digest in files:
                if cancelled():
                    raise MigrationCancelled('迁移已取消，原录音保留。')
                left = read_verified(root, relative, saved['source_dirs'])
                right = read_verified(target, relative, saved['target_dirs'])
                if (left != (saved['source_ids'][relative], digest)
                        or right != (saved['target_ids'][relative], digest) or left[0] == right[0]):
                    raise ValueError('迁移副本或原文件已变化，请选择其他空目录。')
            if library_entries(root, cancelled) != (directories, snapshot_files):
                raise ValueError('原目录内容已变化，原文件和副本均保留。')
            library = checked_library_copy(source, target)
            saved['journal_id'] = journal_id
            saved['journal_hash'] = file_digest(target_handle, journal.name)[1]
            return library, VerifiedCopy([(Path(p), h) for p, h in files], saved)
    if any(target.iterdir()):
        raise ValueError('新目录已有文件。请选择空目录，已有内容不会被覆盖。')
    stage_name = '.agentscribe-migration-' + uuid4().hex
    os.mkdir(target_handle.name(stage_name), **target_handle.kwargs())
    stage_id = identity(target_handle.stat(stage_name))
    stage = target / stage_name
    stage_dirs = {'.': stage_id}
    published, verified = [], []
    source_ids, target_ids = {}, {}

    def check():
        if cancelled():
            raise MigrationCancelled('迁移已取消，原录音保留。')
        with Directory(target) as current:
            if identity(current.info) != target_dirs['.']:
                raise OSError('目标根目录已变化，原录音保留。')

    def mkdir(root_path, relative, ids):
        with checked_parent(root_path, relative, ids) as parent:
            os.mkdir(parent.name(relative.name), **parent.kwargs())
            ids[str(relative)] = identity(parent.stat(relative.name))

    try:
        total = sum(snapshot_files.values())
        if shutil.disk_usage(target).free < total + 1024**2:
            raise OSError('新位置的磁盘空间不足，请释放空间或选择其他目录。')
        for relative in directories:
            check()
            mkdir(stage, relative, stage_dirs)
        completed = 0
        for relative in snapshot_files:
            check()
            with checked_parent(root, relative, source_dirs) as origin, checked_parent(stage, relative, stage_dirs) as dest:
                with os.fdopen(origin.open(relative.name, os.O_RDONLY), 'rb') as incoming, os.fdopen(
                        dest.open(relative.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL), 'wb') as outgoing:
                    before = os.fstat(incoming.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise OSError('原文件不是普通文件')
                    digest = hashlib.sha256()
                    while chunk := incoming.read(1024**2):
                        check()
                        outgoing.write(chunk)
                        digest.update(chunk)
                        completed += len(chunk)
                        progress(min(95., completed / max(1, total) * 95))
                    outgoing.flush()
                    # Preserve recording/material times and permissions on the
                    # owned staging file, never through a replaceable source path.
                    if hasattr(os, 'fchmod'):
                        os.fchmod(outgoing.fileno(), stat.S_IMODE(before.st_mode))
                    stamp = (before.st_atime_ns, before.st_mtime_ns)
                    if os.utime in os.supports_fd:
                        os.utime(outgoing.fileno(), ns=stamp)
                    else:
                        os.utime(dest.name(relative.name), ns=stamp)
                    os.fsync(outgoing.fileno())
                value = digest.hexdigest()
                if file_digest(origin, relative.name) != (identity(before), value):
                    raise OSError('原文件在迁移时发生变化，原录音保留。')
                source_ids[str(relative)] = identity(before)
                verified.append((relative, value))
        for folder in source.index['folders']:
            relative = source.paths[folder['id']].relative_to(root) / Library.folder_file
            if not (stage / relative).exists():
                Library._write(stage / relative, {'id': folder['id']})
        if library_entries(root, cancelled) != (directories, snapshot_files):
            raise OSError('原目录内容在迁移时发生变化，迁移未完成；原录音保留。')
        for relative, digest in verified:
            if read_verified(root, relative, source_dirs) != (source_ids[str(relative)], digest):
                raise OSError('原文件在校验后发生变化，原录音保留。')
        check()
        if any(p != stage for p in target.iterdir()):
            raise FileExistsError('新目录已出现其他文件，迁移停止；已有内容未覆盖。')
        for relative in directories:
            check()
            mkdir(target, relative, target_dirs)
            published.append((relative, target_dirs[str(relative)], None, True))
        # Stage files include generated folder identity markers.
        for path in sorted(stage.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(stage)
            check()
            with checked_parent(stage, relative, stage_dirs) as origin, checked_parent(target, relative, target_dirs) as dest:
                # Link our independent staged copy where supported. A volume
                # without hardlinks uses an exclusive file with audited partial bytes.
                value = file_digest(origin, path.name)[1]
                try:
                    if origin.fd is None:
                        os.link(origin.name(path.name), dest.name(path.name))
                    else:
                        os.link(path.name, path.name, src_dir_fd=origin.fd,
                                dst_dir_fd=dest.fd, follow_symlinks=False)
                except FileExistsError:
                    raise
                except OSError:
                    with os.fdopen(origin.open(path.name, os.O_RDONLY), 'rb') as incoming:
                        fd = dest.open(path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL)
                        owned = identity(os.fstat(fd))
                        entry = len(published)
                        published.append((relative, owned, 'unverified', False))
                        with os.fdopen(fd, 'r+b', buffering=0) as outgoing:
                            try:
                                while chunk := incoming.read(1024**2):
                                    check()
                                    view = memoryview(chunk)
                                    while view:
                                        written = os.write(fd, view)
                                        if not written:
                                            raise OSError('迁移文件写入未推进')
                                        view = view[written:]
                                os.fsync(fd)
                            finally:
                                outgoing.seek(0)
                                actual = hashlib.file_digest(outgoing, 'sha256').hexdigest()
                                published[entry] = (relative, owned, actual, False)
                else:
                    owned = identity(dest.stat(path.name))
                    published.append((relative, owned, value, False))
                target_ids[str(relative)] = owned
                if file_digest(origin, path.name)[1] != file_digest(dest, path.name)[1]:
                    raise OSError('迁移副本校验失败，原录音保留。')
        check()
        library = checked_library_copy(source, target)
        if library_entries(root, cancelled) != (directories, snapshot_files):
            raise OSError('原目录内容在迁移时发生变化，迁移未完成；原录音保留。')
        record = dict(source=str(root), state='copied', directories=[str(p) for p in directories],
                      verified=[(str(p), h) for p, h in verified], source_dirs=source_dirs,
                      target_dirs=target_dirs, source_ids=source_ids, target_ids=target_ids)
        atomic_write(journal, json.dumps(record, ensure_ascii=False).encode('utf-8'), exclusive=True)
        record['journal_id'], record['journal_hash'] = file_digest(target_handle, journal.name)
        published.append((Path(journal.name), record['journal_id'], record['journal_hash'], False))
        progress(100.)
        return library, VerifiedCopy(verified, record)
    except BaseException as error:
        retained = []
        for relative, owned, digest, is_dir in reversed(published):
            try:
                with checked_parent(target, relative, target_dirs) as parent:
                    if not remove_owned(parent, relative.name, owned, digest, is_directory=is_dir):
                        retained.append(str(relative))
            except OSError:
                retained.append(str(relative))
        if retained and isinstance(error, Exception):
            raise OSError(str(error) + '；部分目标项已变化或无法清理，已保留，请检查：' + ', '.join(retained)) from error
        raise
    finally:
        # rmtree uses descriptor-relative traversal on POSIX. Never follow a
        # replaced stage name, and never let cleanup hide the original failure.
        try:
            if identity(target_handle.stat(stage_name)) == stage_id:
                if target_handle.fd is not None:
                    shutil.rmtree(stage_name, dir_fd=target_handle.fd)
                else:
                    shutil.rmtree(stage)
        except OSError as exc:
            from . import diagnostic_log as diag
            diag.exception('migration_stage_cleanup_failed', exc)


def finish_migration(root, target, verified):
    record = getattr(verified, 'record', None)
    if not record:
        return [str(relative) for relative, _ in verified]
    retained = []
    for relative, digest in verified:
        try:
            with checked_parent(root, relative, record['source_dirs']) as origin, checked_parent(
                    target, relative, record['target_dirs']) as dest:
                left, right = file_digest(origin, relative.name), file_digest(dest, relative.name)
                if (left != (record['source_ids'][str(relative)], digest)
                        or right != (record['target_ids'][str(relative)], digest) or left[0] == right[0]):
                    raise OSError('原件或独立副本已变化')
                def still_copied():
                    if read_verified(target, relative, record['target_dirs']) != right:
                        raise OSError('目标副本在清理时发生变化')
                if not remove_owned(origin, relative.name, left[0], digest, validate=still_copied):
                    raise OSError('原件在清理时发生变化')
        except (OSError, ValueError):
            retained.append(str(relative))
    for name in reversed(record['directories']):
        relative = Path(name)
        try:
            with checked_parent(root, relative, record['source_dirs']) as origin, checked_parent(
                    target, relative, record['target_dirs']) as dest:
                if identity(dest.stat(relative.name)) != record['target_dirs'][name]:
                    raise OSError('目标目录已变化')
                if not remove_owned(origin, relative.name, record['source_dirs'][name], is_directory=True):
                    raise OSError('原目录非空或已变化')
        except (OSError, ValueError):
            retained.append(name + '/')
    return retained


class LibraryMigration(Owner):
    progress = Signal(float)
    copied = Signal(object, object, str)
    cleaned = Signal(object)
    _finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.job = None
        self.cancelled = Event()
        self.result = None
        self.error = ''
        self.cleaning = False
        self._finished.connect(self._deliver, Connection.Queued)

    @property
    def busy(self):
        return self.job is not None

    def start(self, library, path):
        if self.busy:
            return False
        self.cancelled.clear()
        self.result, self.error, self.cleaning = None, '', False
        def run():
            try:
                self.result = migrate_library(library, path, cancelled=self.cancelled.is_set,
                                              progress=self.progress.emit)
            except Exception as exc:
                self.error = str(exc)
            finally:
                self._finished.emit()
        self.job = Thread(target=run)
        self.job.start()
        return True

    def cleanup(self, root, verified):
        self.cleaning = True
        def run():
            try:
                target = self.result[0].root
                self.result = finish_migration(root, target, verified)
                # Completed relocation no longer needs the resumable copy record.
                record = getattr(verified, 'record', {})
                if record.get('journal_id'):
                    with checked_parent(target, Path('.agentscribe-migration.json'), record['target_dirs']) as directory:
                        if not remove_owned(directory, '.agentscribe-migration.json', record['journal_id'], record.get('journal_hash')):
                            self.result.append('.agentscribe-migration.json')
            except Exception as exc:
                self.result = [str(exc)]
            finally:
                self._finished.emit()
        self.job = Thread(target=run)
        self.job.start()

    def cancel(self):
        if not self.cleaning:
            self.cancelled.set()

    def _deliver(self):
        self.job.join()
        self.job = None
        if self.cleaning:
            self.cleaned.emit(self.result)
        else:
            library, verified = self.result or (None, [])
            self.copied.emit(library, verified, self.error)
