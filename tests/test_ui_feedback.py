"""Task feedback remains actionable through waits, cancellation and disconnection."""
from ui_support import run_ui


def test_migration_progress_and_cancel_remain_reachable_after_wait_and_dismissal(tmp_path):
    run_ui('''
from types import SimpleNamespace
from unittest.mock import patch
import linguaflow.notifications as feedback
w.show();settle_geometry(w)
clock=[100.]
cancelled=[]
with patch.object(feedback,'time',SimpleNamespace(monotonic=lambda:clock[0])), \
     patch.object(w.library_migration,'cancel',lambda:cancelled.append(True)):
    w.cancel_migration_action.setEnabled(True)
    w.library_migration.progress.emit(10)
    clock[0]+=60;w.library_migration.progress.emit(20)
    assert w.notifications.isVisible()
    assert w.notifications.progress.value()==20 and w.notifications.action_button.isVisible()
    w.notifications.action_button.click();assert cancelled==[True]
    w.notifications.dismiss.click()
    w.library_migration.progress.emit(21)
    assert w.notifications.isHidden() and w.cancel_migration_action.isEnabled()
    # The menu also cancels a deferred migration, including when another error
    # has priority over its notification.
    w.pending_library_path='unused-fixture'
    w.notifications.post('save','保存失败',kind='error')
    w.cancel_migration_action.trigger()
    assert w.pending_library_path is None and not w.cancel_migration_action.isEnabled()
    w.notifications.clear('save')
    w.on_library_migrated([],success=False)
    assert not w.cancel_migration_action.isEnabled()
w.close()
''', tmp_path)


def test_model_check_is_busy_cancellable_and_rejects_late_result(tmp_path):
    run_ui('''
from types import SimpleNamespace
from unittest.mock import patch
import linguaflow.notifications as feedback
w.show();settle_geometry(w)
callbacks=[]
wait(lambda:not w.background_checks)
def check(module,callback,*args):
    callbacks.append(callback)
    return object()
w.start_background_check=check
clock=[100.]
with patch.object(feedback,'time',SimpleNamespace(monotonic=lambda:clock[0])):
    w.check_models_for_action('start')
    assert not w.start_button.isEnabled() and '检查模型' in w.start_button.text(), (w.start_button.isEnabled(),w.start_button.text(),w.model_action)
    assert w.notifications.progress.isVisible(), (w.notifications.current_key,w.notifications.isVisible())
    w.check_models_for_action('start');assert len(callbacks)==1, (len(callbacks),len(w.background_checks))
    clock[0]+=60;w.notifications._refresh()
    assert w.notifications.isVisible()
    w.notifications.dismiss.click()
    assert w.cancel_model_check_action.isEnabled()
    started=[];w.start=lambda **kwargs:started.append(kwargs)
    w.cancel_model_check_action.trigger()
    assert w.start_button.isEnabled() and w.start_button.text()=='开始聆听'
    assert '已取消' in w.model_manager.status.text()
    callbacks[0]([]);assert not started
    w.check_models_for_action('start');callbacks[-1](None)
    assert w.start_button.isEnabled() and w.notifications.notices['model-check'].kind=='error'
    w.check_models_for_action('start');callbacks[-1]([])
    assert started==[{'models_checked':True}] and w.start_button.isEnabled()
    assert w.model_manager.status.text()=='所选模型已就绪。'
    w.check_models_for_action('start');callback=callbacks[-1]
    assert w.new_recording(check_models=False)
    callback([]);assert len(started)==1
    w.check_models_for_action('start');callback=callbacks[-1]
    w.close();callback([])
    assert len(started)==1 and w.model_action is None
w.close()
''', tmp_path)


def test_course_disconnect_disables_actions_and_keeps_unsaved_terms_for_reconnect(tmp_path):
    run_ui('''
from types import SimpleNamespace
from linguaflow.knowledge.panel import KnowledgePanel
p=KnowledgePanel(w.knowledge_client,lambda:None,lambda:True,w,feedback=w.notifications)
p.view={'course':{},'blocks':[]};p.terms_course_id='fixture-course'
p.append_term({'canonical':'Unsaved term','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
p.terms_dirty=True
state=[None]
w.knowledge_client.process=SimpleNamespace(poll=lambda:state[0])
try:
    p.update_controls();assert p.import_button.isEnabled()
    # The worker exits between enabling the button and dispatching its command.
    state[0]=1
    p.command('import',path='unused-fixture.pdf')
    assert not p.busy and not p.import_button.isEnabled()
    assert not p.save_terms_button.isEnabled() and not p.cancel_button.isEnabled()
    assert p.reconnect_button.isEnabled() and not p.reconnect_button.isHidden()
    assert '重新连接' in w.notifications.message.text()
    assert p.terms_dirty and p.term_rows()[0]['canonical']=='Unsaved term'
    retried=[];p.reconnectRequested.connect(lambda:retried.append(True))
    p.reconnect_button.click();assert retried==[True]
    state[0]=None;w.knowledge_client.disconnected=False
    p.update_controls()
    assert p.import_button.isEnabled() and p.reconnect_button.isHidden()
    assert p.terms_dirty and p.term_rows()[0]['canonical']=='Unsaved term'
    w.knowledge_client.epoch='new'
    w.knowledge_client._deliver('old',{'type':'disconnected','busy':False})
    assert w.knowledge_client.connected
finally:
    w.knowledge_client.process=None
p.close();w.close()
''', tmp_path)


def test_real_course_worker_exit_and_reconnect_preserve_draft(tmp_path):
    run_ui('''
from unittest.mock import patch
w.beta_features.setChecked(True)
assert w.new_recording(name='重连草稿',check_models=False)
w.open_knowledge();p=w.knowledge_panel
wait(lambda:bool(p.view))
p.append_term({'canonical':'Unsaved draft','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
assert p.terms_dirty
old=w.knowledge_client.process
old.terminate()
wait(lambda:w.knowledge_client.disconnected)
assert not p.import_button.isEnabled() and p.reconnect_button.isEnabled()
p.reconnect_button.click()
wait(lambda:w.knowledge_client.process is not old and p.import_button.isEnabled()
     and 'knowledge' not in w.notifications.notices)
assert old.poll() is not None
assert p.terms_dirty and p.term_rows()[0]['canonical']=='Unsaved draft'
with patch.object(module.QMessageBox,'question',return_value=module.QMessageBox.StandardButton.Discard):
    w.close()
''', tmp_path)
