"""A restored process is not enough: its actual Electron frontend must be ready."""
import json
from unittest.mock import Mock

import psutil
import pytest

from scripts import probe_macos_update as probe


@pytest.mark.p0
@pytest.mark.parametrize('scenario,expected', [
    ('ready', True), ('no_parent', False), ('unrelated_child', False),
    ('no_receipt', False), ('partial_receipt', False), ('wrong_token', False),
    ('wrong_parent', False), ('exited', False),
])
def test_restored_desktop_requires_owned_frontend_receipt(tmp_path, monkeypatch, scenario, expected):
    executable = tmp_path / 'AgentScribe.app/Contents/MacOS/AgentScribe'
    electron = executable.parent.parent / 'Resources/desktop/runtime/Electron.app/Contents/MacOS/Electron'
    receipt = tmp_path / 'ready.json'
    value = {'token': 'owned-token', 'parent': 42}
    if scenario == 'wrong_token':
        value['token'] = 'another-token'
    if scenario == 'wrong_parent':
        value['parent'] = 99
    if scenario != 'no_receipt':
        receipt.write_text('{' if scenario == 'partial_receipt' else json.dumps(value))
    child = Mock(pid=42)
    child.exe.return_value = '/unrelated/Electron' if scenario == 'unrelated_child' else str(electron)
    child.environ.return_value = {'AGENTSCRIBE_DESKTOP_READY': str(receipt),
                                  'AGENTSCRIBE_DESKTOP_READY_TOKEN': 'owned-token'}
    parent = Mock()
    parent.children.return_value = [child]
    if scenario == 'exited':
        parent.children.side_effect = psutil.NoSuchProcess(21)
    monkeypatch.setattr(psutil, 'Process', lambda pid: parent)
    monkeypatch.setattr(probe, 'owned_processes', lambda path: [] if scenario == 'no_parent' else [21])
    assert probe.restored_desktop_ready(executable) is expected


@pytest.mark.p0
@pytest.mark.parametrize('lingering', [False, True])
def test_cleanup_stops_host_and_waits_for_desktop_close(monkeypatch, lingering):
    host, desktop, backend = Mock(pid=21), Mock(pid=42), Mock(pid=63)
    host.parents.return_value = []
    backend.parents.return_value = [desktop, host]
    host.children.return_value = [desktop, backend]
    monkeypatch.setattr(probe, 'owned_processes', lambda path: [21, 63])
    monkeypatch.setattr(psutil, 'Process', lambda pid: {21: host, 63: backend}[pid])
    wait = Mock(return_value=([], [desktop] if lingering else []))
    monkeypatch.setattr(psutil, 'wait_procs', wait)
    native = Mock()
    native.stamp.return_value = 123
    native.stop.return_value = True
    if lingering:
        with pytest.raises(AssertionError, match='Owned desktop processes did not exit'):
            probe.stop_owned('owned-app', native)
    else:
        probe.stop_owned('owned-app', native)
    native.stop.assert_called_once_with(21, 123)
    assert {p.pid for p in wait.call_args.args[0]} == {21, 42, 63}
