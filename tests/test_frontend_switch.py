"""Handoffs preserve data and never run two recording owners concurrently."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest
from PySide6.QtCore import QSettings

from linguaflow import frontend_switch as switch


@pytest.mark.p1
def test_prepare_preflights_before_writing_and_carries_isolated_context(tmp_path, monkeypatch):
    monkeypatch.setattr(switch, 'resource_root', lambda: tmp_path)
    prefs = QSettings(str(tmp_path / '中文设置.ini'), QSettings.Format.IniFormat)
    library = SimpleNamespace(root=tmp_path / '中文 录音')
    with pytest.raises(ValueError, match='Electron'):
        switch.prepare('electron', library=library, prefs=prefs)
    monkeypatch.setattr(switch, 'command_for', lambda target: [sys.executable])
    monkeypatch.setattr(switch.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    with pytest.raises(ValueError, match='归属'):
        switch.prepare('qt', library=library, prefs=prefs, owner_pid=-1)
    path = switch.prepare('electron', library=library, prefs=prefs, recording='recording-id',
                          geometry=dict(x=10, y=20, width=900, height=650), no_audio=True)
    value = json.loads(path.read_text())
    assert value['recording'] == 'recording-id' and value['no_audio']
    assert value['preferences'] == prefs.fileName() and value['preferences_format'] == 1
    assert value['library'] == str(library.root)
    assert value['owners'] == [{'pid': os.getpid(), 'created': psutil.Process().create_time()}]
    monkeypatch.setenv(switch.CONTEXT_ENV, str(path))
    assert switch.context()['geometry']['width'] == 900
    switch.ready('electron', prefs)
    assert path.with_name('ready-electron').exists()
    assert prefs.value('desktop_frontend') == 'electron'


@pytest.mark.p1
def test_handoff_waits_for_owner_and_restores_original_on_startup_failure(tmp_path, monkeypatch):
    # The only subprocesses owned by this test are short, harmless Python fixtures.
    owner = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.25)'])
    context = tmp_path / 'context.json'
    context.write_text(json.dumps(dict(target='electron', previous='qt', owners=[
        dict(pid=owner.pid, created=psutil.Process(owner.pid).create_time())])))
    marker = tmp_path / 'sequence.json'
    source = '''
import json, os, sys
from pathlib import Path
import psutil
pid, output, frontend = int(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
assert not psutil.pid_exists(pid), 'new UI started before the old owner exited'
if frontend == 'electron':
    output.write_text(json.dumps([frontend]))
    raise SystemExit(7)
assert '退出码 7' in os.environ['AGENTSCRIBE_FRONTEND_RECOVERY']
assert 'AGENTSCRIBE_DESKTOP_LIBRARY' not in os.environ
output.write_text(json.dumps(json.loads(output.read_text()) + [frontend]))
Path(os.environ['AGENTSCRIBE_FRONTEND_CONTEXT']).with_name('ready-qt').write_text('ready')
'''
    monkeypatch.setattr(switch, 'command_for', lambda target: [sys.executable, '-c', source, str(owner.pid), str(marker), target])
    monkeypatch.setenv('AGENTSCRIBE_DESKTOP_LIBRARY', 'stale-library')
    try:
        assert switch.handoff(context) == 0
        assert json.loads(marker.read_text()) == ['electron', 'qt']
    finally:
        owner.wait(timeout=3)


@pytest.mark.p1
def test_qt_frontend_button_guards_and_accepted_close(tmp_path):
    from ui_support import run_ui_process
    run_ui_process('''
import json, os
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.recording_state import RecordingState
from scripts.probe_package import close_window
app = QApplication([])
root = Path(os.environ['AGENTSCRIBE_LIBRARY'])
w = Window(discover=False, no_audio=True, library_root=root/'library',
           prefs=QSettings(str(root/'prefs.ini'), QSettings.Format.IniFormat))
w.show(); app.processEvents()
assert w.new_recording(check_models=False)
w.pending_recording_name = '切换草稿 · 中文'
w.workspace_title.setText(w.pending_recording_name)
launched = []
with patch('linguaflow.frontend_switch.command_for', return_value=[__import__('sys').executable]), patch('linguaflow.frontend_switch.launch', side_effect=launched.append):
    w.recording_state = RecordingState.LISTENING
    w.frontend_button.click()
    assert w.isVisible() and not launched and not w.frontend_handoff
    w.recording_state = RecordingState.IDLE
    w.session_dirty = True
    w.frontend_button.click()
    assert w.isVisible() and not launched
    w.session_dirty = False
    w.frontend_button.click()
    close_window(w, app)
assert len(launched) == 1
saved = json.loads(launched[0].read_text())
assert saved['draft']['name'] == '切换草稿 · 中文'
assert saved['recording'] is None and saved['no_audio']
assert not list((root/'library').rglob('session.json'))
''', tmp_path)


@pytest.mark.p1
@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_packaged_qt_switch_uses_native_launcher_identity(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(switch, 'packaged', lambda: True)
    monkeypatch.setattr(switch, 'resource_root', lambda: tmp_path / 'Resources')
    monkeypatch.setattr(switch.sys, 'platform', platform)
    executable = tmp_path / ('MacOS/AgentScribe' if platform == 'darwin' else 'Resources/AgentScribe.exe')
    executable.parent.mkdir(parents=True)
    executable.touch()
    assert switch.command_for('qt') == [str(executable), '--frontend', 'qt']
