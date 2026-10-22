"""One-click recording workspace, safe naming and consistent control geometry."""
import pytest
from ui_support import run_ui


@pytest.mark.p0
def test_new_workspace_uses_defaults_without_creating_empty_recordings(tmp_path):
    run_ui(r'''
from PySide6.QtTest import QTest
from linguaflow.core import Caption
assert w.new_recording(name='已有录音',check_models=False)
w.on_caption(Caption(1,0,2,'Existing saved text','en'))
assert w.persist_session('complete')
identifier=w.current_item['id']
path=w.library.directory(identifier)/'session.json'
before=path.read_bytes()
w.notifications.post('session','录音与字幕已保存。',kind='success')
w.show()
for _ in range(3):
    w.new_button.click()
    assert app.activeModalWidget() is None
    assert w.current_item is None and w.session is None
    assert len(w.library.index['sessions'])==1
    assert path.read_bytes()==before
    assert 'status' not in w.notifications.notices and 'session' not in w.notifications.notices
    assert not w.start_button.isHidden()
    assert '音频来源：' in w.empty.text() and '保存文件夹：' in w.empty.text() and '语言：' in w.empty.text()
assert not any(b.accessibleName()=='关闭当前录音' for b in w.findChildren(module.QPushButton))
QTest.mouseClick(w.workspace_title.label,Qt.MouseButton.LeftButton)
assert w.workspace_title.currentIndex()==1
w.workspace_title.editor.setText('第二段录音')
w.commit_recording_title(w.workspace_title.editor.text())
assert w.pending_recording_name=='第二段录音' and w.workspace_title.text()=='第二段录音'
w.rename_current()
w.workspace_title.editor.setText('取消这个名称')
QTest.keyClick(w.workspace_title.editor,Qt.Key.Key_Escape)
assert w.pending_recording_name=='第二段录音' and w.workspace_title.currentIndex()==0
folder=w.library.folder('课堂')['id']
from PySide6.QtCore import QTimer
from linguaflow.ui_components import ActionMenu
menus=[]
def select_from_menu():
    menu=app.activePopupWidget()
    if isinstance(menu,ActionMenu):
        menus.append(menu.screen().availableGeometry().contains(menu.geometry())
                     and all(menu.actionGeometry(action).height()>=34
                             and menu.rect().contains(menu.actionGeometry(action)) for action in menu.actions()))
        next(action for action in menu.actions() if action.text()=='课堂').trigger()
        menu.close()
QTimer.singleShot(30,select_from_menu)
w.quick_folder.click()
assert menus==[True]
assert w.folder_id==folder and '课堂' in w.empty.text()
assert len(w.library.index['sessions'])==1 and path.read_bytes()==before
w.device.addItem('外部输入 · 测试麦克风',('fixture',False))
assert '测试麦克风' in w.empty.text()
w.source.setCurrentIndex(1)
w.update_quick_settings()
assert w.source.currentText() in w.empty.text()
# Start creates the selected draft with the inline name. Stop before inference or audio.
assert w.new_recording(name=w.pending_recording_name,check_models=False)
assert w.current_item['name']=='第二段录音' and w.current_item['folder']==folder
assert path.read_bytes()==before
w.rename_current()
w.workspace_title.editor.setText('已改名')
w.commit_recording_title('已改名')
assert w.current_item['name']=='已改名'
assert w.library.directory(w.current_item['id']).name=='已改名'
messages=[]
w.show_warning=lambda title,message: messages.append(title)
w.rename_current()
w.commit_recording_title('../不合法')
assert messages and w.current_item['name']=='已改名' and path.read_bytes()==before
w.notifications.post('save','保存失败，原内容保留。',kind='error')
w.new_button.click()
assert w.notifications.notices['save'].kind=='error'
w.notifications.clear('save')
w.close()
''',tmp_path)
