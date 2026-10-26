"""One-click recording workspace, safe naming and consistent control geometry."""
import pytest
from ui_support import run_ui


@pytest.mark.p2
@pytest.mark.parametrize('flags', [dict(final=False), dict(asr_final=False), dict(boundary_final=False), dict(source='  ')])
def test_export_requires_confirmed_nonempty_source(tmp_path, flags):
    run_ui('''
from linguaflow.core import Caption
w.new_recording(name='导出定稿资格',check_models=False)
values=dict(id=1,start=0,end=2,source='Not confirmed',language='en')
values.update(%r)
w.on_caption(Caption(**values))
assert not w.export_action.isEnabled()
w.on_caption(Caption(1,0,2,'Confirmed source','en',revision=2))
assert w.export_action.isEnabled()
assert w.persist_session('complete')
w.close()
'''%flags,tmp_path)


@pytest.mark.p2
def test_live_final_captions_do_not_reenable_export_until_idle(tmp_path):
    run_ui('''
from linguaflow.core import Caption
from linguaflow.recording_state import RecordingState
w.new_recording(name='录音导出资格',check_models=False)
w.set_recording_state(RecordingState.LISTENING)
assert not w.export_action.isEnabled()
w.on_caption(Caption(1,0,2,'Live final caption','en',final=True))
assert not w.export_action.isEnabled()
def unexpected_dialog(*args):raise AssertionError('Active recording must not open the export dialog')
module.QFileDialog.getSaveFileName=unexpected_dialog
w.export()
assert w.notifications.notices['export'].text=='请先停止录音再导出定稿。'
w.set_recording_state(RecordingState.STOPPING)
w.on_caption(Caption(2,2,4,'Drained final caption','en',final=True))
assert not w.export_action.isEnabled()
w.set_recording_state(RecordingState.IDLE)
assert w.export_action.isEnabled()
assert w.persist_session('complete')
w.close()
''',tmp_path)


@pytest.mark.p0
def test_new_workspace_uses_defaults_without_creating_empty_recordings(tmp_path):
    run_ui(r'''
from PySide6.QtTest import QTest
from linguaflow.core import Caption
assert not any(button.text() in ('悬浮字幕','导出定稿') for button in w.recording_actions.findChildren(module.QPushButton))
assert w.overlay_action.text()=='悬浮字幕' and w.export_action.text()=='导出定稿'
assert not w.export_action.isEnabled()
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
