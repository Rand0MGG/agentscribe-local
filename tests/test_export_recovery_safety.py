"""R36–R38: real queued exports and locks over synthetic recordings only."""
import ctypes
import os
import subprocess
import sys
from pathlib import Path
from threading import Event

import pytest

from linguaflow import recording_export, storage_io
from linguaflow.core import Caption
from linguaflow.library_access import acquire_recording_lock
from linguaflow.storage_io import Directory
from tests.test_desktop_service import desktop as desktop
from tests.test_desktop_service import drain


def prepare(service):
    service._create_recording(name='恢复测试')
    service._caption(Caption(1, 0, 1, 'Preserved source', 'en'))
    service._caption(Caption(2, 1, 2, 'Preserved draft', 'en', final=False))
    service.autosave.stop()
    service.save_error = 'synthetic prior save failure'
    service.recording_lock = acquire_recording_lock(service.library.directory(service.item['id']))


@pytest.mark.p0
@pytest.mark.parametrize('recovery', [False, True])
def test_queued_export_rejects_replaced_parent(desktop, tmp_path, recovery):
    prepare(desktop)
    folder = tmp_path / 'original parent'
    folder.mkdir()
    release = Event()
    def wait(item, captions, state):
        assert release.wait(5)
        item['state'] = 'export'
    desktop.exporter.submit(wait, (100, 'blocker'), 0, {}, [])
    try:
        desktop.export(str(folder / 'result.txt'), format='txt', recovery=recovery)
        folder.rename(tmp_path / 'moved parent')
        folder.mkdir()
        target = folder / 'result.txt'
        target.write_bytes(b'non-owned result')
    finally:
        release.set()
        drain(desktop)
    assert target.read_bytes() == b'non-owned result'
    assert not list((tmp_path / 'moved parent').iterdir())
    assert desktop.export_errors and desktop.recovery_receipt is None
    assert desktop.dirty and desktop.recording_lock.locked


@pytest.mark.p0
@pytest.mark.parametrize('recovery', [False, True])
def test_queued_export_cannot_follow_new_mapping_into_library(desktop, tmp_path, recovery):
    prepare(desktop)
    folder = tmp_path / 'selected export folder'
    folder.mkdir()
    source = desktop.library.directory(desktop.item['id'])
    original = source / 'result.txt'
    original.write_bytes(b'original recording material')
    release = Event()
    def wait(item, captions, state):
        assert release.wait(5)
        item['state'] = 'export'
    desktop.exporter.submit(wait, (100, 'blocker'), 0, {}, [])
    try:
        desktop.export(str(folder / original.name), format='txt', recovery=recovery)
        folder.rename(tmp_path / 'moved export folder')
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(folder), str(source)],
                                    capture_output=True, timeout=5)
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            folder.symlink_to(source, target_is_directory=True)
    finally:
        release.set()
        drain(desktop)
    assert original.read_bytes() == b'original recording material'
    assert desktop.export_errors and desktop.recovery_receipt is None
    assert desktop.dirty and desktop.recording_lock.locked


@pytest.mark.p0
@pytest.mark.parametrize('recovery', [False, True])
def test_temp_replacement_before_verification_preserves_existing_export(desktop, tmp_path, monkeypatch, recovery):
    prepare(desktop)
    target = tmp_path / 'export.txt'
    target.write_bytes(b'previous export')
    sync = os.fsync
    replacements = []
    def replace_written(fd):
        sync(fd)
        temporary = next(tmp_path.glob('.agentscribe-write-*.tmp'))
        # Windows may deny renaming an open writer. Mutation before publication
        # is also exercised below after the stream has closed.
        replacements.append(temporary)
    original = Directory.stat
    def substitute(directory, name):
        if str(name).startswith('.agentscribe-write-') and replacements:
            temporary = replacements.pop()
            temporary.rename(tmp_path / 'owned-preserved.tmp')
            temporary.write_bytes(b'non-owned replacement')
        return original(directory, name)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'fsync', replace_written)
        patch.setattr(Directory, 'stat', substitute)
        desktop.export(str(target), format='txt', recovery=recovery)
        drain(desktop)
    assert target.read_bytes() == b'previous export'
    assert desktop.export_errors and desktop.recovery_receipt is None
    if os.name == 'nt':
        assert not list(tmp_path.glob('.agentscribe-write-*.tmp'))
        assert not (tmp_path / 'owned-preserved.tmp').exists()
    else:
        assert next(tmp_path.glob('.agentscribe-write-*.tmp')).read_bytes() == b'non-owned replacement'
        assert b'Preserved source' in (tmp_path / 'owned-preserved.tmp').read_bytes()


@pytest.mark.p0
@pytest.mark.parametrize('fail_publish', [False, True])
def test_export_cleanup_keeps_non_owned_replacement(tmp_path, monkeypatch, fail_publish):
    target = tmp_path / 'export.txt'
    target.write_bytes(b'previous export')
    publish = Directory.publish
    remove = storage_io.remove_owned
    replaced = []
    def fail(directory, source, destination, fd, **kwargs):
        if fail_publish:
            raise OSError('publication failed')
        return publish(directory, source, destination, fd, **kwargs)
    def race(directory, name, *args, **kwargs):
        temporary = directory.path / name
        if temporary.exists():
            temporary.rename(tmp_path / 'owned-preserved.tmp')
        temporary.write_bytes(b'non-owned replacement')
        replaced.append(temporary)
        return remove(directory, name, *args, **kwargs)
    monkeypatch.setattr(Directory, 'publish', fail)
    monkeypatch.setattr(storage_io, 'remove_owned', race)
    if fail_publish:
        with pytest.raises(OSError, match='publication failed'):
            recording_export._write_text(target, 'new export')
        assert target.read_bytes() == b'previous export'
    else:
        receipt = recording_export._write_text(target, 'new export')
        recording_export.check_export(target, receipt)
    assert replaced[0].read_bytes() == b'non-owned replacement'


@pytest.mark.p0
def test_publication_boundary_substitution_cannot_authorize_recovery_close(desktop, tmp_path, monkeypatch):
    prepare(desktop)
    target = tmp_path / 'backup.txt'
    target.write_bytes(b'previous backup')
    publish = Directory.publish
    def race(directory, source, destination, fd, **kwargs):
        if destination == target.name:
            path = directory.path / source
            path.rename(tmp_path / 'owned-preserved.tmp')
            path.write_bytes(b'foreign publication')
        return publish(directory, source, destination, fd, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Directory, 'publish', race)
        desktop.export(str(target), recovery=True)
        drain(desktop)
    assert desktop.export_errors and desktop.recovery_receipt is None
    with pytest.raises(ValueError, match='内容已变化'):
        desktop.close_recovered()
    assert desktop.dirty and desktop.recording_lock.locked
    if os.name == 'nt':
        assert target.read_bytes() == b'previous backup'
    else:
        assert b'Preserved draft' in (tmp_path / 'owned-preserved.tmp').read_bytes()


@pytest.mark.p1
@pytest.mark.parametrize('blocked', [False, True])
def test_recovery_close_unlock_failure_retains_state_and_allows_retry(desktop, tmp_path, monkeypatch, blocked):
    prepare(desktop)
    target = tmp_path / 'backup.txt'
    desktop.export(str(target), recovery=True)
    drain(desktop)
    if blocked:
        lock = desktop.recording_lock
        state = desktop.dirty, desktop.save_error, desktop.recovery_receipt
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                          ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
            kernel.CreateFileW.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.CreateFileW(str(lock.path), 0x80000000, 3, None, 3, 0x80, None)
            assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
            try:
                with pytest.raises(PermissionError):
                    desktop.close_recovered()
            finally:
                kernel.CloseHandle(handle)
        else:
            unlink = Path.unlink
            def denied(path, *args, **kwargs):
                if path == lock.path:
                    raise PermissionError('synthetic unlink denial')
                return unlink(path, *args, **kwargs)
            with monkeypatch.context() as patch:
                patch.setattr(Path, 'unlink', denied)
                with pytest.raises(PermissionError):
                    desktop.close_recovered()
        assert (desktop.dirty, desktop.save_error, desktop.recovery_receipt) == state
        assert desktop.item is not None and lock.locked and desktop._recovery_ready()
    desktop.close_recovered()
    assert desktop.item is None and desktop.recording_lock is None and not desktop.dirty
    assert 'Preserved draft' in target.read_text('utf-8-sig')


@pytest.mark.p1
@pytest.mark.parametrize('exception_type', [OSError, MemoryError])
def test_receipt_digest_failure_reports_error_and_drains_queue(desktop, tmp_path, monkeypatch, exception_type):
    prepare(desktop)
    first, second = tmp_path / 'first.txt', tmp_path / 'second.txt'
    digest = recording_export.file_digest
    def fail(directory, name):
        if name == first.name:
            raise exception_type('injected receipt read failure')
        return digest(directory, name)
    with monkeypatch.context() as patch:
        patch.setattr(recording_export, 'file_digest', fail)
        desktop.export(str(first), recovery=True)
        desktop.export(str(second), format='txt')
        assert desktop.exporter.flush(3000)
    assert first.exists() and second.exists() and not desktop.exporter.busy, desktop.export_errors
    assert desktop.export_errors and desktop.recovery_receipt is None
    assert desktop.dirty and desktop.recording_lock.locked


@pytest.mark.p1
def test_completion_listener_failure_reports_error_and_drains_queue(desktop, tmp_path, monkeypatch):
    prepare(desktop)
    errors, events = [], []
    desktop.output.connect(events.append)
    monkeypatch.setattr(sys, 'excepthook', lambda kind, value, tb: errors.append(kind))
    first, second = tmp_path / 'first.txt', tmp_path / 'second.txt'
    def fail(snapshot, state, error):
        if snapshot.item['path'] == str(first):
            raise MemoryError('listener failed')
    desktop.exporter.completed.connect(fail)
    desktop.export(str(first), recovery=True)
    desktop.export(str(second), format='txt')
    assert desktop.exporter.flush(3000)
    assert first.exists() and second.exists() and errors == [MemoryError], desktop.export_errors
    assert desktop.export_errors and desktop.recovery_receipt is None
    assert any(event.get('event') == 'notice' and event['data'].get('error') for event in events)
    assert desktop.dirty and desktop.recording_lock.locked


@pytest.mark.p0
def test_backup_receipt_rejects_identical_content_in_replaced_file(desktop, tmp_path):
    prepare(desktop)
    target = tmp_path / 'backup.txt'
    desktop.export(str(target), recovery=True)
    drain(desktop)
    content = target.read_bytes()
    target.rename(tmp_path / 'original.txt')
    target.write_bytes(content)
    with pytest.raises(ValueError, match='备份已被修改'):
        desktop.close_recovered()
    assert desktop.dirty and desktop.recording_lock.locked


@pytest.mark.p1
def test_receipt_validation_never_reads_whole_file(desktop, tmp_path, monkeypatch):
    prepare(desktop)
    target = tmp_path / 'backup.txt'
    def forbidden(*args, **kwargs):
        raise AssertionError('whole-file receipt read')
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'read_bytes', forbidden)
        desktop.export(str(target), recovery=True)
        drain(desktop)
        assert not desktop.export_errors and desktop._recovery_ready()
        desktop.close_recovered()
    assert desktop.item is None and 'Preserved draft' in target.read_text('utf-8-sig')


@pytest.mark.p0
def test_directory_replacement_after_open_cannot_redirect_write(tmp_path, monkeypatch):
    folder = tmp_path / 'selected folder'
    folder.mkdir()
    target = folder / 'backup.txt'
    original = Directory.create_temporary
    attempted = []
    def race(directory, name):
        if directory.path == folder and not attempted:
            attempted.append(True)
            folder.rename(tmp_path / 'moved folder')
            folder.mkdir()
            target.write_bytes(b'other directory content')
        return original(directory, name)
    monkeypatch.setattr(Directory, 'create_temporary', race)
    with pytest.raises(OSError):
        recording_export._write_text(target, 'owned content')
    assert attempted
    if os.name == 'nt':
        # Native held directory handle denies the move before it takes effect.
        assert not (tmp_path / 'moved folder').exists() and not target.exists()
    else:
        assert target.read_bytes() == b'other directory content'


@pytest.mark.p1
def test_save_completion_failure_retains_unsaved_state(desktop, monkeypatch):
    prepare(desktop)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda kind, value, tb: errors.append(kind))
    def fail(snapshot, state, error):
        raise MemoryError('completion observer failed')
    desktop.saver.completed.connect(fail)
    desktop._save('complete')
    assert desktop.saver.flush(3000)
    assert desktop.dirty and desktop.save_error and desktop.recording_lock.locked
    assert errors == [MemoryError]
    desktop.saver.completed.disconnect(fail)
    desktop.retry_save()
    drain(desktop)
    assert not desktop.dirty and not desktop.save_error and desktop.recording_lock is None
