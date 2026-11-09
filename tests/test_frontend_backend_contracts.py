"""Official desktop failure/ownership contracts, without a legacy GUI runtime."""
import sys
from types import SimpleNamespace

import pytest

from linguaflow.recording_state import RecordingState
from tests.test_desktop_service import desktop as desktop
from tests.test_desktop_service import drain


@pytest.mark.p2
def test_shared_backend_imports_without_a_widget_or_electron_frontend():
    import subprocess
    result = subprocess.run([sys.executable, '-c', '''
import sys
from linguaflow.recording_workflow import RecordingWorkflow
from linguaflow.library_workflow import LibraryWorkflow
from linguaflow.preparation_workflow import PreparationWorkflow
from linguaflow.application_lifecycle import ShutdownWorkflow
recording = RecordingWorkflow()
preparation = PreparationWorkflow()
assert not any(n.startswith(('PySide6', 'shiboken6')) for n in sys.modules)
'''], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('save_fails', [False, True])
@pytest.mark.p1
def test_start_failure_is_durable_and_retains_lock_until_saved(desktop, monkeypatch, save_fails):
    import linguaflow.wlk_session as module
    desktop._create_recording(name='shared contract')
    desktop.device = ('audit', False)
    desktop.devices = [dict(id='audit', loopback=False)]
    monkeypatch.setattr(desktop, '_audio_allowed', lambda: None)
    def fail(*args, **kwargs):
        raise RuntimeError('injected constructor failure')
    monkeypatch.setattr(module, 'Session', fail)
    original = desktop.library.save
    if save_fails:
        def disk_failure(*args):
            raise OSError('injected write failure')
        monkeypatch.setattr(desktop.library, 'save', disk_failure)
    with pytest.raises(RuntimeError, match='constructor failure'):
        desktop.start()
    drain(desktop)
    data = desktop.recording.data
    assert data.state is RecordingState.IDLE and data.session is None
    assert 'injected constructor failure' in data.failure
    if save_fails:
        assert data.dirty and data.save_error and data.lock is not None
        assert data.save_target == 'incomplete'
        monkeypatch.setattr(desktop.library, 'save', original)
        assert desktop.recording.flush()
        desktop.recording.release_lock()
    assert data.lock is None and not data.dirty and not data.save_error
    assert desktop.library.load(data.item)[0]['session']['state'] == 'incomplete'


@pytest.mark.p1
def test_switch_gate_observes_busy_and_idle_without_a_new_view(desktop):
    desktop.knowledge = SimpleNamespace(connected=True)
    receive = desktop._knowledge_event
    receive({'type': 'view', 'busy': False})
    receive({'type': 'status', 'busy': True, 'operation': 'import'})
    assert '课程' in desktop.activity_snapshot().switch_reason()
    receive({'type': 'idle', 'busy': False})
    assert not desktop.activity_snapshot().switch_reason()
    receive({'type': 'view', 'busy': True})
    receive({'type': 'disconnected', 'busy': False})
    assert not desktop.activity_snapshot().switch_reason()
    desktop.knowledge = None
