"""Bulk deletion is confirmed, scoped to displayed trash entries, and preserves failures."""
import pytest
from ui_support import run_ui


@pytest.mark.p0
def test_delete_all_cancel_then_confirm_preserves_live_and_unknown_files(tmp_path):
    run_ui(r'''
from linguaflow.deleted_dialog import DeletedDialog
from PySide6.QtTest import QTest
import linguaflow.deleted_dialog as deleted_module
keep=w.library.create('inbox',{},name='保留录音')
keep_path=w.library.directory(keep['id'])
(keep_path/'录音.wav').write_bytes(b'keep me')
old=w.library.create('inbox',{},name='旧垃圾桶录音')
w.library.trash(old)
(w.library.root/'垃圾桶').rename(w.library.root/'.最近删除')
new=w.library.create('inbox',{},name='新垃圾桶录音')
w.library.trash(new)
unknown=w.library.root/'垃圾桶'/'用户文件.txt';unknown.write_text('keep unknown')
errors=[];changes=[]
d=DeletedDialog(w.library,w,warn=lambda *args:errors.append(args))
d.changed.connect(lambda:changes.append(True));d.show();settle_geometry(d)
assert d.entries.count()==2 and d.purge_all.isEnabled()
confirmations=[]
def cancel(*args):
    confirmations.append(args)
    return deleted_module.QMessageBox.StandardButton.Cancel
deleted_module.QMessageBox.warning=cancel
QTest.mouseClick(d.purge_all,Qt.MouseButton.LeftButton)
assert len(w.library.deleted())==2 and not changes
assert '2 项' in confirmations[0][2]
assert confirmations[0][-1]==deleted_module.QMessageBox.StandardButton.Cancel
# A new item arriving while the confirmation is open was never approved for deletion.
def confirm(*args):
    extra=w.library.create('inbox',{},name='确认期间新增')
    w.library.trash(extra)
    return deleted_module.QMessageBox.StandardButton.Yes
deleted_module.QMessageBox.warning=confirm
QTest.mouseClick(d.purge_all,Qt.MouseButton.LeftButton)
assert [i['name'] for i in w.library.deleted()]==['确认期间新增']
assert changes==[True] and not errors
assert (keep_path/'录音.wav').read_bytes()==b'keep me'
assert unknown.read_text()=='keep unknown'
deleted_module.QMessageBox.warning=lambda *args:deleted_module.QMessageBox.StandardButton.Yes
QTest.mouseClick(d.purge_all,Qt.MouseButton.LeftButton)
assert not w.library.deleted() and not d.purge_all.isEnabled()
assert not d.purge.isEnabled() and not d.restore.isEnabled()
assert d.empty.isVisibleTo(d)
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
    d.grab().save(str(output/'deleted-empty.png'))
d.close();w.close()
''',tmp_path)


@pytest.mark.p0
def test_delete_all_retains_shared_course_and_reports_partial_failure(tmp_path):
    run_ui(r'''
import json
from linguaflow.deleted_dialog import DeletedDialog
import linguaflow.deleted_dialog as deleted_module
course=w.library.folder('共享课程')
base=w.library.directory(course['id'])/'.agentscribe';base.mkdir()
(base/'course.json').write_text(json.dumps({'id':'course-fixture'}))
keep=w.library.create('inbox',{},name='引用课程的保留录音')
knowledge=w.library.directory(keep['id'])/'knowledge';knowledge.mkdir()
(knowledge/'manifest.json').write_text(json.dumps({'course_id':'course-fixture'}))
w.library.trash(course)
other=w.library.create('inbox',{},name='可清除录音');w.library.trash(other)
errors=[];changes=[]
d=DeletedDialog(w.library,w,warn=lambda *args:errors.append(args))
d.changed.connect(lambda:changes.append(True));d.show();settle_geometry(d)
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
    d.grab().save(str(output/'deleted-actions.png'))
deleted_module.QMessageBox.warning=lambda *args:deleted_module.QMessageBox.StandardButton.Yes
d.purge_all.click()
assert [i['name'] for i in w.library.deleted()]==['共享课程']
assert d.entries.count()==1 and d.purge_all.isEnabled()
assert errors and errors[0][0]=='部分项目未删除'
assert '仍被其他录音引用' in errors[0][1] and changes==[True]
assert (base/'course.json').exists() is False  # Original moved to trash, never back.
assert w.library.directory(keep['id']).exists()
token=w.library.deleted()[0]['token']
restored=w.library.restore_deleted(token)
assert (restored/'.agentscribe'/'course.json').is_file()
d.close();w.close()
''',tmp_path)
