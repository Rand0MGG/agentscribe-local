"""Real Qt interaction regressions, in isolated processes with simulated content."""
import os
import subprocess
import sys


def run_qt(code, tmp_path):
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=35,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr


def test_smooth_follow_manual_interrupt_return_and_reduce_motion(tmp_path):
    run_qt('''
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from linguaflow.caption_view import CaptionScrollArea
app = QApplication([])
scroll = CaptionScrollArea()
scroll.resize(500, 350)
content = QWidget()
content.setMinimumHeight(1200)
scroll.setWidget(content)
scroll.show()
QTest.qWait(1000)
bar = scroll.verticalScrollBar()
assert scroll.following and bar.value() == bar.maximum()
assert not scroll.latest_button.isVisible()
before = bar.value()
content.setMinimumHeight(1800)
QTest.qWait(70)
assert before < bar.value() < bar.maximum(), (before, bar.value(), bar.maximum())
# New content retargets an animation which is already moving.
middle = bar.value()
content.setMinimumHeight(2200)
QTest.qWait(60)
assert middle < bar.value() < bar.maximum()
# A real wheel event interrupts immediately and no queued update drags us down.
wheel = QWheelEvent(QPointF(200, 100), QPointF(200, 100), QPoint(), QPoint(0, 120),
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                    Qt.ScrollPhase.NoScrollPhase, False)
QApplication.sendEvent(scroll.viewport(), wheel)
QTest.qWait(30)
paused = bar.value()
assert not scroll.following and not scroll.animation.isActive()
assert scroll.latest_button.isVisible()
content.setMinimumHeight(2600)
scroll.content_changed()
QTest.qWait(150)
assert bar.value() == paused and not scroll.following
QTest.mouseClick(scroll.latest_button, Qt.MouseButton.LeftButton)
QTest.qWait(70)
assert scroll.following and paused < bar.value() < bar.maximum()
QTest.qWait(1000)
assert bar.value() == bar.maximum() and not scroll.latest_button.isVisible()
# Keyboard navigation and manually reaching the bottom update the same state.
scroll.setFocus()
QTest.keyClick(scroll, Qt.Key.Key_PageUp)
QTest.qWait(30)
assert not scroll.following
QTest.keyClick(scroll, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
bar.setValue(bar.maximum())
assert scroll.following
app.setProperty('reduceMotion', True)
content.setMinimumHeight(2800)
scroll.content_changed()
QTest.qWait(40)
assert bar.value() == bar.maximum() and not scroll.animation.isActive(), (bar.value(), bar.maximum(), scroll.following, scroll.animation.isActive())
bar.setValue(100)
scroll.reset_follow()
QTest.qWait(40)
assert scroll.following and bar.value() == bar.maximum()
scroll.close()
''', tmp_path)


def test_caption_anchor_audio_selection_sync_and_recording_lock(tmp_path):
    run_qt('''
import os
from dataclasses import replace
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from linguaflow.app import STYLE, Window
from linguaflow.core import Caption
from linguaflow.recording_state import RecordingState
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
for state in (RecordingState.STARTING, RecordingState.LISTENING, RecordingState.STOPPING):
    w.set_recording_state(state)
    assert not w.quick_device.isEnabled() and not w.device.isEnabled()
    assert not w.refresh_source.isEnabled()
w.set_recording_state(RecordingState.IDLE)
assert w.quick_device.isEnabled() and w.device.isEnabled() and w.refresh_source.isEnabled()
w.reduce_motion.setChecked(True)
for i in range(1, 25):
    w.on_caption(Caption(i, i, i+1, 'A sentence in the live transcript. '+str(i), 'en'))
QTest.qWait(150)
bar = w.scroll.verticalScrollBar()
bar.setValue(w.cards[10].y())
QTest.qWait(20)
assert not w.scroll.following
offset = w.cards[10].y()-bar.value()
# Late translation above the reading position must not move the text being read.
w.on_caption(replace(w.captions[1], translation='较长的译文，需要换行显示。'*30))
QTest.qWait(150)
assert abs(w.cards[10].y()-bar.value()-offset) <= 2, (w.cards[10].y(), bar.value(), offset)
assert not w.scroll.following and w.scroll.latest_button.isVisible()
w.on_caption(Caption(25, 25, 26, 'New line at the bottom.', 'en'))
QTest.qWait(100)
assert abs(w.cards[10].y()-bar.value()-offset) <= 2, (w.cards[10].y(), bar.value(), offset)
w.clear_captions()
QTest.qWait(100)
assert w.scroll.following and not w.scroll.latest_button.isVisible()
w.close()
''', tmp_path)


def test_trackpad_phases_do_not_cancel_return_animation(tmp_path):
    run_qt('''
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from linguaflow.caption_view import CaptionScrollArea
app = QApplication([])
scroll = CaptionScrollArea()
scroll.resize(500, 350)
content = QWidget()
content.setMinimumHeight(2200)
scroll.setWidget(content)
scroll.show()
QTest.qWait(1100)
bar = scroll.verticalScrollBar()

def wheel(pixels, angle, phase, inverted=True):
    event = QWheelEvent(QPointF(200, 100), QPointF(200, 100), pixels, angle,
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, phase, inverted)
    QApplication.sendEvent(scroll.viewport(), event)
    QTest.qWait(30)

for inverted in (False, True):
    wheel(QPoint(), QPoint(), Qt.ScrollPhase.ScrollBegin, inverted)
    wheel(QPoint(0, 50), QPoint(0, 120), Qt.ScrollPhase.ScrollUpdate, inverted)
    assert not scroll.following and bar.value() < bar.maximum()
    wheel(QPoint(0, 20), QPoint(0, 40), Qt.ScrollPhase.ScrollMomentum, inverted)
    wheel(QPoint(), QPoint(), Qt.ScrollPhase.ScrollEnd, inverted)
    assert not scroll.following and scroll.latest_button.isVisible()
    # A late gesture-end event must not cancel a just-started return animation.
    QTest.mouseClick(scroll.latest_button, Qt.MouseButton.LeftButton)
    wheel(QPoint(), QPoint(), Qt.ScrollPhase.ScrollEnd, inverted)
    assert scroll.following, 'Zero-delta ScrollEnd cancelled automatic following'
    QTest.qWait(1000)
    assert bar.value() == bar.maximum()
# Touching the trackpad without moving should not cancel incoming-caption motion.
content.setMinimumHeight(3200)
QTest.qWait(40)
assert scroll.animation.isActive()
wheel(QPoint(), QPoint(), Qt.ScrollPhase.ScrollBegin)
assert scroll.following and scroll.animation.isActive()
QTest.qWait(1000)
assert bar.value() == bar.maximum()
scroll.close()
''', tmp_path)
