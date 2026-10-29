"""The same failure/ownership contracts through both real frontend adapters."""
import pytest

from tests.ui_support import run_ui_process

pytestmark = pytest.mark.p1


def test_shared_backend_imports_without_a_widget_or_electron_frontend():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c', '''
import sys
from PySide6.QtCore import QCoreApplication
from linguaflow.recording_workflow import RecordingWorkflow
from linguaflow.library_workflow import LibraryWorkflow
from linguaflow.preparation_workflow import PreparationWorkflow
from linguaflow.application_lifecycle import ShutdownWorkflow
from linguaflow.session_settings import session_settings
app = QCoreApplication([])
recording = RecordingWorkflow()
preparation = PreparationWorkflow()
assert not any(name in sys.modules for name in (
    'PySide6.QtWidgets', 'linguaflow.app', 'linguaflow.management', 'linguaflow.qt_controls'))
'''], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


ADAPTER = '''
import os
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.core import Settings
from linguaflow.recording_state import RecordingState
from linguaflow.recording_workflow import RecordingWorkflow
from linguaflow.library_workflow import LibraryWorkflow
from linguaflow.application_lifecycle import ShutdownWorkflow
from linguaflow.preparation_workflow import PreparationWorkflow
app = QApplication([])
root = Path(os.environ['AGENTSCRIBE_LIBRARY'])
prefs = QSettings(str(root/'prefs.ini'), QSettings.Format.IniFormat)
if ADAPTER == 'qt':
    import linguaflow.app as module
    w = module.Window(discover=False, prefs=prefs, no_audio=True)
    assert w.new_recording(name='shared contract', check_models=False)
    w.no_audio = False
    w.quick_device.addItem('isolated', ('audit', False))
    w.quick_device.setCurrentIndex(w.quick_device.count()-1)
    w.settings_binding.session_settings = lambda _: Settings('audit', translate=False)
    w.model_manager.start_block_reason = lambda: None
    preparations = w.model_manager.preparation_workflow
else:
    from linguaflow.desktop_service import DesktopService
    import linguaflow.wlk_session as module
    w = DesktopService(library_root=root/'library', prefs=prefs, no_audio=True)
    w._create_recording(name='shared contract')
    w.device = ('audit', False)
    w.devices = [{'id': 'audit', 'loopback': False}]
    w._audio_allowed = lambda: None
    preparations = w.preparation_workflow
assert type(w.recording) is RecordingWorkflow
assert type(w.library_workflow) is LibraryWorkflow
assert type(w.shutdown) is ShutdownWorkflow
assert type(preparations) is PreparationWorkflow
def fail(*args, **kwargs):
    raise RuntimeError('injected constructor failure')
module.Session = fail
'''


@pytest.mark.parametrize('adapter', ['qt', 'electron'])
@pytest.mark.parametrize('save_fails', [False, True])
def test_start_failure_is_durable_and_retains_lock_until_saved(tmp_path, adapter, save_fails):
    run_ui_process(f'ADAPTER = {adapter!r}\nSAVE_FAILS = {save_fails!r}\n' + ADAPTER + '''
original = w.library.save
if SAVE_FAILS:
    def disk_failure(*args): raise OSError('injected write failure')
    w.library.save = disk_failure
try:
    w.start()
except RuntimeError as exc:
    assert ADAPTER == 'electron' and 'injected constructor failure' in str(exc)
data = w.recording.data
assert data.state is RecordingState.IDLE and data.session is None
assert 'injected constructor failure' in data.failure
if SAVE_FAILS:
    assert data.dirty and data.save_error and data.lock is not None
    assert data.save_target == 'incomplete'
    w.library.save = original
    assert w.recording.flush()
    w.recording.release_lock()
assert data.lock is None and not data.dirty and not data.save_error
assert w.library.load(data.item)[0]['session']['state'] == 'incomplete'
if ADAPTER == 'qt':
    w.no_audio = True
else:
    w.close()
    from tests.ui_support import wait_until
    wait_until(lambda: not w.shutdown.timer.isActive())
    w.clock.stop()
''', tmp_path)


@pytest.mark.parametrize('adapter', ['qt', 'electron'])
def test_switch_gate_observes_busy_and_idle_without_a_new_view(tmp_path, adapter):
    run_ui_process(f'ADAPTER = {adapter!r}\n' + ADAPTER + '''
if ADAPTER == 'qt':
    receive = lambda event: w.knowledge_client._deliver(w.knowledge_client.epoch, event)
else:
    receive = w._knowledge_event
receive({'type': 'view', 'busy': False})
receive({'type': 'status', 'busy': True, 'operation': 'import'})
assert '课程' in w.activity_snapshot().switch_reason()
receive({'type': 'idle', 'busy': False})
assert not w.activity_snapshot().switch_reason()
receive({'type': 'view', 'busy': True})
receive({'type': 'disconnected', 'busy': False})
assert not w.activity_snapshot().switch_reason()
if ADAPTER == 'qt':
    w.no_audio = True
else:
    w.clock.stop()
''', tmp_path)
