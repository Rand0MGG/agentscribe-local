"""Native filesystem regressions for dot R28–R35; synthetic data only."""
import errno
import os
import shutil
import time

import pytest

from linguaflow.core import Caption
from linguaflow.library import Library
from linguaflow.library_migration import finish_migration, migrate_library
from linguaflow.settings_store import SettingsStore
from linguaflow.storage_io import Directory, atomic_write, identity
from tests.test_desktop_service import desktop as desktop
from tests.test_desktop_service import drain
from tests.test_library_migration import populated


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def assert_preserved(root, before):
    assert all((root / p).read_bytes() == content for p, content in before.items())


def symlink(path, target, directory=False):
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip('native symlink permission unavailable')


@pytest.mark.p1
@pytest.mark.parametrize('length', [61, 62, 63, 64])
def test_duplicate_name_trash_and_restore_remain_visible(tmp_path, length):
    library = Library(tmp_path)
    name = '课' * length
    library.create('inbox', {}, name)
    duplicate = library.create('inbox', {}, name)
    assert len(duplicate['name']) <= 64 and duplicate['name'].endswith(' (2)')
    library.save(duplicate, [Caption(1, 0, 1, 'preserve', 'en')])
    original = snapshot(library.directory(duplicate['id']))
    token = library.trash(duplicate)
    assert token in {row['token'] for row in library.deleted()}
    restored = library.restore_deleted(token)
    assert len(restored.name) <= 64
    assert_preserved(restored, original)
    folder = library.folder(name)
    assert len(library.folder(name)['name']) <= 64
    assert folder['name'] == name


@pytest.mark.p1
def test_old_overlong_duplicate_is_recoverable_without_rewriting_receipt(tmp_path):
    library = Library(tmp_path)
    item = library.create('inbox', {}, 'old')
    old = library.directory(item['id'])
    long_name = '课' * 64 + ' (2)'
    old.rename(old.with_name(long_name))
    library.refresh()
    item = next(row for row in library.index['sessions'] if row['id'] == item['id'])
    before = snapshot(library.directory(item['id']))
    token = library.trash(item)
    receipt = tmp_path / library.trash_name / token / 'restore.json'
    receipt_bytes = receipt.read_bytes()
    assert library.deleted()[0]['name'] == long_name
    restored = library.restore_deleted(token)
    assert len(restored.name) <= 64
    assert_preserved(restored, before)
    assert receipt.read_bytes() == receipt_bytes


@pytest.mark.p0
@pytest.mark.parametrize('name', ['session.json', '定稿.srt', '定稿.txt'])
@pytest.mark.parametrize('link_kind', ['symlink', 'hardlink'])
def test_save_ignores_foreign_fixed_temporary_names(tmp_path, name, link_kind):
    library = Library(tmp_path / 'library')
    item = library.create('inbox', {})
    outside = tmp_path / 'original.wav'
    content = b'original audio must not be touched'
    outside.write_bytes(content)
    old_temp = library.directory(item['id']) / (name + '.tmp')
    if link_kind == 'hardlink':
        os.link(outside, old_temp)
    else:
        symlink(old_temp, outside)
    library.save(item, [Caption(1, 0, 1, 'saved normally', 'en')])
    assert outside.read_bytes() == content and old_temp.read_bytes() == content
    assert library.load(item)[1][0].source == 'saved normally'


@pytest.mark.p0
@pytest.mark.parametrize('operation', ['fsync', 'rename'])
def test_atomic_write_failure_keeps_original_and_cleans_owned_temp(tmp_path, monkeypatch, operation):
    output = tmp_path / 'session.json'
    output.write_bytes(b'old durable result')
    def fail(*args, **kwargs):
        raise OSError('injected write failure')
    with monkeypatch.context() as patch:
        if operation == 'fsync':
            patch.setattr(os, 'fsync', fail)
        else:
            original = Directory.rename
            def fail_publish(directory, source, target, **kwargs):
                if target == output.name:
                    fail()
                return original(directory, source, target, **kwargs)
            patch.setattr(Directory, 'rename', fail_publish)
        with pytest.raises(OSError):
            atomic_write(output, b'new')
    assert output.read_bytes() == b'old durable result'
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.p0
def test_atomic_cleanup_preserves_replaced_temporary(tmp_path, monkeypatch):
    output = tmp_path / 'session.json'
    output.write_bytes(b'original')
    original = Directory.rename
    replacement = []
    def replace_temp(directory, source, target, **kwargs):
        if target == output.name:
            path = directory.path / source
            path.rename(path.with_suffix('.owned'))
            path.write_bytes(b'other process')
            replacement.append(path)
            raise OSError('publication failed')
        return original(directory, source, target, **kwargs)
    monkeypatch.setattr(Directory, 'rename', replace_temp)
    with pytest.raises(OSError):
        atomic_write(output, b'new')
    assert output.read_bytes() == b'original'
    assert replacement[0].read_bytes() == b'other process'


@pytest.mark.p0
@pytest.mark.parametrize('side', ['source', 'target'])
@pytest.mark.parametrize('level', ['root', 'ancestor'])
def test_cleanup_rejects_replaced_directory_mapping(tmp_path, side, level):
    source, item, _ = populated(tmp_path / 'old')
    copied, verified = migrate_library(source, tmp_path / 'new')
    library = source if side == 'source' else copied
    path = library.root if level == 'root' else library.directory(item['id'])
    outside = tmp_path / 'outside'
    shutil.copytree(path, outside)
    before = snapshot(outside)
    saved = path.with_name(path.name + '-moved')
    path.rename(saved)
    symlink(path, outside, True)
    retained = finish_migration(source.root, copied.root, verified)
    assert retained
    assert_preserved(outside, before)
    if side == 'source':
        assert_preserved(saved, before)
    else:
        assert (source.directory(item['id']) / '录音.wav').read_bytes() == b'fixture PCM bytes' * 1000


@pytest.mark.p0
@pytest.mark.parametrize('link_kind', ['symlink', 'hardlink'])
def test_retry_and_cleanup_reject_target_audio_alias_to_original(tmp_path, link_kind):
    source, item, _ = populated(tmp_path / 'old')
    copied, verified = migrate_library(source, tmp_path / 'new')
    original = source.directory(item['id']) / '录音.wav'
    target = copied.directory(item['id']) / '录音.wav'
    before = original.read_bytes()
    target.unlink()
    if link_kind == 'hardlink':
        os.link(original, target)
    else:
        symlink(target, original)
    with pytest.raises((OSError, ValueError)):
        migrate_library(source, copied.root)
    assert str(original.relative_to(source.root)) in finish_migration(source.root, copied.root, verified)
    assert original.read_bytes() == before


@pytest.mark.p0
def test_target_changed_after_first_cleanup_check_restores_original(tmp_path, monkeypatch):
    source, item, _ = populated(tmp_path / 'old')
    copied, verified = migrate_library(source, tmp_path / 'new')
    audio = source.directory(item['id']) / '录音.wav'
    target_audio = copied.directory(item['id']) / '录音.wav'
    before = audio.read_bytes()
    rename = Directory.rename
    changed = []
    def race(directory, name, target, **kwargs):
        if directory.path == audio.parent and name == audio.name and not changed:
            target_audio.unlink()
            os.link(audio, target_audio)
            changed.append(True)
        return rename(directory, name, target, **kwargs)
    monkeypatch.setattr(Directory, 'rename', race)
    assert str(audio.relative_to(source.root)) in finish_migration(source.root, copied.root, verified)
    assert audio.read_bytes() == before


@pytest.mark.p2
@pytest.mark.parametrize('change', ['new', 'missing_target', 'replaced_source'])
def test_cleanup_preserves_unverified_empty_directories(tmp_path, change):
    source, _, _ = populated(tmp_path / 'old')
    empty = source.root / 'empty'
    empty.mkdir()
    copied, verified = migrate_library(source, tmp_path / 'new')
    if change == 'new':
        empty = source.root / 'added after copy'
        empty.mkdir()
    elif change == 'missing_target':
        (copied.root / empty.name / Library.folder_file).unlink(missing_ok=True)
        (copied.root / empty.name).rmdir()
    else:
        empty.rename(source.root / 'old-empty')
        empty.mkdir()
    expected = identity(empty.stat())
    retained = finish_migration(source.root, copied.root, verified)
    assert empty.is_dir() and identity(empty.stat()) == expected
    if change != 'new':
        assert empty.name + '/' in retained


@pytest.mark.p0
@pytest.mark.parametrize('change', ['root_mapping', 'ancestor_mapping', 'empty_directory', 'file'])
def test_failed_publication_rollback_preserves_replacements(tmp_path, monkeypatch, change):
    import linguaflow.library_migration as module
    source, item, _ = populated(tmp_path / 'old')
    recording = source.directory(item['id']).relative_to(source.root)
    before = snapshot(source.root)
    target = tmp_path / 'new'
    external = tmp_path / 'external'
    saved, attempted = [], []
    def fail_after_publication(_source, _target):
        attempted.append(True)
        path = target if change == 'root_mapping' else target / recording
        if change == 'file':
            path = path / '录音.wav'
            path.rename(path.with_suffix('.moved'))
            path.write_bytes(b'replacement audio')
        else:
            if change == 'empty_directory':
                path.rename(path.with_name('moved'))
                path.mkdir()
            else:
                shutil.copytree(path, external)
                path.rename(path.with_name(path.name + '-moved'))
                symlink(path, external, True)
        saved.append((path, identity(path.lstat())))
        raise OSError('failure after publication')
    monkeypatch.setattr(module, 'checked_library_copy', fail_after_publication)
    with pytest.raises(OSError) as failed:
        migrate_library(source, target)
    if not saved:
        # Windows pins the target root without delete sharing; replacing it
        # must fail before the mutation, then ordinary rollback must finish.
        assert os.name == 'nt' and change == 'root_mapping' and attempted
        assert isinstance(failed.value, PermissionError)
        assert_preserved(source.root, before)
        assert not list(target.iterdir())
        return
    path, expected = saved[0]
    assert identity(path.lstat()) == expected
    if change == 'file':
        assert path.read_bytes() == b'replacement audio'
    elif change.endswith('mapping'):
        assert (external / (recording / '录音.wav' if change == 'root_mapping' else '录音.wav')).read_bytes() == b'fixture PCM bytes' * 1000
    assert_preserved(source.root, before)


@pytest.mark.p0
@pytest.mark.parametrize('name', ['.agentscribe-migration.json', '.agentscribe-migration.json.tmp'])
def test_source_journal_namespace_is_never_overwritten(tmp_path, name):
    source, _, _ = populated(tmp_path / 'old')
    original = source.root / name
    original.write_bytes(b'unrelated source material')
    if name.endswith('.tmp'):
        copied, _ = migrate_library(source, tmp_path / 'new')
        assert (copied.root / name).read_bytes() == original.read_bytes()
    else:
        with pytest.raises(ValueError, match='同名'):
            migrate_library(source, tmp_path / 'new')
    assert original.read_bytes() == b'unrelated source material'


@pytest.mark.p0
@pytest.mark.parametrize('kind', ['regular', 'hardlink'])
def test_concurrent_journal_is_not_replaced_or_deleted(tmp_path, monkeypatch, kind):
    import linguaflow.library_migration as module
    source, item, _ = populated(tmp_path / 'old')
    original = source.directory(item['id']) / '录音.wav'
    before = snapshot(source.root)
    writer = module.atomic_write
    def race(path, content, **kwargs):
        if kind == 'hardlink':
            os.link(original, path)
        else:
            path.write_bytes(b'other writer')
        return writer(path, content, **kwargs)
    monkeypatch.setattr(module, 'atomic_write', race)
    target = tmp_path / 'new'
    with pytest.raises(FileExistsError):
        migrate_library(source, target)
    expected = original.read_bytes() if kind == 'hardlink' else b'other writer'
    assert (target / '.agentscribe-migration.json').read_bytes() == expected
    assert_preserved(source.root, before)


@pytest.mark.p2
@pytest.mark.parametrize('failure', ['fsync', 'rename'])
def test_journal_failure_rolls_back_and_same_target_can_retry(tmp_path, monkeypatch, failure):
    import linguaflow.library_migration as module
    source, _, _ = populated(tmp_path / 'old')
    before = snapshot(source.root)
    writer = module.atomic_write
    def fail_journal(path, content, **kwargs):
        with monkeypatch.context() as patch:
            if failure == 'fsync':
                def fail_sync(fd):
                    raise OSError('journal fsync failed')
                patch.setattr(os, 'fsync', fail_sync)
            else:
                rename = Directory.rename
                def fail_rename(directory, name, target, **options):
                    if target == path.name:
                        raise OSError('journal replace failed')
                    return rename(directory, name, target, **options)
                patch.setattr(Directory, 'rename', fail_rename)
            return writer(path, content, **kwargs)
    target = tmp_path / 'new'
    with monkeypatch.context() as patch:
        patch.setattr(module, 'atomic_write', fail_journal)
        with pytest.raises(OSError):
            migrate_library(source, target)
    assert not list(target.iterdir())
    assert_preserved(source.root, before)
    copied, verified = migrate_library(source, target)
    assert not finish_migration(source.root, copied.root, verified)


@pytest.mark.p2
def test_partial_fallback_write_is_removed_and_retry_succeeds(tmp_path, monkeypatch):
    source, _, _ = populated(tmp_path / 'old')
    before = snapshot(source.root)
    write = os.write
    partial = []
    def no_links(*args, **kwargs):
        raise OSError(errno.ENOTSUP, 'hardlinks unsupported')
    def short_failure(fd, content):
        write(fd, content[:min(7, len(content))])
        partial.append(True)
        raise OSError('write failed after a partial kernel write')
    target = tmp_path / 'new'
    with monkeypatch.context() as patch:
        patch.setattr(os, 'link', no_links)
        patch.setattr(os, 'write', short_failure)
        with pytest.raises(OSError, match='partial'):
            migrate_library(source, target)
    assert partial and not list(target.iterdir())
    assert_preserved(source.root, before)
    copied, verified = migrate_library(source, target)
    assert not finish_migration(source.root, copied.root, verified)


@pytest.mark.p1
def test_migration_commits_preferences_once_and_reopens_new_library(desktop, tmp_path, monkeypatch):
    desktop._create_recording(name='single commit')
    desktop._caption(Caption(1, 0, 1, 'saved', 'en'))
    desktop._save('complete')
    drain(desktop)
    destination = tmp_path / 'new'
    sync = desktop.prefs.sync
    calls = []
    def one_write():
        calls.append(True)
        if len(calls) > 1:
            desktop.prefs._status = SettingsStore.Status.AccessError
            return
        sync()
    monkeypatch.setattr(desktop.prefs, 'sync', one_write)
    desktop.migrate_library(str(destination))
    drain(desktop)
    assert len(calls) == 1
    assert desktop.library.root == destination
    assert SettingsStore(desktop.prefs.path, 1).value('library_directory') == str(destination)
    assert not desktop.migration_locks


@pytest.mark.p1
def test_preference_and_cleanup_double_failure_releases_locks_retry_and_exit(desktop, tmp_path, monkeypatch):
    desktop._create_recording(name='preserve across failures')
    desktop._caption(Caption(1, 0, 1, 'saved', 'en'))
    desktop._save('complete')
    drain(desktop)
    source = desktop.library.root
    desktop.prefs.setValue('library_directory', str(source))
    before = snapshot(source)
    destination = tmp_path / 'new'
    rename, unlink = Directory.rename, Directory.unlink
    attempts = []
    def fail_replace(directory, name, target, **kwargs):
        if directory.path == desktop.prefs.path.parent and target == desktop.prefs.path.name:
            raise OSError('preferences write failed')
        return rename(directory, name, target, **kwargs)
    def fail_cleanup(handle, name, **kwargs):
        if handle.path == desktop.prefs.path.parent and name.startswith('.agentscribe-clean-'):
            attempts.append(True)
            raise OSError('preferences cleanup failed')
        return unlink(handle, name, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Directory, 'rename', fail_replace)
        patch.setattr(Directory, 'unlink', fail_cleanup)
        desktop.migrate_library(str(destination))
        drain(desktop)
    assert attempts and not desktop.migration_locks and not desktop.migration.busy
    assert desktop.library.root == source
    assert desktop.prefs.value('library_directory') == str(source)
    assert SettingsStore(desktop.prefs.path, 1).value('library_directory') == str(source)
    assert_preserved(source, before)
    desktop.migrate_library(str(destination))
    drain(desktop)
    assert desktop.library.root == destination and not desktop.migration_locks
    closed = []
    desktop.output.connect(lambda event: closed.append(event) if event.get('event') == 'closed' else None)
    desktop.close()
    deadline = time.monotonic() + 5
    while not closed and time.monotonic() < deadline:
        desktop.dispatcher.process(.01)
    assert closed


@pytest.mark.p2
@pytest.mark.parametrize('phase', ['publication', 'journal'])
def test_kernel_partial_write_limit_recovers_same_destination(tmp_path, phase):
    """Exercise actual partial kernel writes, beyond injected Python exceptions."""
    import subprocess
    import sys
    if os.name == 'nt':
        pytest.skip('POSIX file size limits; Windows uses the injected write-failure cases')
    program = r'''
import errno, os, resource, signal, sys
from pathlib import Path
from linguaflow.library import Library
import linguaflow.library_migration as migration
base=Path(sys.argv[1]);phase=sys.argv[2]
source=Library(base/'old');item=source.create('inbox',{},'fixture')
audio=source.directory(item['id'])/'录音.wav';audio.write_bytes(b'original audio'*5000)
before={p.relative_to(source.root):p.read_bytes() for p in source.root.rglob('*') if p.is_file()}
target=base/'new';limit=resource.getrlimit(resource.RLIMIT_FSIZE)
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
link, writer, write = os.link, migration.atomic_write, os.write
partial=[]
def no_links(*args, **kwargs):
 resource.setrlimit(resource.RLIMIT_FSIZE,(256,limit[1]))
 raise OSError(errno.ENOTSUP,'no hardlinks')
def observe(fd, data):
 try: return write(fd,data)
 except OSError:
  partial.append(os.fstat(fd).st_size)
  raise
def limited_journal(path, content, **kwargs):
 resource.setrlimit(resource.RLIMIT_FSIZE,(256,limit[1]))
 return writer(path,content,**kwargs)
if phase=='publication': os.link=no_links;os.write=observe
else: migration.atomic_write=limited_journal
try:
 try: migration.migrate_library(source,target)
 except OSError as error: assert error.errno==errno.EFBIG,repr(error)
 else: raise AssertionError('expected actual filesystem write failure')
finally:
 resource.setrlimit(resource.RLIMIT_FSIZE,limit)
 os.link=link;os.write=write;migration.atomic_write=writer
assert not list(target.iterdir()),list(target.iterdir())
assert all((source.root/p).read_bytes()==content for p,content in before.items())
if phase=='publication': assert partial and 0<partial[-1]<=256,partial
copied,verified=migration.migrate_library(source,target)
assert not migration.finish_migration(source.root,copied.root,verified)
assert (copied.directory(item['id'])/'录音.wav').read_bytes()==b'original audio'*5000
print('native partial write rollback and retry passed')
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path), phase],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'rollback and retry passed' in result.stdout


@pytest.mark.p1
def test_post_commit_lock_cleanup_error_does_not_revert_durable_preference(tmp_path, monkeypatch):
    from linguaflow.file_lock import FileLock
    prefs = SettingsStore(tmp_path / 'prefs.json', 1)
    prefs.setValue('library_directory', 'old')
    unlock = FileLock.unlock
    failures = []
    def once(lock):
        if str(lock.path) == str(prefs.path) + '.lock' and not failures:
            failures.append(True)
            raise OSError('post-commit lock cleanup failure')
        return unlock(lock)
    monkeypatch.setattr(FileLock, 'unlock', once)
    assert prefs.commit_value('library_directory', 'new')
    assert failures and prefs.value('library_directory') == 'new'
    assert SettingsStore(prefs.path, 1).value('library_directory') == 'new'
    assert prefs.status() == SettingsStore.Status.NoError
