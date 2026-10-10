"""Responsive presentation and visible audio selection, without native audio."""
from test_beta_features import run_ui


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
startup.start_problem = lambda settings: captured.append(settings) or ('诊断', '测试快照')
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
module.QMessageBox.warning = lambda *args: messages.append(args[1:])
w.refresh_devices()
assert w.device.currentIndex() == w.quick_device.currentIndex() == -1
assert read_audio_device(w.prefs) == ('mic', False)
assert messages and messages[-1][0] == '音频来源不可用'
w.close()
''', tmp_path)


def test_playback_controls_and_duration_replace_recording_actions(tmp_path):
    run_ui(r'''
from types import SimpleNamespace
from linguaflow.recording_state import RecordingState
w.show()
w.playback.setProperty('available', True)
w.playback_duration(3723000)
w.playback_position(65000)
w.update_transport()
app.processEvents()
assert w.transport.currentWidget() is w.playback
assert w.play_time.text() == '01:05 / 1:02:03'
assert w.start_button.isHidden() and w.quick_device.isHidden()
assert w.quick_language.isHidden() and w.refresh_source.isHidden()
assert w.play_button.text() == '' and not w.play_button.icon().isNull()
w.player = SimpleNamespace(playbackState=lambda: SimpleNamespace(name='PlayingState'))
w.update_playback_button()
assert w.play_button.accessibleName() == '暂停播放'
w.player = None
w.update_playback_button()
assert w.play_button.accessibleName() == '播放录音'
w.release_playback()
app.processEvents()
assert w.play_time.text() == '00:00 / 00:00'
assert not w.start_button.isHidden() and not w.quick_device.isHidden()
w.set_recording_state(RecordingState.LISTENING)
assert w.transport.currentWidget() is w.live_transport and not w.meter.isHidden()
w.on_stage('音频', '输入持续为零，请检查来源 / 静音')
assert '没有收到声音' in w.empty.text()
w.on_stage('音频', '已收到声音 · 连续采集')
assert w.empty.text() == '正在聆听…'
w.status.setText('删除成功')
w.update_activity()
assert w.status.isHidden()
w.on_failure('录音失败：测试错误')
assert not w.status.isHidden() and '测试错误' in w.status.text()
w.set_recording_state(RecordingState.IDLE)
w.current_item = None
w.close()
''', tmp_path)


def test_narrow_settings_and_overlay_sliders_remain_reachable(tmp_path):
    run_ui(r'''
from PySide6.QtWidgets import QLabel, QSlider
from PySide6.QtTest import QTest
w.show()
assert w.minimumSize().width() == 640 and w.minimumSize().height() == 480
assert not any('本地工作空间' in label.text() for label in w.findChildren(QLabel))
assert not w.deleted_button.icon().isNull()
for width, height in ((640,480), (900,650), (700,960)):
    w.resize(width,height)
    for theme in (0,1):
        w.appearance.setCurrentIndex(theme)
        for category, tab in (('字幕与延迟',2),('运行环境',3)):
            w.open_settings(category)
            w.model_manager.advanced_toggle.setChecked(True)
            app.processEvents()
            scroll = w.model_manager.tabs.widget(tab)
            assert scroll.horizontalScrollBar().maximum() == 0
            page = scroll.widget().layout().itemAt(0).widget()
            assert page.width() <= scroll.viewport().width()
            controls = [child for child in page.findChildren(module.QPushButton) if child.isVisibleTo(page)]
            for child in controls:
                scroll.ensureWidgetVisible(child)
                app.processEvents()
                rect = child.rect().translated(child.mapTo(scroll.viewport(), child.rect().topLeft()))
                assert scroll.viewport().rect().intersects(rect), (category,child.text(),rect)
    w.leave_settings()
    app.processEvents()
    assert w.quick_language.width() > 80
    assert w.control_island.geometry().right() < w.scroll.viewport().width()
    assert w.control_island.geometry().bottom() < w.scroll.viewport().height()
    assert w.control_island.compact == (w.control_island.width() < 500)
assert isinstance(w.overlay.font_size, QSlider)
assert isinstance(w.overlay.background_opacity, QSlider)
assert not any('拖动移动' in label.text() for label in w.overlay.findChildren(QLabel))
w.overlay.show()
w.overlay.set_controls_visible(True)
app.processEvents()
slider = w.overlay.font_size
old = slider.value()
point = slider.rect().center()
QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=point)
QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=point)
assert slider.value() != old
w.overlay.background_opacity.setValue(37)
assert w.overlay.backdrop.opacity == 37
assert w.overlay.opacity_value.text() == '37%'
assert w.overlay.font_value.text() == str(slider.value())
w.overlay.close()
w.close()
''', tmp_path)
