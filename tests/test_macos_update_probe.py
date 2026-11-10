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
