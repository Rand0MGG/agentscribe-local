"""A spawned desktop is not an acknowledged healthy startup."""
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from linguaflow import desktop_startup, update_recovery


@pytest.mark.p0
@pytest.mark.parametrize('acknowledge,authenticated', [(False, True), (True, True), (True, False)])
def test_launcher_confirms_only_actual_frontend_ready(tmp_path, monkeypatch, acknowledge, authenticated):
    child = tmp_path / 'desktop.py'
    child.write_text('''import json, os, socket, time
from pathlib import Path
assert 'AGENTSCRIBE_STARTUP_TICKET' not in os.environ
port, token = os.environ['AGENTSCRIBE_DESKTOP_LIFETIME'].split(':')
channel = socket.create_connection(('127.0.0.1', int(port)))
channel.sendall(((token if ''' + repr(authenticated) + ''' else 'invalid') + '\\n').encode('ascii'))
if ''' + repr(acknowledge) + ''':
    from linguaflow.update_recovery import write_json
    write_json(Path(os.environ['AGENTSCRIBE_DESKTOP_READY']),
        {'token': os.environ['AGENTSCRIBE_DESKTOP_READY_TOKEN'], 'parent': os.getpid()})
time.sleep(.25)
''', encoding='utf-8')
    healthy, register = Mock(), Mock()
    monkeypatch.setattr(update_recovery, 'mark_startup_healthy', healthy)
    monkeypatch.setattr(update_recovery, 'register_desktop_child', register)
    # Match the direct native Electron child, without Windows venv's redirector.
    assert desktop_startup.run_desktop([sys._base_executable, str(child)], cwd=tmp_path,
        env={**os.environ, 'AGENTSCRIBE_STARTUP_TICKET': 'parent-only'}) == 0
    register.assert_called_once()
    assert healthy.call_count == int(acknowledge and authenticated)


@pytest.mark.p0
def test_backend_ready_carries_its_actual_electron_parent(tmp_path, monkeypatch):
    import json
    ready = tmp_path / 'ready.json'
    monkeypatch.setenv('AGENTSCRIBE_DESKTOP_READY', str(ready))
    monkeypatch.setenv('AGENTSCRIBE_DESKTOP_READY_TOKEN', 'owned-token')
    desktop_startup.frontend_healthy()
    assert json.loads(ready.read_text()) == {'token': 'owned-token', 'parent': os.getppid()}
    assert 'AGENTSCRIBE_DESKTOP_READY_TOKEN' not in os.environ


@pytest.mark.p1
def test_actual_desktop_stays_open_and_closes_after_launcher_dies(tmp_path):
    import psutil

    from linguaflow.frontend_switch import command_for
    from linguaflow.process_platform import stop_tree

    try:
        command_for('electron')
    except ValueError as exc:
        pytest.skip(str(exc))
    root = Path(__file__).resolve().parents[1]
    healthy = tmp_path / 'healthy'
    code = '''
import os, sys
from pathlib import Path
from linguaflow import desktop_launcher, update_recovery
marker = Path(sys.argv[1])
update_recovery.mark_startup_healthy = lambda: marker.write_text(str(os.getpid()))
sys.argv = ['linguaflow', '--no-audio']
raise SystemExit(desktop_launcher.main())
'''
    # The real launcher, Electron main, renderer and backend perform the ready
    # handshake. Only its update receipt is observed; no user paths or devices.
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8',
        'AGENTSCRIBE_LOG_DIR': str(tmp_path / 'logs'),
        'AGENTSCRIBE_DESKTOP_PROFILE': str(tmp_path / 'profile'),
        'AGENTSCRIBE_DESKTOP_LIBRARY': str(tmp_path / 'library'),
        'AGENTSCRIBE_DESKTOP_PREFERENCES': str(tmp_path / 'prefs.ini')}
    owned = []
    with (tmp_path / 'launcher.log').open('w', encoding='utf-8') as output:
        process = subprocess.Popen([sys.executable, '-c', code, str(healthy)], cwd=root, env=env,
                                   stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while not healthy.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            assert healthy.exists(), (tmp_path / 'launcher.log').read_text(encoding='utf-8')
            assert process.poll() is None, 'Acknowledged desktop exited while its launcher was alive'
            owned = [(p.pid, p.create_time()) for p in psutil.Process(process.pid).children(recursive=True)]
            assert owned, 'No owned Electron/backend processes'
            # Windows venv python.exe may be a redirector. Stop the actual
            # Python owner of the connection, whose identity the receipt saved.
            owner = psutil.Process(int(healthy.read_text()))
            assert owner.pid in {process.pid, *(pid for pid, _ in owned)}
            owner.terminate()  # Only this newly created, isolated test launcher.
            process.wait(timeout=5)
            deadline = time.monotonic() + 15
            while True:
                alive = []
                for pid, created in owned:
                    try:
                        child = psutil.Process(pid)
                        if child.create_time() == created and child.status() != psutil.STATUS_ZOMBIE:
                            alive.append(pid)
                    except psutil.NoSuchProcess:
                        pass
                if not alive:
                    break
                assert time.monotonic() < deadline, f'Owned desktop processes survived launcher exit: {alive}'
                time.sleep(.05)
        finally:
            if process.poll() is None:
                stop_tree(process, force=True)
                process.wait(timeout=5)
            for pid, created in owned:
                try:
                    child = psutil.Process(pid)
                    if child.create_time() == created:
                        child.kill()
                        child.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
