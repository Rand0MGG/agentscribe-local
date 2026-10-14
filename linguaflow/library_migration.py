"""Verified, cancellable library relocation; originals survive failed copies."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal

from .library import Library


class MigrationCancelled(Exception):
    pass


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def library_entries(root, cancelled):
    """Snapshot all user entries, rejecting mappings and excluding process-owned locks."""
    directories, files = [], {}
    for path in sorted(root.rglob('*')):
        if cancelled():
            raise MigrationCancelled('迁移已取消，原录音保留。')
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('保存目录包含快捷映射，请移除映射后重试；原文件未修改。')
        if path.name in ('.recording.lock', '.knowledge.lock', '.library-migration.lock', '.agentscribe-migration.json'):
            continue
        relative = path.relative_to(root)
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            files[relative] = path.stat().st_size
    return directories, files


def checked_library_copy(source, target):
    """Keep folder/recording identities intact before committing either copy path."""
    library = Library(target)
    if set(source.paths) - set(library.paths):
        raise ValueError('新目录中的录音索引不完整，原目录仍保留。')
    return library


def migrate_library(source, destination, *, cancelled=lambda: False, progress=lambda value: None):
    """Copy the complete library, including trash/materials, without overwriting.

    Destination must be empty. Publication uses exclusive mkdir/file creation so
    even a concurrent name collision cannot replace a file. Originals are only
    removed by finish_migration AFTER the caller commits its preference.
    """
    root, target = source.root, Path(destination).expanduser().resolve()
    if root == target:
        return source, []
    if root in target.parents or target in root.parents:
        raise ValueError('新保存位置不能是原目录的子目录或父目录，请选择独立目录。')
    target.mkdir(parents=True, exist_ok=True)
    journal = target / '.agentscribe-migration.json'
    if journal.is_file() and not journal.is_symlink():
        saved = json.loads(journal.read_text(encoding='utf-8'))
        if saved.get('source') == str(root) and saved.get('state') == 'copied':
            verified = saved['verified']
            directories, current_files = library_entries(root, cancelled)
            if (set(current_files) != {Path(relative) for relative, _ in verified}
                    or saved.get('directories') != [str(relative) for relative in directories]):
                raise ValueError('原目录内容已变化或迁移记录不完整，请选择其他空目录；原文件和副本均保留。')
            for relative, digest in verified:
                relative = Path(relative)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('迁移记录无效，原文件保留。')
                if cancelled():
                    raise MigrationCancelled('迁移已取消，原录音保留。')
                if checksum(target / relative) != digest or checksum(root / relative) != digest:
                    raise ValueError('迁移副本或原文件已变化，请选择其他空目录。')
            if library_entries(root, cancelled) != (directories, current_files):
                raise ValueError('原目录内容在校验时发生变化，请选择其他空目录；原文件和副本均保留。')
            return checked_library_copy(source, target), [(Path(relative), digest) for relative, digest in verified]
    if any(target.iterdir()):
        raise ValueError('新目录已有文件。请选择空目录，已有内容不会被覆盖。')
    stage = target / ('.agentscribe-migration-' + uuid4().hex)
    stage.mkdir()
    files, published, published_hashes = [], [], {}

    def check():
        if cancelled():
            raise MigrationCancelled('迁移已取消，原录音保留。')

    try:
        check()
        directories, snapshot_files = library_entries(root, cancelled)
        for relative in directories:
            (stage / relative).mkdir(parents=True, exist_ok=True)
        files = list(snapshot_files.items())
        total = sum(size for _, size in files)
        if shutil.disk_usage(target).free < total + 1024**2:
            raise OSError('新位置的磁盘空间不足，请释放空间或选择其他目录。')
        verified, completed = [], 0
        for relative, size in files:
            check()
            original, copied = root / relative, stage / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            before = original.stat()
            digest = hashlib.sha256()
            with original.open('rb') as incoming, copied.open('xb') as outgoing:
                while chunk := incoming.read(1024**2):
                    check()
                    outgoing.write(chunk)
                    digest.update(chunk)
                    completed += len(chunk)
                    progress(min(95., completed / max(1, total) * 95))
                outgoing.flush()
                os.fsync(outgoing.fileno())
            after = original.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or checksum(copied) != digest.hexdigest():
                raise OSError('录音文件在迁移时发生变化，已停止迁移；请结束其他窗口的录音后重试。')
            shutil.copystat(original, copied)
            verified.append((relative, digest.hexdigest()))
        # Paths without explicit folder markers retain their original identity.
        for folder in source.index['folders']:
            relative = source.paths[folder['id']].relative_to(root) / Library.folder_file
            if not (stage / relative).exists():
                Library._write(stage / relative, {'id': folder['id']})
        # An external editor is not governed by our application locks. Recheck
        # the snapshot before publishing rather than quietly copying stale data.
        for relative, digest in verified:
            check()
            if checksum(root / relative) != digest:
                raise OSError('原文件在校验后发生变化，迁移未完成；原录音保留。')
        if library_entries(root, cancelled) != (directories, snapshot_files):
            raise OSError('原目录内容在迁移时发生变化，迁移未完成；原录音保留。')
        check()
        if any(path != stage for path in target.iterdir()):
            raise FileExistsError('新目录已出现其他文件，迁移停止；已有内容未覆盖。')
        verified_hashes = dict(verified)
        for path in sorted(stage.rglob('*')):
            check()
            final = target / path.relative_to(stage)
            if path.is_dir():
                final.mkdir()  # Exclusive creation.
            else:
                expected = verified_hashes.get(path.relative_to(stage))
                published_hashes[final] = expected or checksum(path)
                try:
                    os.link(path, final)  # Exclusive, same-volume publication.
                except FileExistsError:
                    raise
                except OSError:
                    # External exFAT/FAT volumes do not support hard links.
                    # Exclusive copying still cannot replace an existing file.
                    with path.open('rb') as incoming, final.open('xb') as outgoing:
                        published.append(final)
                        partial_hash = hashlib.sha256()
                        try:
                            while chunk := incoming.read(1024**2):
                                check()
                                outgoing.write(chunk)
                                partial_hash.update(chunk)
                            outgoing.flush()
                            os.fsync(outgoing.fileno())
                        except Exception:
                            published_hashes[final] = partial_hash.hexdigest()
                            raise
                    if checksum(final) != published_hashes[final]:
                        raise OSError('迁移副本校验失败，原录音保留。')
                    continue
            published.append(final)
        library = checked_library_copy(source, target)
        if library_entries(root, cancelled) != (directories, snapshot_files):
            raise OSError('原目录内容在迁移时发生变化，迁移未完成；原录音保留。')
        Library._write(journal, {'source': str(root), 'state': 'copied',
                                'directories': [str(relative) for relative in directories],
                                'verified': [(str(relative), digest) for relative, digest in verified]})
        progress(100.)
        return library, verified
    except Exception:
        # Only remove unchanged published files; a changed/new file is retained.
        for path in reversed(published):
            try:
                if path.is_dir():
                    path.rmdir()
                elif path.is_file() and not path.is_symlink() and checksum(path) == published_hashes[path]:
                    path.unlink()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(stage)


def finish_migration(root, target, verified):
    """After preference commit, remove only unchanged, verified originals.

    Changed files are deliberately retained and reported. An interruption during
    this cleanup leaves a complete destination and harmless old duplicates.
    """
    retained = []
    for relative, digest in verified:
        path = root / relative
        try:
            copied = target / relative
            if path.is_symlink() or copied.is_symlink() or checksum(copied) != digest or checksum(path) != digest:
                retained.append(str(relative))
            else:
                path.unlink()
        except OSError:
            retained.append(str(relative))
    for path in sorted(root.rglob('*'), key=lambda path: len(path.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            try:
                path.rmdir()
            except OSError:
                pass
    return retained


class LibraryMigration(QObject):
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
        self._finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

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
                (target / '.agentscribe-migration.json').unlink(missing_ok=True)
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
