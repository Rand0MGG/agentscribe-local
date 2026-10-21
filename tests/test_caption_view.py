"""Real Qt interaction regressions, in isolated processes with simulated content."""
import os

from ui_support import run_ui_process


def run_qt(code, tmp_path):
    run_ui_process(code, timeout=35,
                   env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGENTSCRIBE_LIBRARY': str(tmp_path)})


def test_caption_anchor_audio_selection_sync_and_recording_lock(tmp_path):
    run_qt('''
import os
import sys
from pathlib import Path
from dataclasses import replace
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import STYLE, Window
from linguaflow.core import Caption
from linguaflow.recording_state import RecordingState
sys.path.insert(0, str(Path(__import__('linguaflow').__file__).resolve().parent.parent / 'tests'))
from ui_support import settle_geometry, wait_until
app = QApplication([])
app.setStyleSheet(STYLE)
prefs = QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat)
w = Window(discover=False, prefs=prefs)
w.resize(900, 650)
w.show()
w.device.addItem('麦克风 · 测试输入', ('mic', False))
w.device.addItem('系统声音 · 很长的设备名称用于验证窗口缩放与下拉选择', ('loopback', True))
assert w.quick_device.isVisible() and w.quick_device.count() == 2
w.quick_device.setCurrentIndex(1)
assert w.device.currentData() == ('loopback', True)
w.device.setCurrentIndex(0)
assert w.quick_device.currentData() == ('mic', False)
for state in (RecordingState.STARTING, RecordingState.LISTENING, RecordingState.PAUSING,
              RecordingState.PAUSED, RecordingState.RESUMING, RecordingState.STOPPING):
    w.set_recording_state(state)
    enabled = state in (RecordingState.LISTENING, RecordingState.PAUSED)
    assert w.quick_device.isEnabled() == w.device.isEnabled() == enabled
    assert w.refresh_source.isEnabled() == enabled
w.set_recording_state(RecordingState.IDLE)
assert w.quick_device.isEnabled() and w.device.isEnabled() and w.refresh_source.isEnabled()
w.reduce_motion.setChecked(True)
for i in range(1, 25):
    w.on_caption(Caption(i, i, i+1, 'A sentence in the live transcript. '+str(i), 'en'))
geometry_widgets = (w.scroll, w.control_island, w.cards[10])
settle_geometry(*geometry_widgets)
bar = w.scroll.verticalScrollBar()
wait_until(lambda: not w.scroll.layout_timer.isActive() and bar.value() == bar.maximum())
assert 0 < w.cards[10].y() < bar.maximum()
bar.setValue(w.cards[10].y())
settle_geometry(*geometry_widgets)
assert not w.scroll.following
offset = w.cards[10].y()-bar.value()
# Late translation above the reading position must not move the text being read.
w.on_caption(replace(w.captions[1], translation='较长的译文，需要换行显示。'*30))
settle_geometry(*geometry_widgets)
assert abs(w.cards[10].y()-bar.value()-offset) <= 2, (w.cards[10].y(), bar.value(), offset)
assert not w.scroll.following and w.scroll.latest_button.isVisible()
w.on_caption(Caption(25, 25, 26, 'New line at the bottom.', 'en'))
settle_geometry(*geometry_widgets)
assert abs(w.cards[10].y()-bar.value()-offset) <= 2, (w.cards[10].y(), bar.value(), offset)
w.clear_captions()
wait_until(lambda: w.scroll.following and not w.scroll.latest_button.isVisible())
assert w.scroll.following and not w.scroll.latest_button.isVisible()
w.close()
''', tmp_path)
