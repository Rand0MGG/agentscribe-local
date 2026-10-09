"""Real Qt/process/file roundtrip without model, network, credentials or audio devices."""
import os
import subprocess
import sys


def test_missing_agent_sdk_corrupt_course_and_worker_exit_leave_local_recording_usable(tmp_path):
    code = '''
import importlib.abc, os, subprocess, sys, time
from threading import Event
class NoCloudSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'deepagents','langchain','langchain_core','langchain_deepseek','langgraph','openai','httpx','keyring'}:
            raise AssertionError('Cloud SDK entered the desktop: '+fullname)
sys.meta_path.insert(0, NoCloudSDK())
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication
import linguaflow.app as module
from linguaflow.core import Caption
from linguaflow.knowledge.session import manifest_path
class FakeSession(QObject):
    status=Signal(str);stage=Signal(str,str);ready=Signal();paused=Signal(bool)
    caption=Signal(object);level=Signal(float);failure=Signal(str);finished=Signal()
    def __init__(self, settings, parent, recording_path, runtime=None):
        super().__init__(parent)
        self.settings=settings;self.model_ready=Event()
    def start(self):
        self.model_ready.set();self.ready.emit()
    def stop(self): self.finished.emit()
module.Session=FakeSession
app=QApplication([])
w=module.Window(discover=False,prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini',QSettings.Format.IniFormat))
w.device.addItem('fixture',('fixture',False));w.translate.setChecked(False)
w.model_manager.backend.setCurrentIndex(0)
assert w.new_recording(name='后台失败仍可录音')
path=manifest_path(w.library,w.current_item['id'])
path.parent.mkdir(parents=True,exist_ok=True);path.write_text('broken JSON',encoding='utf-8')
def forbidden_context(*args): raise AssertionError('Whisper must not compile Qwen context')
module.session_context=forbidden_context
w.start()
assert w.session is not None and w.recording_state.active
real_spawn=subprocess.Popen
def crashing_worker(command,**kwargs):
    if 'linguaflow.knowledge.worker' in command:
        return real_spawn([sys.executable,'-c','import sys;sys.exit(3)'],**kwargs)
    return real_spawn(command,**kwargs)
subprocess.Popen=crashing_worker
w.knowledge_client.open(w.library,w.current_item,[])
process=w.knowledge_client.process
deadline=time.monotonic()+5
while process.poll() is None and time.monotonic()<deadline:
    app.processEvents();time.sleep(.01)
assert process.poll()==3 and w.recording_state.active and w.session is not None
caption=Caption(1,0,1,'Preserved source','en','保留译文')
w.session.caption.emit(caption)
assert w.persist_session()
w.stop();app.processEvents()
assert w.session is None and w.current_item['state']=='complete'
saved=w.library.load(w.current_item)[1]
assert saved[0].source==caption.source and saved[0].translation==caption.translation
assert not {'soundcard','PySide6.QtMultimedia'} & sys.modules.keys()
assert not any(name.startswith(('linguaflow.knowledge.worker','linguaflow.knowledge.api','linguaflow.knowledge.harness')) for name in sys.modules)
w.close();app.processEvents()
assert not w.knowledge_client.threads
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30,
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr


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


def test_visual_page_panel_coverage_provenance_and_window_sizes(tmp_path):
    from dataclasses import asdict

    from test_knowledge_visual import fake_pages, reading, setup_course

    from linguaflow.knowledge.materials import course_for_folder, read_blocks
    from linguaflow.knowledge.readings import save_reading, visual_blocks
    library, item, document = setup_course(tmp_path)
    path, course = course_for_folder(library, item['folder'])
    native = read_blocks(library, path, course)
    images = fake_pages(library, path, document, len(native))['images']
    for block, image in zip(native, images):
        save_reading(library, path, block, image['sha256'], reading(block))
    visual, coverage = visual_blocks(library, path, native, course['documents'])
    value = {'type': 'view', 'manifest': {'notes_cloud': False, 'asr_context': {}}, 'course': course,
             'blocks': [asdict(row) for row in native + visual], 'sources': {}, 'notes': [], 'pending': [],
             'event_seq': 0, 'notes_version': 0, 'reading_coverage': coverage, 'busy': False}
    data = tmp_path / 'view.json'
    import json
    data.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    code = '''
import json, os
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from linguaflow.knowledge.panel import KnowledgePanel
class Client(QObject):
 changed=Signal(dict)
 process=object()
 def send(self,*args,**kwargs): return True
app=QApplication([])
p=KnowledgePanel(Client(),lambda:None,lambda:True)
p.receive(json.loads(Path(os.environ['AGENTSCRIBE_VISUAL_VIEW']).read_text(encoding='utf-8')))
p.show();app.processEvents();p.pages.setCurrentIndex(1);app.processEvents()
assert p.pages.count()==3 and '视觉读取 3/3 页' in p.status.text()
assert '模型生成' in p.material_text.toPlainText() and 'A visible triangle.' in p.material_text.toPlainText()
for width,height in [(860,680),(640,540)]:
 p.resize(width,height);app.processEvents();p.show_page();app.processEvents()
 assert p.material_text.horizontalScrollBar().maximum()==0
 if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
  output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
  p.grab().save(str(output/f'course-visual-{width}.png'))
p.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
        env={**os.environ, 'QT_QPA_PLATFORM': os.environ.get('AGENTSCRIBE_UI_PLATFORM', 'offscreen'),
             'AGENTSCRIBE_VISUAL_VIEW': str(data)})
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_format_import_filter_and_local_preview_without_cloud(tmp_path):
    from test_knowledge_visual import png
    source = tmp_path / '课程图片.png'
    source.write_bytes(png(512, 288))
    code = '''
import os,time
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
app=QApplication([])
w=Window(discover=False,prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini',QSettings.Format.IniFormat))
assert w.new_recording(name='静态课件')
w.open_knowledge();p=w.knowledge_panel
def wait(predicate):
 deadline=time.monotonic()+20
 while not predicate() and time.monotonic()<deadline:
  app.processEvents();time.sleep(.02)
 assert predicate(),p.status.text()
wait(lambda:bool(p.view))
p.command('import',path=os.environ['AGENTSCRIBE_TEST_IMAGE'])
wait(lambda:len(p.view.get('blocks',[]))==1)
assert p.import_button.text()=='导入课件'
assert not p.material_cloud.isChecked() and not p.notes_cloud.isChecked()
assert '本地原页' in p.material_text.toPlainText() and '<img' in p.material_text.toHtml()
assert '视觉读取 0/1 页' in p.status.text()
import linguaflow.knowledge.panel as module
filters=[]
module.QFileDialog.getOpenFileName=lambda *args: (filters.append(args[-1]) or ('',''))
p.import_material()
assert all('*'+suffix in filters[0] for suffix in ('.doc','.ppt','.xlsx','.html','.md','.csv','.png','.bmp','.ico','.svg'))
p.show()
for width,height in [(860,680),(640,540)]:
 p.resize(width,height);app.processEvents();p.show_page();app.processEvents()
 assert p.material_text.horizontalScrollBar().maximum()==0
 if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
  output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
  p.grab().save(str(output/f'course-local-preview-{width}.png'))
process=w.knowledge_client.process
p.close();w.close();app.processEvents()
assert process.poll() is not None
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=40,
        env={**os.environ, 'QT_QPA_PLATFORM': os.environ.get('AGENTSCRIBE_UI_PLATFORM', 'offscreen'),
             'AGENTSCRIBE_LIBRARY': str(tmp_path), 'AGENTSCRIBE_TEST_IMAGE': str(source)})
    assert result.returncode == 0, result.stdout + result.stderr
