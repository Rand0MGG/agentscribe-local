"""Owned startup failures restore a sealed package without touching user data."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from linguaflow import update_recovery as recovery

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    folder = tmp_path_factory.mktemp('recovery-native')
    library = folder / ('recovery.dll' if os.name == 'nt' else 'recovery.dylib')
    if sys.platform == 'darwin':
        command = ['clang', '-shared', '-O2', '-Wall', '-Wextra', '-o', str(library), str(ROOT / 'packaging/recovery.c')]
    elif os.name == 'nt' and shutil.which('cl'):
        command = ['cl', '/nologo', '/LD', '/O2', str(ROOT / 'packaging/recovery.c'),
                   '/Fe:' + str(library), '/Fo:' + str(folder / 'recovery.obj')]
    else:
        pytest.skip('Native recovery compiler is unavailable on this runner.')
    subprocess.run(command, check=True, cwd=folder)
    return library


def library_name(native):
    return 'recovery.dll' if os.name == 'nt' else 'recovery.dylib'


def fixture(tmp_path, native):
    installed = tmp_path / 'AgentScribe.app'
    installed.mkdir()
    (installed / 'version').write_text('new')
    directory = tmp_path / 'updates' / uuid4().hex
    directory.mkdir(parents=True)
    shutil.copy2(native, directory / library_name(native))
    backup = tmp_path / ('.AgentScribe-previous-' + directory.name)
    backup.mkdir()
    (backup / 'version').write_text('old')
    files, links = recovery.inventory(backup)
    state = dict(token=directory.name, installed=str(installed), backup=str(backup),
                 failed=str(tmp_path / ('.AgentScribe-failed-' + directory.name)), target='macos-arm64',
                 previous_version='0.7.0', old_pid=2**30, old_stamp=1, files=files, links=links,
                 status='prepared', native_sha256=recovery.checksum(native))
    recovery.write_json(directory / 'state.json', state)
    recovery.write_json(directory.parent / 'pending.json', {'token': directory.name})
    user = tmp_path / 'recordings'
    user.mkdir()
    (user / 'session').write_bytes(b'unchanged audio fixture')
    return directory, state, user


def test_native_creation_stamp_cannot_stop_unrelated_process(native):
    implementation = recovery.NativeRecovery(native)
    child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
    try:
        stamp = implementation.stamp(child.pid)
        assert stamp and stamp == implementation.stamp(child.pid)
        assert not implementation.stop(child.pid, stamp + 1)
        assert child.poll() is None
        assert implementation.stop(child.pid, stamp)
        child.wait(timeout=5)
        assert not implementation.stamp(child.pid)
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait()


def test_owned_crash_restores_old_package_and_retains_failed_candidate(tmp_path, native):
    directory, state, user = fixture(tmp_path, native)
    recovery.write_json(directory / 'startup.json', dict(pid=2**30, stamp=5, version='0.8.0'))
    assert recovery.watch(directory, startup_timeout=1, relaunch=False) == 'restored'
    assert (Path(state['installed']) / 'version').read_text() == 'old'
    assert (Path(state['failed']) / 'version').read_text() == 'new'
    assert (user / 'session').read_bytes() == b'unchanged audio fixture'
    assert not (directory.parent / 'pending.json').exists()


def test_healthy_bootstrap_preserves_new_and_backup(tmp_path, native):
    directory, state, _ = fixture(tmp_path, native)
    record = dict(pid=os.getpid(), stamp=recovery.NativeRecovery(native).stamp(os.getpid()), version='0.8.0')
    recovery.write_json(directory / 'startup.json', record)
    recovery.write_json(directory / 'healthy.json', record)
    assert recovery.watch(directory, startup_timeout=1, relaunch=False) == 'healthy'
    assert (Path(state['installed']) / 'version').read_text() == 'new'
    assert Path(state['backup']).exists()


def test_missing_ownership_does_not_replace_a_potentially_running_app(tmp_path, native):
    directory, state, _ = fixture(tmp_path, native)
    assert recovery.watch(directory, startup_timeout=0, relaunch=False) == 'manual-recovery'
    assert (Path(state['installed']) / 'version').read_text() == 'new'
    assert Path(state['backup']).exists()


@pytest.mark.parametrize('marker', ['cancelled', 'unchanged.json'])
def test_cancel_or_unchanged_old_relaunch_never_swaps(tmp_path, native, marker):
    directory, state, _ = fixture(tmp_path, native)
    (directory / marker).touch()
    assert recovery.watch(directory, startup_timeout=1, relaunch=False) == 'cancelled'
    assert not Path(state['failed']).exists()


@pytest.mark.parametrize('change', ['content', 'external-link', 'path'])
def test_corrupt_backup_or_state_refuses_restore(tmp_path, native, change):
    directory, state, user = fixture(tmp_path, native)
    recovery.write_json(directory / 'startup.json', dict(pid=2**30, stamp=5, version='0.8.0'))
    if change == 'content':
        (Path(state['backup']) / 'version').write_text('changed')
    elif change == 'external-link':
        try:
            (Path(state['backup']) / 'external').symlink_to(user, target_is_directory=True)
        except OSError:
            pytest.skip('This Windows user cannot create symlinks.')
    else:
        state['backup'] = str(user)
        recovery.write_json(directory / 'state.json', state)
    with pytest.raises(ValueError):
        recovery.watch(directory, startup_timeout=1, relaunch=False)
    assert (Path(state['installed']) / 'version').read_text() == 'new'
    assert (user / 'session').read_bytes() == b'unchanged audio fixture'


def test_failed_prepare_clears_only_its_own_pending(monkeypatch, tmp_path):
    transaction = recovery.UpdateRecovery(tmp_path, 'macos-arm64', '0.7.0')
    directory = tmp_path / uuid4().hex
    directory.mkdir()
    transaction.directory = directory
    recovery.write_json(tmp_path / 'pending.json', {'token': directory.name})
    monkeypatch.setattr(transaction, '_prepare', lambda: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        transaction.prepare()
    assert not (tmp_path / 'pending.json').exists()


def test_restored_bootstrap_feedback_is_taken_once(tmp_path, native, monkeypatch):
    import linguaflow
    from linguaflow import runtime_paths
    directory, _, _ = fixture(tmp_path, native)
    recovery.write_json(directory / 'startup.json', dict(pid=2**30, stamp=5, version='0.8.0'))
    recovery.watch(directory, startup_timeout=1, relaunch=False)
    monkeypatch.setattr(runtime_paths, 'packaged', lambda: True)
    monkeypatch.setattr(runtime_paths, 'user_data_root', lambda: tmp_path)
    monkeypatch.setattr(linguaflow, '__version__', '0.7.0')
    assert '已恢复上一版本' in recovery.take_recovery_notice()['text']
    assert recovery.take_recovery_notice() is None


@pytest.mark.parametrize('status', ['healthy', 'manual-recovery'])
def test_previous_backup_retirement_keeps_failed_evidence(tmp_path, native, status):
    directory, state, user = fixture(tmp_path, native)
    state['status'] = status
    recovery.write_json(directory / 'state.json', state)
    current = directory.parent / uuid4().hex
    current.mkdir()
    recovery.retire_older_backups(directory.parent, Path(state['installed']), current)
    assert Path(state['backup']).exists() == (status != 'healthy')
    assert (user / 'session').read_bytes() == b'unchanged audio fixture'
