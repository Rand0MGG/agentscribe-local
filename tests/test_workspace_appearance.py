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
import faulthandler
faulthandler.dump_traceback_later(25)
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from threading import Event, Thread
from unittest.mock import patch
from PySide6.QtCore import QTimer
release = Event()
request_done = Event()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        self.connection.settimeout(5)
        try:
            self.send_response(200)
            self.send_header('Content-Length',str(64*65536))
            self.end_headers()
            for i in range(64):
                self.wfile.write(b'x'*65536)
                self.wfile.flush()
                if i == 15:
                    # Keep the actual downloader alive until UI navigation has
                    # been exercised, independent of machine/download speed.
                    assert release.wait(10), 'UI did not release the HTTP fixture'
        finally:
            request_done.set()
class FixtureServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer's getfqdn('127.0.0.1') blocks in the Mac CI resolver.
        # This loopback fixture never serves by hostname or needs reverse DNS.
        TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]
with patch('socket.getfqdn', side_effect=AssertionError('loopback fixture must not use DNS')):
    server=FixtureServer(('127.0.0.1',0),Handler)
server_thread=Thread(target=server.serve_forever,daemon=True)
server_thread.start()
# Local fixtures must bypass host proxy settings; application network choices
# are unchanged. Bound the socket so failures cannot hang server cleanup.
code="import urllib.request,io; from linguaflow.download_progress import copy_download; opener=urllib.request.build_opener(urllib.request.ProxyHandler({})); response=opener.open('http://127.0.0.1:%s/weights',timeout=5); copy_download(response,io.BytesIO(),'fixture weights')"%server.server_port
manager=w.model_manager
progress=[]
manager.download_changed.connect(lambda event:progress.append(event.get('completed',0)))
ticks=[]
timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10)
try:
    manager.prepare(lambda:manager.run_preparation([sys.executable,'-c',code]))
    wait(lambda:any(0<n<64*65536 for n in progress) or manager.worker is None)
    assert any(0<n<64*65536 for n in progress), manager.status.toolTip()
    assert manager.update_button.isEnabled()
    w.open_settings('常规')
    wait(lambda:len(ticks)>30)
    assert manager.worker is not None and max(progress)<64*65536
    w.open_settings('模型管理')
    release.set()
    wait(lambda:manager.worker is None)
    assert len(set(progress))>=3 and max(progress)==64*65536
    assert request_done.is_set()
    assert len(ticks)>30 and manager.status.text()
    assert not manager.progress_bar.isVisible()
finally:
    timer.stop()
    release.set()
    if manager.worker is not None:
        manager.cancel_preparation();wait(lambda:manager.worker is None)
    server.shutdown();server.server_close()
    server_thread.join(5)
    assert not server_thread.is_alive()
    w.close();app.processEvents()
    faulthandler.cancel_dump_traceback_later()
''', tmp_path)
