"""Responsive presentation and visible audio selection, without native audio."""
from ui_support import run_ui


def test_device_refresh_is_atomic_and_start_uses_visible_source(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QSignalBlocker
from linguaflow.audio import Device
from linguaflow.preferences import read_audio_device
import linguaflow.inference_startup as startup
devices = [Device('speaker', '系统声音 · 扬声器', True), Device('mic', '输入 · 麦克风', False)]
module.list_devices = lambda: devices
w.refresh_devices()
w.quick_device.setCurrentIndex(1)
assert read_audio_device(w.prefs) == ('mic', False)
changes = []
w.device.currentIndexChanged.connect(lambda *_: changes.append(w.device.currentData()))
w.refresh_devices()
assert changes == [], changes
assert w.quick_device.currentData() == w.device.currentData() == ('mic', False)
assert read_audio_device(w.prefs) == ('mic', False)
devices.reverse()
w.refresh_devices()
assert w.quick_device.currentData() == w.device.currentData() == ('mic', False)
assert read_audio_device(w.prefs) == ('mic', False)
# Even a hidden view desynchronised by a model reset cannot select a different
# source for the start action. Inspect the snapshot before any model/process.
with QSignalBlocker(w.device):
    w.device.setCurrentIndex(1)
assert w.quick_device.currentData() == ('mic', False)
captured = []
def capture_settings(settings):
    captured.append(settings)
    raise RuntimeError('测试快照，不启动测试之外的采集')
w.launch_session = capture_settings
module.QMessageBox.warning = lambda *args: None
w.start(models_checked=True)
assert len(captured) == 1
assert (captured[0].device_id, captured[0].loopback) == ('mic', False)
# A disconnected selected device must remain unselected, without silently
# switching to the first speaker. The user gets an explicit prompt.
with QSignalBlocker(w.device):
    w.device.setCurrentIndex(0)
devices[:] = [Device('speaker', '系统声音 · 扬声器', True)]
messages = []
w.show_warning = lambda title, message: messages.append((title, message))
w.refresh_devices()
assert w.device.currentIndex() == w.quick_device.currentIndex() == -1
assert read_audio_device(w.prefs) == ('mic', False)
assert messages and messages[-1][0] == '音频来源不可用'
w.close()
''', tmp_path)


def test_recording_starts_without_asset_scan_and_loading_is_distinct_from_capture(tmp_path):
    run_ui(r'''from threading import Event
from PySide6.QtCore import QObject
import linguaflow.inference_startup as startup
startup.start_problem=lambda settings:None
w.device.addItem('fixture',('fixture',False));w.translate.setChecked(False)
def forbidden(*args):raise AssertionError('start waited for asynchronous model scan')
w.check_models_for_action=forbidden
class Recording(QObject):
    def __init__(self,settings):
        super().__init__(w);self.settings=settings;self.model_ready=Event();self.recorded_seconds=2
    def pause(self):return True
    def resume(self):return True
    def stop(self):w.on_finished()
def launch(settings):w.session=Recording(settings)
w.launch_session=launch
w.start()
assert w.session is not None
assert w.recording_state is module.RecordingState.STARTING
assert '连接音频来源' in w.empty.text()
w.on_source_changed(0)
assert w.recording_state is module.RecordingState.LISTENING
assert '已开始录音，正在加载识别模型' in w.empty.text()
assert w.pause_button.isEnabled() and w.capture_time.text()=='00:00:02'
assert '已开始录音' in w.notifications.notices['session'].text
w.toggle_pause();w.on_paused(True)
w.toggle_pause();w.on_paused(False)
assert '正在加载识别模型' in w.empty.text()
w.toggle_pause();w.on_paused(True)
w.session.model_ready.set();w.on_ready()
assert w.recording_state is module.RecordingState.PAUSED
assert w.empty.text()=='已暂停收音'
w.toggle_pause();w.on_paused(False)
w.on_stage('识别','正在追赶识别 · 延后 12.0s')
assert '追赶识别' in w.state_caption.text()
w.on_stage('识别','实时识别 · 待确认 1.0s')
assert '实时识别' in w.state_caption.text()
w.stop();wait(lambda:w.session is None)
# Conversely, a warm model may be ready before the first captured block.
w.start()
w.session.model_ready.set();w.on_ready()
assert w.recording_state is module.RecordingState.STARTING
assert '连接音频来源' in w.empty.text() and '已开始录音' not in w.empty.text()
w.on_source_changed(0)
assert w.recording_state is module.RecordingState.LISTENING
assert '处理已录音频' in w.empty.text()
w.stop();wait(lambda:w.session is None)
w.close()
''',tmp_path)
