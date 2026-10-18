"""Automatic inventory work stays quiet; explicit actions retain feedback."""
from test_beta_features import run_ui


def test_inventory_automatic_manual_refresh_and_visible_guide(tmp_path):
    run_ui(r'''
from PySide6.QtWidgets import QLabel
w.start_background_check=lambda *args: None
browser=w.settings_workspace.model_browser
requests=[]
browser.start_check=lambda *args: requests.append(args)
feedback=[]
browser.feedback.connect(lambda *values:feedback.append(values))
w.open_settings('模型管理')
assert browser.busy
browser.receive({'models':[]})
assert not feedback and browser.inventory_loaded
browser.set_preparing(True);browser.set_preparing(False)
assert browser.busy
browser.receive({'models':[]})
assert not feedback
browser.refresh_button.click()
assert feedback[-1][1]=='progress'
browser.receive({'models':[]})
assert feedback[-1]==('模型列表已刷新。','success')
feedback.clear()
browser.refresh();browser.receive({'models':[]})
assert not feedback
browser.request('fixture-to-delete');browser.receive({'models':[]})
assert feedback[-1]==('模型已删除。','success')
w.open_settings('使用指南');w.show();app.processEvents()
guide='\n'.join(label.text() for label in w.settings_workspace.findChildren(QLabel) if label.isVisibleTo(w))
assert '优化中' in guide and '已定稿' in guide
assert '未提交' not in guide and '已提交，可修订' not in guide
w.close()
''', tmp_path)


def test_checkable_folder_menu_render_and_reopen(tmp_path):
    run_ui(r'''
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from linguaflow.ui_components import ActionMenu
w.show();w.reduce_motion.setChecked(True)
folder=w.library.folder('1')['id']
w.select_recording_folder(folder)
out=Path.cwd()/'.work/browser/menu-check'
out.mkdir(parents=True,exist_ok=True)
samples=[]
def capture():
    menu=app.activePopupWidget()
    assert isinstance(menu,ActionMenu)
    checked=[a for a in menu.actions() if a.isChecked()]
    assert len(checked)==1 and checked[0].text()=='1'
    menu.setActiveAction(checked[0])
    app.processEvents()
    samples.append(menu.grab())
    samples[-1].save(str(out/(str(w.appearance.currentIndex())+'.png')))
    menu.close()
for mode in (0,1):
    w.appearance.setCurrentIndex(mode)
    QTest.qWait(30)
    QTimer.singleShot(50,capture)
    w.quick_folder.click()
assert len(samples)==2
w.close()
''', tmp_path)
