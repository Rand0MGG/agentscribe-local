"""Navigation and preference regressions in an isolated, audio-free Qt process."""
import os
import subprocess
import sys

from ui_support import assert_ui_process, finish_ui_code


def test_search_navigation_motion_and_menu_stay_in_sync(tmp_path):
    code = '''
import os
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QPushButton
from linguaflow.app import STYLE, Window
from linguaflow.ui_components import ActionMenu, Disclosure, NameDialog
app = QApplication([])
app.setStyleSheet(STYLE)
prefs = QSettings(os.environ['AGENTSCRIBE_LIBRARY'] + '/prefs.ini', QSettings.Format.IniFormat)
w = Window(discover=False, prefs=prefs)
w.show()
app.processEvents()
w.open_settings('常规')
s = w.settings_workspace
s.search.setText('  草稿  ')
assert s.title.text() == '字幕与延迟'
assert not s.pages.isHidden()
s.search.setText('HY-MT2')
assert s.title.text() == '模型管理'
s.search.setText('no-such-feature')
assert s.pages.isHidden() and not s.no_results.isHidden()
clear = next(b for b in s.no_results.findChildren(QPushButton) if b.text() == '清除搜索')
clear.click()
assert not s.pages.isHidden() and s.no_results.isHidden()
w.reduce_motion.setChecked(True)
w.open_settings('识别模型')
assert s.transition.effect.opacity() == 1
disclosure = w.model_manager.findChild(Disclosure)
assert not disclosure.toggle.isChecked()
disclosure.toggle.click()
assert disclosure.toggle.isChecked()
w.open_settings('使用指南')
next(b for b in s.findChildren(QPushButton) if b.text() == '设置聆听  →').click()
assert s.title.text() == '聆听'
w.leave_settings()
assert not any(a.text() == '跟随最新字幕' for m in w.findChildren(ActionMenu) for a in m.actions())
assert w.scroll.following
assert not w.scroll.latest_button.isVisible()
assert w.pages.currentIndex() == 0
assert w.session is None
w.new_button.click()
assert w.current_item is None and not w.library.index['sessions']
assert '保存文件夹' in w.empty.text()
QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
name, accepted = NameDialog.getText(w, '新建文件夹', '文件夹名称')
assert not accepted and name == ''
w.close()
w = Window(discover=False, prefs=prefs)
assert w.reduce_motion.isChecked() and QApplication.instance().property('reduceMotion')
w.close()
'''
    result = subprocess.run([sys.executable, '-c', finish_ui_code(code)], capture_output=True, text=True, errors='backslashreplace', timeout=30,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert_ui_process(result)
