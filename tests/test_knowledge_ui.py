"""Real Qt/process/file roundtrip without model, network, credentials or audio devices."""
import os
import subprocess
import sys


def test_course_panel_context_save_source_sync_and_owned_process_cleanup(tmp_path):
    code = '''
import os, time
from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.core import Caption
from linguaflow.knowledge.files import read_json
from linguaflow.knowledge.session import manifest_path
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
assert w.new_recording(name='课程笔记')
original = Caption(1,0,1,'Use gradient descent.','en')
w.on_caption(original)
assert w.persist_session()
w.open_knowledge()
p = w.knowledge_panel
def wait(predicate):
    deadline=time.monotonic()+10
    while not predicate() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.02)
    assert predicate(), p.status.text()
wait(lambda: bool(p.view))
assert p.view['sources']['caption:1']['saved']
assert not p.material_cloud.isChecked() and not p.notes_cloud.isChecked()
p.command('import',path=os.environ['AGENTSCRIBE_TEST_MATERIAL'])
wait(lambda: len(p.view.get('blocks',[]))==2)
p.append_term({'canonical':'gradient descent','aliases':[],'approved':True,'origin':'manual','evidence_ids':[]})
p.save_terms()
wait(lambda: p.view['manifest']['asr_context'].get('text')=='Course terminology: gradient descent')
assert read_json(manifest_path(w.library,w.current_item['id']))['asr_context']['terms']==['gradient descent']
# A source update reaches the child, but is ineligible until this exact version is saved.
w.on_caption(Caption(1,0,1,'Use stochastic gradient descent.','en',revision=2))
w.knowledge_client.send('view')
wait(lambda: p.view['sources']['caption:1']['text']=='Use stochastic gradient descent.')
assert not p.view['sources']['caption:1']['saved']
assert w.persist_session()
wait(lambda: p.view['sources']['caption:1']['saved'])
p.receive({'type':'answer','answer':'离线回答示例','refs':[{'id':'caption:1','quote':'gradient descent'}],
           'sources':p.view['sources'],'event_seq':p.view['event_seq'],'notes_version':p.view['notes_version']})
p.receive({'type':'view',**p.view})
assert '离线回答示例' in p.note_text.toPlainText()
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
    p.show();p.tabs.setCurrentIndex(1);app.processEvents();p.grab().save(str(output/'course-terms.png'))
    p.tabs.setCurrentIndex(0);app.processEvents();p.grab().save(str(output/'course-materials.png'))
    p.tabs.setCurrentIndex(2);app.processEvents();p.grab().save(str(output/'course-notes.png'))
    p.resize(640,540);app.processEvents();p.grab().save(str(output/'course-compact.png'))
    p.resize(860,680)
# Freeze at start; no audio/model runner is launched by this test.
import linguaflow.model_cache as cache
cache.resolve_qwen_cached=lambda value: Path(os.environ['AGENTSCRIBE_LIBRARY'])
w.model_manager.backend.setCurrentIndex(w.model_manager.backend.findData('qwen3-streaming'))
w.source.setCurrentIndex(next(i for i in range(w.source.count()) if w.source.itemData(i)[0]=='en'))
w.device.addItem('模拟设备',('test',False))
w.translate.setChecked(False)
captured=[]
w.launch_session=lambda settings: captured.append(settings)
w.start()
assert captured and list(captured[0].asr_context['terms'])==['gradient descent']
assert not p.save_terms_button.isEnabled()
assert 'soundcard' not in sys.modules and 'PySide6.QtMultimedia' not in sys.modules
from linguaflow.recording_state import RecordingState
w.set_recording_state(RecordingState.IDLE)
process=w.knowledge_client.process
epoch=w.knowledge_client.epoch
assert w.can_edit_library()
assert process.poll() is not None and not w.knowledge_client.threads
before=p.status.text()
w.knowledge_client._deliver(epoch,{'type':'error','message':'late message','busy':False})
assert p.status.text()==before
w.close()
'''
    from test_knowledge import pptx
    material = tmp_path / '课堂课件.pptx'
    pptx(material)
    result = subprocess.run([sys.executable, '-c', 'import sys\n' + code], capture_output=True, text=True,
        timeout=35, env={**os.environ, 'QT_QPA_PLATFORM': os.environ.get('AGENTSCRIBE_UI_PLATFORM', 'offscreen'),
                         'AGENTSCRIBE_LIBRARY': str(tmp_path), 'AGENTSCRIBE_TEST_MATERIAL': str(material)})
    assert result.returncode == 0, result.stdout + result.stderr
