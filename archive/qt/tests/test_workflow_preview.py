"""Reported UI regressions exercised through the real Window, without external work."""
import os
import subprocess
import sys

import pytest
from ui_support import assert_ui_process


@pytest.mark.p1
def test_real_preview_navigation_and_task_recovery(tmp_path):
    code = r'''
import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from scripts.preview_workflows import preview_window
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
print('actual workflow regressions passed')
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                            encoding='utf-8', errors='backslashreplace', timeout=50,
                            env={**os.environ, 'PREVIEW_FIXTURE': str(tmp_path),
                                 'QT_QPA_PLATFORM': os.environ.get('LAB_TEST_PLATFORM', 'offscreen')})
    assert_ui_process(result)


@pytest.mark.p1
def test_preparation_cancel_feedback_survives_late_progress(tmp_path):
    code = r'''
import os
from pathlib import Path
from threading import Event
from PySide6.QtWidgets import QApplication
from scripts.preview_workflows import preview_window
from tests.ui_support import wait_until
app = QApplication([])
with preview_window(Path(os.environ['PREVIEW_FIXTURE'])) as (w, scenario):
    w.open_settings('运行环境')
    m = w.model_manager
    started, release = Event(), Event()
    def task():
        started.set()
        assert release.wait(8)
        return '准备完成'
    m.prepare(task, location='runtime')
    try:
        wait_until(started.is_set)
        m.cancel_button.click()
        notice = w.notifications.notices['preparation']
        assert '取消' in notice.text, notice.text
        assert notice.action is None
        assert not m.cancel_button.isEnabled()
        cancelled = m.status.text()
        m.worker.download.emit(dict(unit='stage', label='迟到的校验进度'))
        m.worker.download.emit(dict(unit='B', completed=80, total=100))
        app.processEvents()
        assert m.status.text() == cancelled
        assert '取消' in w.notifications.notices['preparation'].text
        assert w.notifications.notices['preparation'].action is None
        assert m.worker is not None and not m.retry_button.isVisible()
        from PySide6.QtTest import QTest
        for theme, width, height in ((0, 900, 650), (1, 640, 480)):
            w.appearance.setCurrentIndex(theme)
            w.resize(width, height)
            QTest.qWait(100)
            w.grab().save(str(Path(os.environ['PREVIEW_FIXTURE']) / f'cancel-{theme}.png'))
        w.leave_settings()
        app.processEvents()
        assert w.notifications.notices['preparation'].kind == 'progress'
        assert w.notifications.notices['preparation'].expires == float('inf')
    finally:
        release.set()
        wait_until(lambda:m.worker is None)
    assert '已取消' in m.status.text()
    assert m.retry_button.text() == '继续准备'
    m.retry_button.click()
    wait_until(lambda:m.worker is None)
    assert m.retry_request is None and '准备完成' in m.status.text()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                            encoding='utf-8', errors='backslashreplace', timeout=30,
                            env={**os.environ, 'PREVIEW_FIXTURE': str(tmp_path),
                                 'QT_QPA_PLATFORM': os.environ.get('LAB_TEST_PLATFORM', 'offscreen')})
    assert_ui_process(result)
