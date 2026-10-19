"""Behavioral checks for the isolated design lab, never the production pages."""
import os
import subprocess
import sys

from ui_support import assert_ui_process


def test_lab_cancel_ime_following_task_recovery_and_close():
    code = r'''
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QFocusEvent, QInputMethodEvent, QKeyEvent, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout, QPushButton
from scripts.preview_components import ComponentLab, ResponsiveRow
from tests.ui_support import wait_until

app = QApplication([])
app.setStyle('Fusion')
w = ComponentLab()
w.show()
wait_until(w.isVisible)
assert w.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
assert w.windowFlags() & Qt.WindowType.FramelessWindowHint
assert not w.progress.isTextVisible()
# Route through QWindow and the active popup, as real mouse input does.
# Widget-targeted QTest alone skips Qt's popup dismissal/replay path.
QTest.qWait(50)
for choice in (w.category, w.theme, w.choice):
    closed_arrow = choice.grab().toImage()
    for click in range(6):
        target = app.activePopupWidget() or w
        point = choice.mapToGlobal(choice.rect().center())
        QTest.mouseClick(target.windowHandle(), Qt.MouseButton.LeftButton,
                         pos=target.mapFromGlobal(point))
        QTest.qWait(30)  # Also deliver any queued replay before asserting.
        assert choice.choice_popup.isVisible() == (click % 2 == 0), (choice.accessibleName(), click)
        if click == 0:
            opened_arrow = choice.grab().toImage()
            scale = opened_arrow.devicePixelRatio()
            x, y = int((choice.width()-24)*scale), int((choice.height()/2-6)*scale)
            assert closed_arrow.copy(x, y, int(14*scale), int(12*scale)) != opened_arrow.copy(x, y, int(14*scale), int(12*scale))
# Repeated anchor clicks, native-popup outside routing and keyboard selection.
for _ in range(3):
    QTest.mouseClick(w.choice, Qt.MouseButton.LeftButton)
    assert w.choice.choice_popup.isVisible()
    QTest.mouseClick(w.choice, Qt.MouseButton.LeftButton)
    assert not w.choice.choice_popup.isVisible()
w.choice.showPopup()
QTest.mouseClick(w.choice.choice_popup, Qt.MouseButton.LeftButton, pos=QPoint(-10, -10))
assert not w.choice.choice_popup.isVisible()
w.choice.showPopup()
QTest.keyClick(w.choice.view(), Qt.Key.Key_Down)
QTest.keyClick(w.choice.view(), Qt.Key.Key_Return)
assert w.choice.currentIndex() == 1 and not w.choice.choice_popup.isVisible()
w.choice.showPopup()
QTest.keyClick(w.choice.view(), Qt.Key.Key_Escape)
assert not w.choice.choice_popup.isVisible()
w.choice.setCurrentIndex(0)
# Choose themes through the popup's native window, then move the pointer away.
# Mouse selection must not leave a focus border; keyboard entry must retain one.
for mode in (1, 0, 1, 0):
    choice = w.theme
    QTest.mouseClick(w.windowHandle(), Qt.MouseButton.LeftButton,
                     pos=choice.mapTo(w, choice.rect().center()))
    view = choice.view()
    first = view.visualRect(view.model().index(0, 0)).adjusted(4, 2, -4, -2)
    last = view.visualRect(view.model().index(1, 0)).adjusted(4, 2, -4, -2)
    popup = choice.choice_popup
    a = view.viewport().mapTo(popup, first.topLeft())
    b = view.viewport().mapTo(popup, last.bottomRight())
    assert (a.x()-12, a.y()-8, popup.width()-13-b.x(), popup.height()-17-b.y()) == (8, 8, 8, 8)
    point = view.viewport().mapToGlobal(view.visualRect(view.model().index(mode, 0)).center())
    popup = choice.choice_popup
    QTest.mouseClick(popup.windowHandle(), Qt.MouseButton.LeftButton,
                     pos=popup.mapFromGlobal(point))
    QTest.mouseMove(w.windowHandle(), QPoint(8, 8))
    QTest.qWait(30)
    assert not popup.isVisible() and choice.currentIndex() == mode
    assert not choice.property('keyboardFocus')
    # Offscreen popup dismissal does not reliably reactivate its owner on Mac.
    # setFocus on an inactive window only records a future focus request.
    app.setActiveWindow(w)
    wait_until(w.isActiveWindow)
    mouse_image = choice.grab().toImage()
    choice.clearFocus()
    app.processEvents()
    assert mouse_image == choice.grab().toImage()
    choice.setFocus(Qt.FocusReason.TabFocusReason)
    wait_until(choice.hasFocus)
    assert choice.property('keyboardFocus')
    assert mouse_image != choice.grab().toImage()
    choice.clearFocus()
# Disabled role styling must win over normal secondary styling in both themes.
disabled = next(b for b in w.findChildren(QPushButton) if b.text() == '不可用')
for mode in range(2):
    w.theme.setCurrentIndex(mode)
    app.processEvents()
    enabled = next(b for b in w.findChildren(QPushButton)
                   if b.objectName() == 'secondary' and b.isEnabled())
    role = QPalette.ColorRole.ButtonText
    assert disabled.palette().color(QPalette.ColorGroup.Disabled, role) != enabled.palette().color(QPalette.ColorGroup.Active, role)
w.theme.setCurrentIndex(0)
# Mouse focus uses the track only; keyboard focus remains visible.
QTest.mouseClick(w.switch, Qt.MouseButton.LeftButton)
wait_until(lambda: w.switch.position == float(w.switch.isChecked()))
assert not w.switch.keyboard_focus
app.sendEvent(w.switch, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
assert w.switch.keyboard_focus
checked = w.switch.isChecked()
QTest.keyClick(w.switch, Qt.Key.Key_Space)
wait_until(lambda: w.switch.position == float(w.switch.isChecked()))
assert w.switch.isChecked() != checked
w.switch.setEnabled(False)
checked = w.switch.isChecked()
QTest.mouseClick(w.switch, Qt.MouseButton.LeftButton)
assert w.switch.isChecked() == checked
w.switch.setEnabled(True)
# A narrow responsive row preserves its selected value and actually stacks.
w.resize(640, 480)
wait_until(lambda: w.width() == 640)
row = w.findChildren(ResponsiveRow)[0]
row.resize(400, 160)
app.processEvents()
assert row.box.direction() == QBoxLayout.Direction.TopToBottom
assert w.choice.currentIndex() == 0

# The complete popup, including shadow margins, stays inside its owner.
for width, height in ((640, 480), (1100, 780)):
    w.resize(width, height)
    QTest.qWait(30)
    for choice in (w.category, w.theme, w.choice):
        choice.showPopup()
        app.processEvents()
        bounds = QRect(w.mapToGlobal(QPoint()), w.size())
        assert bounds.contains(choice.choice_popup.geometry())
        choice.hidePopup()
w.choice.addItems([f'Extra option {i}' for i in range(20)])
w.resize(640, 480)
QTest.qWait(30)
w.choice.showPopup()
app.processEvents()
assert QRect(w.mapToGlobal(QPoint()), w.size()).contains(w.choice.choice_popup.geometry())
assert w.choice.view().verticalScrollBar().maximum() > 0
QTest.keyClick(w.choice.view(), Qt.Key.Key_End)
QTest.keyClick(w.choice.view(), Qt.Key.Key_Return)
assert w.choice.currentIndex() == w.choice.count()-1
for i in range(w.choice.count()-1, 2, -1):
    w.choice.removeItem(i)
w.choice.setCurrentIndex(0)
w.choice.showPopup()
w.resize(660, 480)
app.processEvents()
assert not w.choice.choice_popup.isVisible()

w.category.setCurrentIndex(1)
w.open_dialog()
dialog = w.dialog
QTest.qWait(30)
dialog.field.clear()
QTest.mouseClick(dialog.save, Qt.MouseButton.LeftButton)
assert dialog.isVisible() and dialog.error.text()
dialog.field.setText('new sample')
app.sendEvent(dialog.field, QInputMethodEvent('pinyin', []))
app.sendEvent(dialog, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
assert dialog.isVisible() and dialog.composing
app.sendEvent(dialog.field, QInputMethodEvent())
QTest.keyClick(dialog, Qt.Key.Key_Escape)
assert not dialog.isVisible()
assert 'new sample' not in w.name_result.text()
w.open_dialog()
w.dialog.field.setText('accepted sample')
QTest.mouseClick(w.dialog.save, Qt.MouseButton.LeftButton)
assert 'accepted sample' in w.name_result.text()
w.open_dialog()
assert w.dialog.field.text() == 'accepted sample'
w.dialog.field.setText('discard this')
w.dialog.reject()
w.open_dialog()
assert w.dialog.field.text() == 'accepted sample'
w.dialog.reject()

w.category.setCurrentIndex(2)
w.reduce.setChecked(True)
wait_until(lambda: w.scroll.verticalScrollBar().maximum() > 0)
w.scroll.jump_to_latest()
wait_until(lambda: w.scroll._at_bottom())
w.scroll.browse_history()
w.scroll.verticalScrollBar().setValue(0)
app.processEvents()
w.append_caption()
w.revise_caption()
QTest.qWait(80)
assert not w.scroll.following
assert w.scroll.verticalScrollBar().value() == 0
w.toggle_island()
assert w.island.property('recording')
w.playback.setChecked(True)
assert not w.island.property('recording') and w.volume.isVisible()
w.volume.set_expanded(True)
assert w.volume.progress == 1
w.stream.start()
w.category.setCurrentIndex(3)
assert not w.stream.isActive()

w.task_unknown.setChecked(True)
assert w.progress.maximum() == 100  # An idle task must not animate as running.
w.start_task()
assert w.progress.maximum() == 0
w.advance_task()
value = w.task_value
w.start_task()
assert w.task_value == value  # Busy task is not accidentally restarted.
w.notices._dismiss()
w.advance_task()
assert not w.notices.isVisible()  # Stage updates respect dismissal.
w.fail_task()
assert w.task_state == 'failed' and w.task_retry.isVisible()
w.start_task()
assert w.progress.maximum() == 0
w.cancel_task()
value = w.task_value
w.advance_task()
assert w.task_state == 'cancelled' and w.task_value == value
w.task_unknown.setChecked(False)
w.task_unknown.setChecked(True)
assert w.progress.maximum() == 100
w.task_unknown.setChecked(False)
w.start_task()
w.advance_task()
assert w.notices.progress.value() == w.task_value
while w.task_state == 'running':
    w.advance_task()
assert w.task_state == 'complete' and w.progress.value() == 100
assert not w.task_timer.isActive() and not w.task_cancel.isEnabled()
w.task_unknown.setChecked(True)
assert w.progress.maximum() == 100 and w.progress.value() == 100
w.start_task()  # Keep shutdown coverage for an active task.
w.theme.setCurrentIndex(1)
assert app.property('appearance') == 'dark'
w.show_overlay()
w.close()
app.processEvents()
assert not w.isVisible() and not w.overlay.isVisible()
assert not any(timer.isActive() for timer in w.findChildren(QTimer)), [(type(t.parent()).__name__, t.interval()) for t in w.findChildren(QTimer) if t.isActive()]
assert not w.overlay.hide_controls.isActive()
print('lab behaviors and active-task shutdown passed')
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                            encoding='utf-8', errors='backslashreplace', timeout=45,
                            env={**os.environ, 'QT_QPA_PLATFORM': os.environ.get('LAB_TEST_PLATFORM', 'offscreen')})
    assert_ui_process(result)
