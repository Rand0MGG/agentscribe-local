"""Missing translation assets must not block recognition or lose user intent."""
import pytest
from ui_support import run_ui


@pytest.mark.p1
def test_translation_recovery_preserves_intent_for_next_recording(tmp_path):
    run_ui(r''' 
w.check_model_assets = lambda: None
w.startup_model_guidance_pending = False
w.device.addItem('Fixture', ('fixture', False))
w.device.setCurrentIndex(0)
captured = []
w.launch_session = lambda settings: captured.append(settings)
w.model_action = 'start'
w.on_model_assets_checked(w.asset_check_generation, ['翻译模型：fixture'])
assert not w.translate.isEnabled() and w.translate.isChecked()
assert not w.language_popup.translation_switch.isEnabled()
assert captured and captured[-1].translate is False
assert w.caption_translation is False
assert '仅识别' in w.notifications.notices['translation'].text
# Finish the simulated session; the real worker/device is never started.
from linguaflow.recording_state import RecordingState
w.persist_session('complete')
w.release_recording_lock()
w.set_recording_state(RecordingState.IDLE)
w.on_model_assets_checked(w.asset_check_generation, [])
assert w.translate.isEnabled() and w.translate.isChecked()
assert w.language_popup.translation_switch.isEnabled()
w.start(models_checked=True)
assert captured[-1].translate and w.caption_translation
w.persist_session('complete')
w.release_recording_lock()
w.set_recording_state(RecordingState.IDLE)
# An explicit opt-out stays off after model preparation/rechecks.
w.translate.setChecked(False)
w.on_model_assets_checked(w.asset_check_generation, [])
w.start(models_checked=True)
assert not captured[-1].translate and not w.translate.isChecked()
w.close()
''', tmp_path)
