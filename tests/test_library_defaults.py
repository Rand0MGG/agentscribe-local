"""An empty library remains usable without losing recently deleted recordings."""
from test_beta_features import run_ui


def test_new_workspace_recreates_default_folder_after_last_folder_is_deleted(tmp_path):
    run_ui(r'''
from linguaflow.ui_components import ActionMenu
from PySide6.QtCore import QTimer
original=w.library.index['folders'][0]
token=w.library.trash(original)
w.folder_id=original['id']
assert not w.library.index['folders']
w.new_button.click()
folders=w.library.index['folders']
assert len(folders)==1 and folders[0]['name']=='我的录音'
assert w.folder_id==folders[0]['id'] and w.folder_id!=original['id']
assert w.library.directory(w.folder_id).is_dir()
assert w.current_item is None and not w.library.index['sessions']
assert w.library_tree.currentItem().text(0)=='我的录音'
for _ in range(2):
    w.new_button.click()
assert len(w.library.index['folders'])==1 and not w.library.index['sessions']
selected=[]
def pick_folder():
    menu=app.activePopupWidget()
    assert isinstance(menu,ActionMenu)
    selected.extend(action.text() for action in menu.actions())
    menu.actions()[0].trigger();menu.close()
QTimer.singleShot(30,pick_folder)
w.quick_folder.click()
assert selected==['我的录音']
assert [item['token'] for item in w.library.deleted()]==[token]
w.library.restore_deleted(token)
assert len(w.library.index['folders'])==2
assert w.library.directory(original['id']).name=='我的录音 (2)'
w.close()
''',tmp_path)


def test_new_workspace_uses_existing_folder_when_selection_is_stale(tmp_path):
    run_ui(r'''
old=w.library.index['folders'][0]
remaining=w.library.folder('现有课程')
w.library.trash(old)
w.folder_id=old['id']
assert w.new_recording()
assert w.folder_id==remaining['id']
assert len(w.library.index['folders'])==1 and not w.library.index['sessions']
w.close()
''',tmp_path)


def test_empty_folder_picker_creates_and_selects_default_without_a_recording(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QTimer
from linguaflow.ui_components import ActionMenu
w.library.trash(w.library.index['folders'][0])
w.folder_id=None
choices=[]
def inspect_menu():
    menu=app.activePopupWidget()
    assert isinstance(menu,ActionMenu)
    choices.extend((action.text(),action.isChecked()) for action in menu.actions())
    menu.close()
QTimer.singleShot(30,inspect_menu)
w.quick_folder.click()
assert choices==[('我的录音',True)]
assert w.library.directory(w.folder_id).name=='我的录音'
assert len(w.library.index['folders'])==1 and not w.library.index['sessions']
w.close()
''',tmp_path)


def test_default_folder_write_failure_reports_error_without_resetting_view(tmp_path):
    run_ui(r'''
original=w.library.index['folders'][0]
w.library.trash(original)
w.workspace_title.setText('保留当前标题')
messages=[]
w.show_warning=lambda title,message:messages.append((title,message))
def denied(*args,**kwargs):
    raise PermissionError('default folder is read-only')
w.library.folder=denied
assert not w.new_recording()
assert messages and 'read-only' in messages[0][1]
assert w.workspace_title.text()=='保留当前标题'
assert not w.library.index['folders'] and not w.library.index['sessions']
w.close()
''',tmp_path)
