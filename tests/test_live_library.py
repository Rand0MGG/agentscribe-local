"""Manage unrelated recordings and rename the live title without moving its writer."""
from test_beta_features import run_ui


def test_live_title_and_unrelated_operations_preserve_capture_path(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QObject, QPoint
from linguaflow.core import Caption
from linguaflow.library_access import acquire_recording_lock
from linguaflow.recording_state import RecordingState
from linguaflow.library import Library
w.show();w.prepare_playback=lambda:None
assert w.new_recording(name='正在录制',check_models=False)
current_id=w.current_item['id']; original=w.library.directory(current_id)
w.library.begin(w.current_item,{})
w.recording_lock=acquire_recording_lock(original)
w.session=QObject(w);live=w.session
w.caption_translation=False
w.set_recording_state(RecordingState.LISTENING)
w.empty.setText('无内容')
other=w.library.create('inbox',{},name='其他录音')
other_path=w.library.directory(other['id'])
(other_path/'录音.wav').write_bytes(b'other recording bytes')
folder=w.library.folder('另一个文件夹')
w.refresh_library()
assert w.library_tree.isEnabled() and not w.new_button.isEnabled()
assert not w.workspace_title.label.font().bold()
assert not w.can_edit_library(w.current_item)
assert not w.can_edit_library(next(f for f in w.library.index['folders'] if f['id']=='inbox'))
assert w.can_edit_library(other)
menus=[]
module.ActionMenu.exec=lambda menu,*args:menus.append({a.text():a.isEnabled() for a in menu.actions()})
w.show_library_menu(w.library_rows[current_id],QPoint())
assert menus[-1]['重命名…'] and not menus[-1]['移到最近删除…'] and not menus[-1]['移动到文件夹']
w.show_library_menu(w.library_rows[other['id']],QPoint())
assert menus[-1]['移到最近删除…'] and menus[-1]['移动到文件夹']
# A real file handle remains writable at the original path throughout live renames.
with (original/'录音.wav').open('wb') as writer:
    writer.write(b'first');writer.flush()
    w.on_caption(Caption(1,0,1,'keep this caption','en'))
    w.rename_current();assert w.workspace_title.currentIndex()==1
    w.workspace_title.editor.setText('课堂录音')
    w.commit_recording_title('课堂录音')
    assert w.workspace_title.text()=='课堂录音'
    assert w.library_rows[current_id].text(0)=='课堂录音'
    assert w.library.directory(current_id)==original and w.session is live
    assert w.recording_lock.isLocked()
    if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
        output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
        w.resize(900,650);settle_geometry(w,w.control_island)
        w.grab().save(str(output/'live-title.png'))
    # A second Library sees the durable name, even before recording ends.
    reopened=Library(w.library.root)
    assert next(i for i in reopened.index['sessions'] if i['id']==current_id)['name']=='课堂录音'
    w.on_caption(Caption(2,1,2,'keep this too','en'))
    assert w.persist_session()
    assert w.library.load(w.current_item)[0]['session']['name']=='课堂录音'
    module.NameDialog.getText=lambda *args,**kwargs:('其他改名',True)
    w.rename_item(other)
    assert w.library.directory(other['id']).name=='其他改名'
    w.move_recording(other,folder['id'])
    assert w.library.directory(other['id']).parent==w.library.directory(folder['id'])
    module.QMessageBox.question=lambda *args:module.QMessageBox.StandardButton.Cancel
    w.delete_item(other);assert other['id'] in w.library.paths
    module.QMessageBox.question=lambda *args:module.QMessageBox.StandardButton.Yes
    w.delete_item(other)
    assert other['id'] not in w.library.paths and w.current_item['id']==current_id
    token=next(d['token'] for d in w.library.deleted() if d['id']==other['id'])
    w.library.restore_deleted(token)
    assert (w.library.directory(other['id'])/'录音.wav').read_bytes()==b'other recording bytes'
    w.refresh_library()
    # Destructive operations on the current recording or its ancestor stay blocked.
    w.delete_current()
    w.move_recording(w.current_item,folder['id'])
    assert w.library.directory(current_id)==original
    w.open_library_item(w.library_rows[other['id']],0)
    assert w.current_item['id']==current_id and w.session is live
    writer.write(b'last');writer.flush()
w._finish_session(live)
assert w.session is None
path=w.library.directory(current_id)
assert path.name=='课堂录音' and not original.exists()
assert (path/'录音.wav').read_bytes()==b'firstlast'
data,captions=w.library.load(w.current_item)
assert 'pending_name' not in data['session']
assert [c.source for c in captions]==['keep this caption','keep this too']
w.close()
''',tmp_path)


def test_saved_empty_recording_is_distinct_from_live_listening_and_pause(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QObject
from linguaflow.recording_state import RecordingState
w.show();w.prepare_playback=lambda:None
assert w.new_recording(name='空录音',check_models=False)
item=w.current_item
w.library.save(item,[], 'complete');w.library.refresh();w.refresh_library()
w.open_library_item(w.library_rows[item['id']],0)
assert w.empty.text()=='无内容' and w.empty.isVisibleTo(w)
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
    w.resize(900,650);settle_geometry(w,w.control_island)
    w.grab().save(str(output/'empty-recording.png'))
w.session=QObject(w)
w.set_recording_state(RecordingState.LISTENING);w.on_ready()
assert '处理已录音频' in w.empty.text()
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    settle_geometry(w,w.control_island)
    w.grab().save(str(output/'listening.png'))
w.on_stage('音频','输入持续为零')
assert '没有收到声音' in w.empty.text()
w.on_stage('音频','已收到声音')
assert w.empty.text()=='正在聆听…'
w.set_recording_state(RecordingState.PAUSING);w.on_paused(True)
assert w.empty.text()=='已暂停收音'
w.set_recording_state(RecordingState.RESUMING);w.on_paused(False)
assert w.empty.text()=='正在聆听…'
w.session.deleteLater();w.session=None
w.set_recording_state(RecordingState.IDLE);w.close()
''',tmp_path)
