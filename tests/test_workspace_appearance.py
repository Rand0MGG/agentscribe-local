import os
import subprocess
import sys


def test_theme_model_navigation_and_progress_survive_page_changes(tmp_path):
    code = '''
import os, time
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.recording_state import RecordingState
app = QApplication([])
prefs = QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat)
w = Window(discover=False, prefs=prefs)
w.show()
workspace, manager = w.settings_workspace, w.model_manager
assert app.property('appearance') == 'light'
assert w.appearance.currentData() == 'light'
w.appearance.setCurrentIndex(1)
assert app.property('appearance') == 'dark' and prefs.value('appearance') == 'dark'
w.appearance.setCurrentIndex(0)
browser = workspace.model_browser
reads=[]
def read_inventory(module, callback, *args):
    reads.append(module)
    callback({'models':[]})
browser.start_check=read_inventory
w.open_settings('模型管理')
assert not hasattr(workspace, 'advanced_navigation')
assert all(not workspace.navigation.item(i).isHidden() for i in range(len(workspace.categories)))
assert len(reads)==1
# Fake only the filesystem result, preserving widget and navigation behavior.
from linguaflow.model_options import asr_backends
engine = next(backend for backend in asr_backends() if backend.startswith('qwen3'))
browser.receive({'models':[dict(id='/fixture',path='/fixture/Qwen',name='Qwen 4-bit',kind='asr',engine=engine,size=100,deletable=True)]})
choice = browser.role_choices['asr']
choice.activated.emit(1)
assert manager.qwen_model.currentText() == '/fixture/Qwen'
assert choice.currentIndex() == 0
assert not hasattr(manager, 'profile')
assert browser.list.count() == 1 and browser.delete_button.isEnabled()
w.set_recording_state(RecordingState.LISTENING)
assert not browser.delete_button.isEnabled()
w.set_recording_state(RecordingState.IDLE)
browser.open_selected()
dialog = QApplication.activeModalWidget()
assert dialog is not None and dialog.windowTitle() == 'Qwen 4-bit'
assert manager.qwen_model.currentText() == '/fixture/Qwen'
dialog.accept()
dialog = workspace.open_model_settings('asr')
assert workspace.navigation.currentItem().text() == '模型管理'
assert '识别模型' not in workspace.categories and '翻译模型' not in workspace.categories
assert dialog.isVisible() and dialog.engine.currentData() == engine
dialog.reject()
assert workspace.pages.currentIndex() == workspace.mapping['模型管理']
assert manager.qwen_model.currentText() == '/fixture/Qwen'
w.open_settings('使用指南')
from threading import Event
release = Event()
def action():
    assert release.wait(3)
    return '完成'
manager.prepare(action)
assert manager.status.isVisible() and manager.download_card.isVisible()
ticks=[]
def advance():
    ticks.append(1)
    manager.show_download({'label':'x'*len(ticks)*20,'completed':len(ticks)*10,'total':100,'unit':'B'})
timer=QTimer()
timer.timeout.connect(advance)
timer.start(10)
deadline=time.monotonic()+2
while len(ticks)<3 and time.monotonic()<deadline:
    app.processEvents()
    time.sleep(.005)
dialog = workspace.open_model_settings('asr')
assert not dialog.download.isEnabled()
dialog.reject()
app.processEvents()
assert manager.progress_bar.value()>=300 and manager.status.isVisible()
width,height=manager.progress_bar.size().toTuple()
while len(ticks)<6 and time.monotonic()<deadline:
    app.processEvents()
    time.sleep(.005)
assert manager.progress_bar.value()>=600
assert manager.progress_bar.size().toTuple()==(width,height)
assert not hasattr(w, 'preparation_summary')
assert manager.download_card.parentWidget() is workspace.right
release.set()
while manager.worker is not None and time.monotonic()<deadline:
    app.processEvents()
    time.sleep(.005)
timer.stop()
assert manager.worker is None
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr


def test_streamed_http_download_progress_stays_live_across_settings(tmp_path):
    from test_beta_features import run_ui
    run_ui(r'''
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from PySide6.QtCore import QTimer
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length',str(64*65536))
        self.end_headers()
        for i in range(64):
            self.wfile.write(b'x'*65536)
            self.wfile.flush()
            time.sleep(.1)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
Thread(target=server.serve_forever,daemon=True).start()
code="import urllib.request,io; from linguaflow.download_progress import copy_download; response=urllib.request.urlopen('http://127.0.0.1:%s/weights'); copy_download(response,io.BytesIO(),'fixture weights')"%server.server_port
manager=w.model_manager
progress=[]
manager.download_changed.connect(lambda event:progress.append(event.get('completed',0)))
ticks=[]
timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10)
try:
    manager.prepare(lambda:manager.run_preparation([sys.executable,'-c',code]))
    wait(lambda:any(0<n<64*65536 for n in progress))
    assert manager.update_button.isEnabled()
    w.open_settings('常规')
    wait(lambda:len(ticks)>10)
    w.open_settings('模型管理')
    wait(lambda:manager.worker is None)
    assert len(set(progress))>=3 and max(progress)==64*65536
    assert len(ticks)>30 and manager.status.text()
    assert not manager.progress_bar.isVisible()
finally:
    timer.stop();server.shutdown();server.server_close()
    if manager.worker is not None:
        manager.cancel_preparation();wait(lambda:manager.worker is None)
    w.close();app.processEvents()
''', tmp_path)
