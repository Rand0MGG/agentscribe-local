"""User-visible regressions for long transcripts and failed-save recovery."""
import pytest
from ui_support import run_ui


@pytest.mark.p2
def test_long_recording_search_pages_and_playback_load_history(tmp_path):
    run_ui('''
from linguaflow.core import Caption
from linguaflow.playback import PlaybackIndex
w.new_recording(name='长课堂',check_models=False)
for i in range(1,406):
    w.on_caption(Caption(i,i*4,i*4+3,f'Lecture sentence {i}.','en'))
assert len(w.captions)==405 and len(w.cards)<=200
assert w.persist_session('complete')
identifier=w.current_item['id']
w.open_library_item(w.library_rows[identifier],0)
w.show();settle_geometry(w)
w.find_captions();s=w.search_dialog
s.query.setText('Lecture sentence 1.');s.search();s.choose()
settle_geometry(w)
assert 1 in w.cards and w.cards[1].isVisibleTo(w)
assert 'operation' not in w.notifications.notices
assert len(w.cards)<=200
w.newer_captions.click();settle_geometry(w)
assert max(w.cards)>200 and len(w.cards)<=200
w.older_captions.click();settle_geometry(w)
assert 1 in w.cards
w.scroll.set_playback(True)
w.playback_index=PlaybackIndex(w.captions.values())
w.seek_playback(405*4000)
settle_geometry(w)
assert 405 in w.cards and w.cards[405].property('playing')
assert len(w.cards)<=200
w.locate_caption(identifier,1);settle_geometry(w)
assert 1 in w.cards and not w.scroll.following
w.highlight_playback(405*4000);app.processEvents()
assert 1 in w.cards and w.scroll.latest_button.isVisibleTo(w)
w.scroll.latest_button.click();settle_geometry(w)
assert 405 in w.cards
w.close()
''',tmp_path)


@pytest.mark.p0
def test_failed_save_keeps_real_lock_and_releases_only_after_retry(tmp_path):
    run_ui('''
from linguaflow.core import Caption
from linguaflow.library_access import acquire_recording_lock
w.new_recording(name='写入失败',check_models=False)
w.on_caption(Caption(1,0,2,'Unsaved content.','en'))
directory=w.library.directory(w.current_item['id'])
w.recording_lock=acquire_recording_lock(directory)
original=w.library.save
def fail(*args): raise OSError('disk full')
w.library.save=fail
assert not w.persist_session('incomplete')
assert w.session_dirty and w.save_error and w.recording_lock is not None
try:
    acquire_recording_lock(directory)
    raise AssertionError('Another instance acquired an unsaved recording')
except ValueError:
    pass
assert w.retry_save_action.isEnabled() and w.backup_action.isEnabled()
w.library.save=original
w.retry_save();wait(lambda:not w.recording_saver.busy)
assert not w.session_dirty and not w.save_error and w.recording_lock is None
other=acquire_recording_lock(directory);other.unlock()
assert not w.retry_save_action.isEnabled()
w.close()
''',tmp_path)


@pytest.mark.p1
def test_save_error_does_not_expire_and_dismissal_keeps_recovery_actions(tmp_path):
    run_ui('''
from types import SimpleNamespace
from unittest.mock import patch
import linguaflow.notifications as feedback
from linguaflow.core import Caption
w.new_recording(name='保存恢复入口',check_models=False)
w.on_caption(Caption(1,0,2,'Draft words.','en',final=False))
w.show()
clock=[100.]
with patch.object(feedback,'time',SimpleNamespace(monotonic=lambda:clock[0])):
    w.save_error='OSError: disk full';w.update_activity()
    clock[0]+=60;w.notifications._refresh();w.update_activity()
    assert w.notifications.current_key=='save'
    w.notifications.dismiss.click()
    assert w.retry_save_action.isEnabled() and w.backup_action.isEnabled()
w.save_error='';assert w.persist_session('incomplete')
w.close()
''',tmp_path)


@pytest.mark.p1
def test_draft_backup_preserves_text_without_claiming_main_save_success(tmp_path):
    run_ui('''
from unittest.mock import patch
from linguaflow.core import Caption
w.new_recording(name='只有草稿',check_models=False)
w.on_caption(Caption(1,0,2,'Only draft.','en','初译内容',final=False,translation_phase='initial'))
w.source_preview={'source':'Newest unfinished words.','start':2,'end':3,'language':'en','keep_ids':[1]}
w.save_error='OSError: disk full';w.update_activity()
assert not w.export_button.isEnabled() and w.backup_action.isEnabled()
target=Path(os.environ['AGENTSCRIBE_LIBRARY'])/'恢复文字.txt'
with patch.object(module.QFileDialog,'getSaveFileName',return_value=(str(target),'文字恢复备份 (*.txt)')):
    w.backup_recording_text()
wait(lambda:not w.export_saver.busy)
text=target.read_text(encoding='utf-8-sig')
assert 'Only draft.' in text and 'Newest unfinished words.' in text and '初译内容' in text
assert '草稿' in text and '不包含音频' in text
assert w.session_dirty and w.save_error and w.current_item is not None
assert w.notifications.notices['recovery'].kind=='success'
w.source_preview=None;w.save_error='';assert w.persist_session('incomplete')
w.close()
''',tmp_path)


@pytest.mark.p2
def test_actionable_warning_shows_reason_without_opening_diagnostics(tmp_path):
    run_ui('''
w.show();w.show_warning('无法创建文件夹','名称最多 64 个字符。')
assert '64' in w.notifications.message.text()
assert '名称' in w.notifications.message.text()
assert w.diagnostics.isHidden()
w.close()
''',tmp_path)


@pytest.mark.p0
def test_course_drafts_remain_bound_to_their_course_with_real_worker(tmp_path):
    run_ui('''
from linguaflow.knowledge.materials import course_for_folder
from linguaflow.knowledge.files import read_json
w.beta_features.setChecked(True)
w.new_recording(name='课程切换',check_models=False)
folder_a=w.current_item['folder']
folder_b=w.library.folder('Course B')['id']
path_b,course_b=course_for_folder(w.library,folder_b,create=True)
w.open_knowledge();p=w.knowledge_panel
wait(lambda:bool(p.view))
course_a=p.view['course']['id']
p.append_term({'canonical':'Course A original','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
p.save_terms()
wait(lambda:p.view['manifest']['asr_context'].get('terms')==['Course A original'])
p.terms.item(0,1).setText('Course A unsaved edit')
assert p.terms_dirty
p.courses.setCurrentIndex(p.courses.findData(folder_b));p.associate()
wait(lambda:p.view['course']['id']==course_b['id'])
assert p.terms.rowCount()==0
p.append_term({'canonical':'Course B own term','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
p.save_terms()
wait(lambda:p.view['manifest']['asr_context'].get('terms')==['Course B own term'])
assert read_json(path_b)['terms'][0]['canonical']=='Course B own term'
p.courses.setCurrentIndex(p.courses.findData(folder_a));p.associate()
wait(lambda:p.view['course']['id']==course_a)
assert p.terms.item(0,1).text()=='Course A unsaved edit' and p.terms_dirty
p.save_terms();wait(lambda:not p.terms_dirty)
assert read_json(path_b)['terms'][0]['canonical']=='Course B own term'
w.close()
''',tmp_path)


@pytest.mark.p0
def test_course_draft_survives_navigation_failure_and_exit_cancel(tmp_path):
    run_ui('''
from unittest.mock import patch
from linguaflow.knowledge.session import read_manifest
w.beta_features.setChecked(True)
w.new_recording(name='术语草稿',check_models=False)
identifier=w.current_item['id']
w.open_knowledge();p=w.knowledge_panel
wait(lambda:bool(p.view))
course=p.terms_course_id
p.append_term({'canonical':'unsaved term','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
assert w.new_recording(check_models=False)
wait(lambda:not w.knowledge_client.closing)
assert p.term_drafts[course][0]['canonical']=='unsaved term'
w.show()
with patch.object(module.QMessageBox,'question',return_value=module.QMessageBox.StandardButton.Cancel):
    assert not w.close()
assert p.has_unsaved_terms()
w.open_library_item(w.library_rows[identifier],0)
w.open_knowledge();wait(lambda:bool(p.view))
assert p.terms_dirty and p.terms.item(0,1).text()=='unsaved term'
assert not p.view['course']['terms']
p.receive({'type':'error','message':'术语保存失败，请检查目录权限。','busy':False})
assert p.terms_dirty and '目录权限' in w.notifications.notices['knowledge'].text
p.save_terms();wait(lambda:not p.terms_dirty)
assert not p.has_unsaved_terms()
assert read_manifest(w.library,identifier)['asr_context']['terms']==['unsaved term']
wait(lambda:p.view['manifest']['asr_context'].get('terms')==['unsaved term'])
w.close()
''',tmp_path)


@pytest.mark.p0
def test_active_term_editor_commits_before_recording_navigation(tmp_path):
    run_ui('''
from PySide6.QtWidgets import QLineEdit
from PySide6.QtTest import QTest
from unittest.mock import patch
w.beta_features.setChecked(True);w.new_recording(name='编辑中的术语',check_models=False)
identifier=w.current_item['id'];w.open_knowledge();p=w.knowledge_panel
wait(lambda:bool(p.view));course=p.terms_course_id
p.append_term({'canonical':'original','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
p.save_terms();wait(lambda:not p.terms_dirty)
p.tabs.setCurrentIndex(1);p.show();settle_geometry(p)
p.terms.editItem(p.terms.item(0,1));editor=p.terms.findChild(QLineEdit)
assert editor is not None
editor.selectAll();QTest.keyClicks(editor,'still editing')
with patch.object(w.native_updater,'release_runtime') as release:
    w.try_install_update()
    release.assert_not_called()
    assert '术语' in w.notifications.notices['update'].text
w.cancel_update_install()
assert w.new_recording(check_models=False)
wait(lambda:not w.knowledge_client.closing)
assert p.term_drafts[course][0]['canonical']=='still editing'
with patch.object(module.QMessageBox,'question',return_value=module.QMessageBox.StandardButton.Discard):
    w.close()
''',tmp_path)


@pytest.mark.p2
def test_history_stays_readable_during_live_updates_and_deleted_rows_refill(tmp_path):
    run_ui('''
from dataclasses import replace
from linguaflow.core import Caption
w.new_recording(name='持续更新',check_models=False)
for i in range(1,301):w.on_caption(Caption(i*3,i,i+1,f'Words {i}','en'))
w.show();settle_geometry(w)
w.locate_caption(w.current_item['id'],3);settle_geometry(w)
first=min(w.cards)
for i in range(301,306):w.on_caption(Caption(i*3,i,i+1,f'Words {i}','en'))
settle_geometry(w)
assert min(w.cards)==first and len(w.cards)==200
w.on_caption(replace(w.captions[3],source='',revision=2));settle_geometry(w)
assert 3 not in w.cards and len(w.cards)==200
w.locate_caption(w.current_item['id'],915);settle_geometry(w)
start=min(w.cards)
w.on_caption(Caption(918,306,307,'New words at the end','en'));settle_geometry(w)
assert min(w.cards)==start and 918 not in w.cards
w.scroll.latest_button.click();settle_geometry(w)
assert 918 in w.cards and len(w.cards)==200
w.close()
''',tmp_path)


@pytest.mark.p0
def test_backup_cancel_failure_and_explicit_close_preserve_original(tmp_path):
    run_ui('''
from unittest.mock import patch
import subprocess,sys
from linguaflow.core import Caption
from linguaflow.library_access import acquire_recording_lock
w.new_recording(name='故障恢复',check_models=False)
w.on_caption(Caption(1,0,2,'Draft recovery words','en',final=False))
directory=w.library.directory(w.current_item['id'])
original=(directory/'session.json').read_bytes()
w.recording_lock=acquire_recording_lock(directory)
real_save=w.library.save
def fail(*args):raise OSError('disk full')
w.library.save=fail
assert not w.persist_session('incomplete')
# A separate process must be denied until recovery is explicitly accepted.
code="from pathlib import Path; from linguaflow.library_access import acquire_recording_lock; acquire_recording_lock(Path(sys.argv[1]))"
r=subprocess.run([sys.executable,'-c','import sys;'+code,str(directory)],capture_output=True,
                 text=True,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
assert r.returncode!=0 and '另一个窗口' in r.stderr,(r.returncode,r.stderr)
with patch.object(module.QFileDialog,'getSaveFileName',return_value=('','')):
    w.backup_recording_text()
assert w.session_dirty and not w.export_saver.busy
bad=directory/'missing'/'恢复.txt'
with patch.object(module.QFileDialog,'getSaveFileName',return_value=(str(bad),'')):
    w.backup_recording_text()
wait(lambda:not w.export_saver.busy)
assert w.recovery_snapshot is None and w.session_dirty and w.recording_lock is not None
assert (directory/'session.json').read_bytes()==original
w.notifications.clear('operation')
target=Path(os.environ['AGENTSCRIBE_LIBRARY'])/'恢复.txt'
with patch.object(module.QFileDialog,'getSaveFileName',return_value=(str(target),'')):
    w.backup_recording_text()
wait(lambda:not w.export_saver.busy)
assert w.finish_recovery_action.isEnabled()
assert '备份已保存' in w.notifications.notices['save'].text
snapshot=w.recovery_snapshot
with patch.object(module.QMessageBox,'question',return_value=module.QMessageBox.StandardButton.Cancel):
    w.finish_text_recovery(snapshot)
assert w.current_item and w.recording_lock is not None
w.on_caption(Caption(2,2,3,'New words after backup','en',final=False))
with patch.object(module.QMessageBox,'question') as question:
    w.finish_text_recovery(snapshot)
    question.assert_not_called()
assert w.session_dirty and w.recording_lock is not None
with patch.object(module.QFileDialog,'getSaveFileName',return_value=(str(target),'')):
    w.backup_recording_text()
wait(lambda:not w.export_saver.busy)
snapshot=w.recovery_snapshot
def changed_while_confirming(*args):
    w.on_caption(Caption(3,3,4,'Words arriving during confirmation','en',final=False))
    return module.QMessageBox.StandardButton.Yes
with patch.object(module.QMessageBox,'question',side_effect=changed_while_confirming):
    w.finish_text_recovery(snapshot)
assert w.current_item and w.recording_lock is not None
with patch.object(module.QFileDialog,'getSaveFileName',return_value=(str(target),'')):
    w.backup_recording_text()
wait(lambda:not w.export_saver.busy)
snapshot=w.recovery_snapshot
with patch.object(module.QMessageBox,'question',return_value=module.QMessageBox.StandardButton.Yes):
    w.finish_text_recovery(snapshot)
assert w.current_item is None and w.recording_lock is None
assert (directory/'session.json').read_bytes()==original and 'Draft recovery words' in target.read_text(encoding='utf-8-sig')
w.library.save=real_save
w.close()
''',tmp_path)


@pytest.mark.p0
def test_old_terms_acknowledgement_does_not_clear_new_edits(tmp_path):
    run_ui('''
from PySide6.QtCore import QObject,Signal
from linguaflow.knowledge.panel import KnowledgePanel
from linguaflow.knowledge.schemas import fingerprint
class Client(QObject):
    changed=Signal(dict)
    connected=True
    closing=False
    def send(self,*args,**kwargs):return False
p=KnowledgePanel(Client(),lambda:None,lambda:True)
p.receive({'type':'view','manifest':{'notes_cloud':False,'asr_context':{}},
 'course':{'id':'a','documents':[],'terms':[]},'blocks':[],'sources':{},'notes':[],
 'pending':[],'event_seq':0,'notes_version':0,'reading_coverage':{},'busy':False})
p.append_term({'canonical':'original term','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
old=p.term_rows();p.save_terms()
assert p.terms_dirty
p.terms.item(0,1).setText('newer edit')
p.receive({'type':'terms_saved','course_id':'a','terms_version':fingerprint(old)})
assert p.terms_dirty and p.terms.item(0,1).text()=='newer edit'
p.receive({'type':'terms_saved','course_id':'b','terms_version':fingerprint(p.term_rows())})
assert p.terms_dirty
p.close();w.close()
''',tmp_path)


@pytest.mark.p1
def test_queued_backups_to_different_files_are_all_written(tmp_path):
    run_ui('''
from threading import Event
from unittest.mock import patch
from linguaflow.core import Caption
import linguaflow.recording_export as exports
w.new_recording(name='连续备份',check_models=False)
w.on_caption(Caption(1,0,1,'Complete backup words','en',final=False))
entered,release=Event(),Event()
original=exports._write_text
paths=[Path(os.environ['AGENTSCRIBE_LIBRARY'])/f'backup-{i}.txt' for i in range(3)]
def held_write(path,text):
    if path==paths[0]:
        entered.set()
        assert release.wait(5)
    original(path,text)
with patch.object(exports,'_write_text',side_effect=held_write):
    try:
        for path in paths:
            with patch.object(module.QFileDialog,'getSaveFileName',return_value=(str(path),'')):
                w.backup_recording_text()
            if path==paths[0]:assert entered.wait(2)
    finally:
        release.set()
    wait(lambda:not w.export_saver.busy)
assert all('Complete backup words' in p.read_text(encoding='utf-8-sig') for p in paths)
w.close()
''',tmp_path)


@pytest.mark.p2
def test_cross_page_variable_heights(tmp_path):
    run_ui('''
from linguaflow.core import Caption
w.new_recording(name='不同长度的字幕',check_models=False)
item=w.current_item
captions=[Caption(i,i,i+1,('Long text. '*180 if i<=200 else 'Short text.'),'en') for i in range(1,451)]
w.library.save(item,captions,'complete');w.refresh_library()
w.open_library_item(w.library_rows[item['id']],0)
w.show();w.resize(640,480);settle_geometry(w)
w.scroll.set_playback(True)
w.locate_caption(item['id'],150)
card=w.cards[150];bar=w.scroll.verticalScrollBar()
# Search completion is the target card entering the viewport, not the size hint
# of a window containing 200 wrapping labels becoming quiet.
wait(lambda:bar.value()<=card.y()<bar.value()+w.scroll.viewport().height(),timeout=2)
assert bar.value() <= card.y() < bar.value()+w.scroll.viewport().height(),(bar.value(),card.y(),bar.maximum())
w.close()
''',tmp_path)
