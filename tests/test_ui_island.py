"""Compact island behaviour, real selection and content contours, without audio."""
from test_beta_features import run_ui


def test_long_device_name_preserves_identity_and_refresh_access(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QPoint
module.Window.start_background_check = lambda *args, **kwargs: None
w.reduce_motion.setChecked(True)
w.device.addItem('系统音频 · 扬声器', ('speaker', True))
w.show()
settle_geometry(w, w.control_island)
assert w.current_item is None and w.control_island.isVisibleTo(w)
assert w.transport.isHidden() and w.control_island.height() <= 76
assert 200 <= w.control_island.width() <= 240
before = w.control_island.geometry()
long_name = '系统音频 · 扬声器（Realtek High Definition Audio，USB-C 扩展坞，多显示器连接设备）' * 3
w.device.setItemText(0, long_name)
settle_geometry(w.control_island)
assert w.control_island.geometry() == before
assert w.quick_device.currentText() == long_name
assert w.quick_device.currentData() == ('speaker', True)
assert long_name in w.quick_device.toolTip()
w.quick_device.showPopup()
popup = w.quick_device.view().window()
wait(popup.isVisible)
settle_geometry(popup)
assert popup.geometry().width() <= 520
assert popup.screen().availableGeometry().contains(popup.geometry())
assert w.quick_device.view().sizeHintForRow(0) > w.quick_device.fontMetrics().height() * 2
assert w.refresh_source.isVisibleTo(popup)
assert popup.rect().contains(w.refresh_source.mapTo(popup, QPoint(0, 0)))
refreshed = []
w.refresh_devices = lambda: refreshed.append(True)
w.refresh_source.click()
wait(lambda: not popup.isVisible())
assert refreshed == [True] and w.quick_device.currentData() == ('speaker', True)
w.close()
''', tmp_path)


def test_recording_clock_reads_capture_length_and_survives_pause_and_status_updates(tmp_path):
    run_ui(r'''
from types import SimpleNamespace
from linguaflow.recording_state import RecordingState
w.show()
w.set_recording_state(RecordingState.STARTING)
w.session = SimpleNamespace(recorded_seconds=754.25)
w.set_recording_state(RecordingState.LISTENING)
w.on_status('识别正在处理，翻译模型加载中')
w.update_activity()
assert w.capture_time.text() == '00:12:34'
w.set_recording_state(RecordingState.PAUSED)
w.on_status('暂停后已有内容继续处理')
w.update_activity()
assert w.capture_time.text() == '00:12:34'
assert w.pause_button.accessibleName() == '继续录音'
assert w.volume_caption.text() == '已暂停' and w.meter.value() == 0
w.session.recorded_seconds += 3600
w.set_recording_state(RecordingState.LISTENING)
w.update_activity()
assert w.capture_time.text() == '01:12:34'
w.session = None
w.set_recording_state(RecordingState.IDLE)
assert w.transport.isHidden() and w.start_button.isVisibleTo(w)
w.close()
''', tmp_path)


def test_window_reopens_with_valid_native_handle_and_bounded_controls(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QWindow
module.Window.start_background_check = lambda *args, **kwargs: None
for _ in range(3):
    w.show()
    settle_geometry(w, w.control_island)
    assert isinstance(w.windowHandle(), QWindow)
    assert w.control_island.width() <= 560
    close_window(w, app)
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    w = window()
w.close()
''', tmp_path)


def test_empty_device_picker_keeps_refresh_reachable_by_mouse(tmp_path):
    run_ui(r'''
from PySide6.QtTest import QTest
module.Window.start_background_check = lambda *args, **kwargs: None
w.show()
settle_geometry(w, w.control_island)
w.device.clear()
assert w.quick_device.count() == 0
refreshed = []
w.refresh_devices = lambda: refreshed.append(True)
QTest.mouseClick(w.quick_device, Qt.MouseButton.LeftButton)
popup = w.quick_device.view().window()
wait(popup.isVisible)
assert w.refresh_source.isVisibleTo(popup)
w.refresh_source.click()
wait(lambda: not popup.isVisible())
assert refreshed == [True]
w.device.addItem('系统音频 · 扬声器', ('speaker', True))
w.quick_device.showPopup()
wait(popup.isVisible)
assert w.quick_device.view().isVisibleTo(popup)
w.quick_device.hidePopup()
w.close()
''', tmp_path)
