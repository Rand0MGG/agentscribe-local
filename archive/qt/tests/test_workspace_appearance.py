"""Real download progress and cleanup across settings navigation, without audio."""
import pytest


@pytest.mark.p1
def test_streamed_http_download_progress_stays_live_across_settings(tmp_path):
    from ui_support import run_ui
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
