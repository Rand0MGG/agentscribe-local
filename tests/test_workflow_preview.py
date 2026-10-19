"""Reported UI regressions exercised through the real Window, without external work."""
import os
import subprocess
import sys

from ui_support import assert_ui_process


def test_real_preview_navigation_task_recovery_focus_menus_and_transitions(tmp_path):
    code = r'''
import os
from pathlib import Path
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from scripts.preview_workflows import preview_window
from linguaflow.ui_components import ActionMenu
from linguaflow.recording_state import RecordingState
from tests.ui_support import wait_until
app = QApplication([])
app.setStyle('Fusion')
with preview_window(Path(os.environ['PREVIEW_FIXTURE'])) as (w, scenario):
    scenario.delay = .004
    w.resize(900,650)
    QTest.qWait(100)
    w.activateWindow()
    w.raise_()
    # Select a folder first, then use the actual asynchronous click/load route.
    folder = next(row for row in w.library_rows.values() if row.data(0,Qt.ItemDataRole.UserRole)[0]=='folder')
    w.open_library_item(folder,0)
    item = w.library.index['sessions'][-1]
    row = w.library_rows[item['id']]
    w.library_tree.scrollToItem(row)
    point = w.library_tree.visualItemRect(row).center()
    QTest.mouseClick(w.library_tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    wait_until(lambda:w.current_item is not None and w.current_item['id']==item['id'])
    assert w.library_tree.currentItem().data(0,Qt.ItemDataRole.UserRole)==('session',item['id'])
    # Mouse focus must not leave the dark keyboard outline after closing a dialog.
    w.open_settings('模型管理')
    QTest.qWait(80)
    trigger = w.settings_workspace.download_model
    QTest.mouseClick(trigger, Qt.MouseButton.LeftButton)
    assert not trigger.property('keyboardFocus')
    from linguaflow.model_dialog import ModelCatalogDialog
    dialog = next(d for d in app.topLevelWidgets() if isinstance(d,ModelCatalogDialog) and d.isVisible())
    dialog.download_buttons[0].click()
    wait_until(lambda:w.model_manager.worker is None)
    m=w.model_manager
    assert m.retry_button.isVisibleTo(w) and m.download_card.isVisibleTo(w)
    assert '准备未完成' in m.status.text()
    first = dict(scenario.attempts)
    m.retry_button.click()
    wait_until(lambda:m.worker is None)
    assert list(scenario.attempts.values())==[2] and set(scenario.attempts)==set(first)
    assert m.retry_request is None and not m.retry_button.isVisible()
    w.open_settings('运行环境')
    m.install_runtime()
    QTest.qWait(50)
    assert m.progress_bar.isVisibleTo(w) and m.cancel_button.isVisibleTo(w)
    assert m.progress_bar.maximum()==0
    assert m.download_card.parentWidget() is m.runtime_task_layout.parentWidget()
    assert m.status.height() >= m.status.fontMetrics().height()
    assert m.runtime_form.parentWidget().geometry().top() > m.download_card.geometry().bottom()
    m.cancel_button.click()
    wait_until(lambda:m.worker is None)
    assert m.retry_button.isVisibleTo(w) and m.retry_button.text()=='继续准备'
    m.retry_button.click()
    wait_until(lambda:m.worker is None)
    assert m.retry_request is None
    # Both directions of the live-control -> playback-rail morph must animate.
    w.leave_settings()
    w.reduce_motion.setChecked(False)
    w.playback.setProperty('available', False)
    w.set_recording_state(RecordingState.IDLE)
    w.update_transport()
    QTest.qWait(330)
    island=w.control_island
    initial=island.geometry()
    w.playback.setProperty('available', True)
    w.playback_duration(60000)
    w.update_transport()
    def verify_morph(start):
        motion = island.resize_motion
        wait_until(lambda:motion.state()==motion.State.Running)
        target = island._target_geometry
        assert start != target, (start,target)
        assert motion.startValue()==start and motion.endValue()==target
        # Inspect a deterministic middle frame, not a 50ms wall-clock guess.
        # Platform fonts can make playback narrower rather than wider.
        motion.pause()
        motion.setCurrentTime(motion.duration()//2)
        middle = island.geometry()
        assert middle != start and middle != target, (start,middle,target)
        for a,b,c in zip(start.getRect(),middle.getRect(),target.getRect()):
            assert min(a,c) <= b <= max(a,c), (start,middle,target)
        motion.resume()
        wait_until(lambda:motion.state()==motion.State.Stopped and island.geometry()==target)
    verify_morph(initial)
    initial = island.geometry()
    w.playback.setProperty('available', False)
    w.update_transport()
    verify_morph(initial)
    w.resize(640,480)
    QTest.qWait(80)
    menu=ActionMenu(w)
    chosen=[]
    for i in range(35):
        menu.addAction('操作项目 '+str(i), lambda i=i:chosen.append(i))
    menu.popup(w.mapToGlobal(QPoint(w.width()-10,70)))
    QTest.qWait(80)
    assert menu.available_bounds().contains(menu.geometry()), (menu.available_bounds(),menu.geometry())
    QTest.keyClick(menu,Qt.Key.Key_End)
    QTest.qWait(40)
    assert menu.activeAction() is menu.actions()[-1]
    assert menu.rect().contains(menu.actionGeometry(menu.activeAction()).center())
    QTest.keyClick(menu,Qt.Key.Key_Return)
    assert chosen==[34]
    menu.deleteLater()
    parent=ActionMenu(w)
    child=ActionMenu(parent)
    child.setTitle('移动到')
    for i in range(30):
        child.addAction('目录 '+str(i))
    parent.addMenu(child)
    parent.popup(w.mapToGlobal(QPoint(w.width()-12,100)))
    QTest.qWait(50)
    QTest.keyClick(parent,Qt.Key.Key_Down)
    QTest.keyClick(parent,Qt.Key.Key_Right)
    QTest.qWait(100)
    assert child.isVisible() and child.available_bounds().contains(child.geometry())
    QTest.keyClick(child,Qt.Key.Key_End)
    QTest.qWait(30)
    assert child.rect().contains(child.actionGeometry(child.activeAction()).center())
    QTest.keyClick(child,Qt.Key.Key_Escape)
    parent.hide()
    parent.deleteLater()
    if w.custom_frame:
        assert w.centralWidget().corner_radius==8
        picture=w.centralWidget().grab().toImage()
        assert any(0<picture.pixelColor(x,y).alpha()<255 for x in range(14) for y in range(14))
    out=Path(os.environ['PREVIEW_FIXTURE'])
    w.grab().save(str(out/'workflow-final.png'))
print('actual workflow regressions passed')
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                            encoding='utf-8', errors='backslashreplace', timeout=50,
                            env={**os.environ, 'PREVIEW_FIXTURE': str(tmp_path),
                                 'QT_QPA_PLATFORM': os.environ.get('LAB_TEST_PLATFORM', 'offscreen')})
    assert_ui_process(result)
