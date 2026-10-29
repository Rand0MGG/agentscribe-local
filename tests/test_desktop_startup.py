"""A spawned desktop is not an acknowledged healthy startup."""
import os
import sys
from unittest.mock import Mock

import pytest

from linguaflow import desktop_startup, update_recovery


@pytest.mark.p0
@pytest.mark.parametrize('acknowledge', [False, True])
def test_launcher_confirms_only_actual_frontend_ready(tmp_path, monkeypatch, acknowledge):
    child = tmp_path / 'desktop.py'
    child.write_text('''import json, os, time
from pathlib import Path
assert 'AGENTSCRIBE_STARTUP_TICKET' not in os.environ
if ''' + repr(acknowledge) + ''':
    from linguaflow.update_recovery import write_json
    write_json(Path(os.environ['AGENTSCRIBE_DESKTOP_READY']),
        {'token': os.environ['AGENTSCRIBE_DESKTOP_READY_TOKEN'], 'parent': os.getpid()})
time.sleep(.25)
''', encoding='utf-8')
    healthy, register = Mock(), Mock()
    monkeypatch.setattr(update_recovery, 'mark_startup_healthy', healthy)
    monkeypatch.setattr(update_recovery, 'register_desktop_child', register)
    assert desktop_startup.run_desktop([sys.executable, str(child)], cwd=tmp_path,
        env={**os.environ, 'AGENTSCRIBE_STARTUP_TICKET': 'parent-only'}) == 0
    register.assert_called_once()
    assert healthy.call_count == int(acknowledge)


@pytest.mark.p0
def test_backend_ready_carries_its_actual_electron_parent(tmp_path, monkeypatch):
    import json
    ready = tmp_path / 'ready.json'
    monkeypatch.setenv('AGENTSCRIBE_DESKTOP_READY', str(ready))
    monkeypatch.setenv('AGENTSCRIBE_DESKTOP_READY_TOKEN', 'owned-token')
    desktop_startup.frontend_healthy()
    assert json.loads(ready.read_text()) == {'token': 'owned-token', 'parent': os.getppid()}
    assert 'AGENTSCRIBE_DESKTOP_READY_TOKEN' not in os.environ
