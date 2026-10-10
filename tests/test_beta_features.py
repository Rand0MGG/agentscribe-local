"""Beta visibility, persistent opt-in and isolation from ordinary local recording."""
import os
import subprocess
import sys
from pathlib import Path


def run_ui(code, tmp_path):
    prefix = '''
import os, time
from pathlib import Path
from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QApplication
import linguaflow.app as module
app=QApplication([])
path=Path(os.environ['AGENTSCRIBE_LIBRARY'])/'prefs.ini'
def window():
    return module.Window(discover=False,prefs=QSettings(str(path),QSettings.Format.IniFormat))
from ui_support import settle_geometry, wait_until as wait
w=window()
'''
    bootstrap = f'import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n'
    result = subprocess.run([sys.executable, '-c', bootstrap + prefix + code], capture_output=True, text=True, timeout=35,
        env={**os.environ, 'QT_QPA_PLATFORM': os.environ.get('AGENTSCRIBE_UI_PLATFORM', 'offscreen'),
             'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr


def test_beta_off_hides_entries_and_ignores_old_cloud_consent_and_qwen_context(tmp_path):
    run_ui('''
from threading import Event
from linguaflow.core import Caption
from linguaflow.knowledge.files import write_json
from linguaflow.knowledge.session import manifest_path
from PySide6.QtWidgets import QTreeWidgetItem
assert not w.beta_features.isChecked() and w.knowledge_button.isHidden()
assert w.model_manager.install_documents_button.isHidden()
assert w.new_recording(name='默认非 Beta 录音')
identifier=w.current_item['id']
manifest=manifest_path(w.library,identifier)
write_json(w.library.root,manifest,{'schema_version':1,'session_id':identifier,'course_id':'a'*32,
                                  'asr_context':{},'notes_cloud':True})
original=manifest.read_bytes()
def forbidden(*args,**kwargs): raise AssertionError('Disabled beta was invoked')
w.model_manager.prepare=forbidden
w.model_manager.install_documents()
module.read_manifest=module.session_context=forbidden
w.knowledge_client.open=forbidden
row=QTreeWidgetItem(['recording']);row.setData(0,Qt.ItemDataRole.UserRole,('session',identifier))
w.open_library_item(row,0)
w.open_knowledge();w.attach_knowledge(force=True)
assert w.knowledge_panel is None and w.knowledge_client.process is None
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
    w.show();app.processEvents();w.grab().save(str(output/'beta-off-main.png'))
    w.open_settings('常规');app.processEvents()
    for width,height in [(1200,800),(900,700)]:
        w.resize(width,height);app.processEvents()
        w.settings_workspace.pages.currentWidget().ensureWidgetVisible(w.beta_features)
        app.processEvents();w.grab().save(str(output/f'beta-settings-{width}.png'))
        assert w.settings_workspace.pages.currentWidget().horizontalScrollBar().maximum()==0
    w.leave_settings()
import linguaflow.model_cache as cache
cache.resolve_qwen_cached=lambda value: Path(os.environ['AGENTSCRIBE_LIBRARY'])
w.model_manager.backend.setCurrentIndex(w.model_manager.backend.findData('qwen3-streaming'))
w.source.setCurrentIndex(next(i for i in range(w.source.count()) if w.source.itemData(i)[0]=='en'))
w.device.addItem('fixture',('fixture',False));w.translate.setChecked(False)
class FakeSession(QObject):
    status=Signal(str);stage=Signal(str,str);ready=Signal();paused=Signal(bool)
    caption=Signal(object);level=Signal(float);source_changed=Signal(int);failure=Signal(str);finished=Signal()
    def __init__(self,settings,parent,recording_path,runtime=None):
        super().__init__(parent);self.settings=settings;self.model_ready=Event()
    def start(self): self.model_ready.set();self.ready.emit()
    def stop(self): self.finished.emit()
module.Session=FakeSession
w.start(models_checked=True)
assert w.session is not None and w.session.settings.asr_context=={}
w.session.caption.emit(Caption(1,0,1,'Local caption','en','本地译文'))
w.stop();wait(lambda:w.session is None)
assert w.library.load(w.current_item)[1][0].translation=='本地译文'
assert manifest.read_bytes()==original and w.knowledge_client.process is None
w.close();app.processEvents()
''', tmp_path)


def test_beta_toggle_persists_and_closes_owned_worker_without_deleting_course_data(tmp_path):
    run_ui('''
from linguaflow.knowledge.files import read_json
from linguaflow.knowledge.session import manifest_path
assert not w.beta_features.isChecked()
w.beta_features.setChecked(True);w.prefs.sync()
assert not w.knowledge_button.isHidden()
assert not w.model_manager.install_documents_button.isHidden()
reopened=window();assert reopened.beta_features.isChecked();reopened.close()
assert w.new_recording(name='Beta 课程')
w.open_knowledge();p=w.knowledge_panel
wait(lambda:bool(p.view))
assert 'Beta' in p.windowTitle() and not p.material_cloud.isChecked() and not p.notes_cloud.isChecked()
p.append_term({'canonical':'gradient descent','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
p.save_terms();wait(lambda:p.view['manifest']['asr_context'].get('terms')==['gradient descent'])
record_manifest=manifest_path(w.library,w.current_item['id'])
course_manifest=w.library.directory(w.current_item['folder'])/'.agentscribe/course.json'
old_record,old_course=record_manifest.read_bytes(),course_manifest.read_bytes()
process,epoch=w.knowledge_client.process,w.knowledge_client.epoch
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
    p.hide();w.show();app.processEvents();w.grab().save(str(output/'beta-on-main.png'));p.show()
w.beta_features.setChecked(False);w.prefs.sync()
assert w.knowledge_button.isHidden() and p.isHidden() and not p.view
assert w.model_manager.install_documents_button.isHidden()
assert process.poll() is not None and w.knowledge_client.process is None and not w.knowledge_client.threads
w.knowledge_client._deliver(epoch,{'type':'view','course':{'terms':[]}})
assert not p.view
w.open_knowledge();w.attach_knowledge(force=True)
assert w.knowledge_client.process is None
assert record_manifest.read_bytes()==old_record and course_manifest.read_bytes()==old_course
assert read_json(course_manifest)['terms'][0]['canonical']=='gradient descent'
w.close()
reopened=window();assert not reopened.beta_features.isChecked() and reopened.knowledge_button.isHidden()
reopened.close();app.processEvents()
''', tmp_path)


def test_disabling_beta_cancels_only_course_component_preparation(tmp_path):
    run_ui('''
from threading import Event
w.beta_features.setChecked(True)
started,finish=Event(),Event()
def install(command,**kwargs):
    assert command[-1]=='linguaflow.document_install'
    started.set()
    assert finish.wait(8)
    return 'done'
w.model_manager.run_preparation=install
w.model_manager.install_documents()
try:
    wait(started.is_set)
    worker=w.model_manager.worker
    assert worker.beta_only and not worker.affects_runtime
    w.beta_features.setChecked(False)
    assert worker.cancelled and w.model_manager.install_documents_button.isHidden()
finally:
    finish.set();wait(lambda:w.model_manager.worker is None)
    w.close();app.processEvents()
''', tmp_path)


def test_knowledge_close_reaps_exited_child_with_buffered_input(tmp_path):
    run_ui('''
import subprocess,sys
from linguaflow.knowledge.client import KnowledgeClient
client=KnowledgeClient()
process=subprocess.Popen([sys.executable,'-c','pass'],stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE,text=True,encoding='utf-8')
client.process=process
process.stdin.write('unflushed command')
process.wait(timeout=8)
client.close();client.close()
assert process.stdin.closed and process.stdout.closed
assert client.process is None and not client.threads
w.close();app.processEvents()
''', tmp_path)
