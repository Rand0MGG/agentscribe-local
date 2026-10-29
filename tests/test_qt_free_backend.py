"""Production backend must operate with Qt imports rejected, not merely unused UI."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from linguaflow.events import Dispatcher, Owner, Signal, Timer, Worker
from linguaflow.file_lock import FileLock
from linguaflow.settings_store import SettingsStore


@pytest.mark.p1
def test_backend_bootstrap_settings_library_and_exit_without_qt(tmp_path):
    program = r'''
import importlib.abc, json, sys, time
from pathlib import Path
class RejectQt(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.startswith(('PySide6','shiboken6')): raise AssertionError('Qt import: '+fullname)
sys.meta_path.insert(0,RejectQt())
from linguaflow.events import Dispatcher
from linguaflow.settings_store import SettingsStore
from linguaflow.desktop_service import DesktopService
app=Dispatcher();root=Path(sys.argv[1])
s=DesktopService(library_root=root/'library',prefs=SettingsStore(root/'preferences.json',1),no_audio=True)
events=[];s.output.connect(events.append)
assert s.bootstrap()['no_audio']
s.prefs.setValue('target','简体中文');assert s.prefs.status()==0
s.close();deadline=time.monotonic()+10
while not any(e.get('event')=='closed' for e in events):
 app.process(.01)
 assert time.monotonic()<deadline
assert not any(n.startswith(('PySide6','shiboken6')) for n in sys.modules)
print('qt-free')
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)], capture_output=True,
                            text=True, timeout=20, env={**os.environ, 'AGENTSCRIBE_LOG_DIR': str(tmp_path/'logs')})
    assert result.returncode == 0, result.stderr
    assert 'qt-free' in result.stdout


@pytest.mark.p1
def test_worker_results_are_ordered_on_owner_and_disposed_callbacks_cancel():
    app = Dispatcher()
    calls = []
    class Task(Worker):
        result = Signal(int)
        def run(self):
            for value in range(3):
                self.result.emit(value)
    parent = Owner()
    worker = Task(parent)
    worker.result.connect(lambda value: calls.append((value, threading.get_ident())))
    worker.start()
    assert worker.wait(1000)
    assert calls == []
    app.process()
    assert calls == [(value, app.owner) for value in range(3)]
    timer = Timer(parent)
    timer.timeout.connect(lambda: calls.append('unexpected'))
    timer.start(1)
    timer.dispose()
    worker.dispose()
    assert parent.children == []
    app.process(.02)
    assert len(calls) == 3


@pytest.mark.p0
def test_preferences_migrate_and_merge_without_replacing_old_file(tmp_path):
    old = tmp_path/'prefs.ini'
    old.write_text('[General]\ntarget=简体中文\ntranslate=false\ngeometry=@ByteArray(\\x1\\x2\\0)\npath=C:\\\\recordings\\\\课程\n', encoding='utf-8')
    original = old.read_bytes()
    one = SettingsStore(old, 1)
    two = SettingsStore(old, 1)
    assert one.value('geometry') == b'\x01\x02\x00'
    assert one.value('translate', type=bool) is False
    assert one.value('path') == 'C:\\recordings\\课程'
    one.setValue('target', 'English')
    one.setValue('new', 1)
    two.setValue('other', 2)
    fresh = SettingsStore(old, 1)
    assert fresh.value('new') == 1 and fresh.value('other') == 2
    assert fresh.value('target') == 'English' and old.read_bytes() == original
    fresh.remove('target')
    assert not SettingsStore(old, 1).contains('target')


@pytest.mark.p0
def test_failed_preference_commit_retains_original_and_pending_changes(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path/'settings.json', 1)
    settings.setValue('saved', 1)
    before = settings.path.read_bytes()
    replace = os.replace
    monkeypatch.setattr(os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('full disk')))
    settings.setValue('saved', 2)
    assert settings.status() == SettingsStore.Status.AccessError
    assert settings.path.read_bytes() == before
    monkeypatch.setattr(os, 'replace', replace)
    settings.sync()
    assert SettingsStore(settings.path, 1).value('saved') == 2


@pytest.mark.p0
def test_live_legacy_lock_and_concurrent_stale_reclaim(tmp_path):
    import socket
    lock_path = tmp_path/'.recording.lock'
    lock_path.write_text(f'{os.getpid()}\npython\n{socket.gethostname()}\n')
    assert not FileLock(lock_path).tryLock()
    lock_path.write_text(f'999999999\npython\n{socket.gethostname()}\n')
    program = '''
import sys,time
from pathlib import Path
from linguaflow.file_lock import FileLock
lock=FileLock(sys.argv[1])
if lock.tryLock(1000):
 path=Path(sys.argv[2])
 with path.open('x'): time.sleep(.03)
 path.unlink();lock.unlock()
else: raise RuntimeError('lock timeout')
'''
    jobs = [subprocess.Popen([sys.executable, '-c', program, str(lock_path), str(tmp_path/'owned')],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(6)]
    for job in jobs:
        _, error = job.communicate(timeout=5)
        assert job.returncode == 0, error
    assert not lock_path.exists()


@pytest.mark.p2
def test_packaged_source_inventory_excludes_all_qt_imports():
    import ast

    from scripts.packaging_common import LEGACY_QT_FILES
    root = Path(__file__).resolve().parents[1]
    found = []
    for path in (root/'linguaflow').rglob('*.py'):
        if path.relative_to(root).as_posix() in LEGACY_QT_FILES:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                found.extend((path, x.name) for x in node.names if x.name.startswith(('PySide6', 'shiboken6')))
            elif isinstance(node, ast.ImportFrom) and (node.module or '').startswith(('PySide6', 'shiboken6')):
                found.append((path,node.module))
    assert not found
    for platform in ('macos','windows'):
        lock = (root/'packaging'/platform/'desktop.lock').read_text().lower()
        assert 'pyside6' not in lock and 'shiboken6' not in lock
    assert 'marked' in json.loads((root/'desktop/package.json').read_text())['dependencies']


@pytest.mark.p1
def test_native_cocoa_dispatches_timer_without_qt(tmp_path):
    import pytest
    if sys.platform != 'darwin':
        pytest.skip('Cocoa owner event loop is macOS only')
    source = '''
import sys
from linguaflow.events import Dispatcher
from linguaflow.native_dispatch import cocoa_pump
from Foundation import NSTimer
app=Dispatcher();app.native_pump=cocoa_pump();fired=[]
def completed(_):
 fired.append(True);app.quit()
timer=NSTimer.scheduledTimerWithTimeInterval_repeats_block_(.02,False,completed)
app.exec()
assert fired == [True]
assert not any(n.startswith('PySide6') for n in sys.modules)
'''
    result = subprocess.run([sys.executable,'-c',source],capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.p2
def test_legacy_windows_registry_geometry_codec_preserves_embedded_nuls():
    geometry = bytes.fromhex('01d9d0cb00030000') + bytes(40)
    registry = ('@ByteArray(' + geometry.decode('latin1') + ')').encode('utf-16-le')
    assert SettingsStore._qt_value(registry.decode('utf-16-le')) == geometry
    assert SettingsStore._qt_value('@@plain') == '@plain'
    assert SettingsStore._qt_value('@String(a\0b)') == 'a\0b'


@pytest.mark.p1
def test_qt_free_native_update_probe_uses_real_backend(tmp_path):
    from scripts.update_probe_host import HOST_IMPORTS
    program = 'import sys\n' + HOST_IMPORTS + '''
from pathlib import Path
root=Path(sys.argv[1]);app=QApplication([])
prefs=QSettings(root/'prefs.json',1)
w=Window(discover=False,prefs=prefs,library_root=root/'library')
from linguaflow.recording_state import RecordingState
w.set_recording_state(RecordingState.LISTENING)
assert w.update_activity_snapshot().recording
w.set_recording_state(RecordingState.IDLE)
assert not w.update_activity_snapshot().recording
w.close();app.exec()
assert not any(n.startswith('PySide6') for n in sys.modules)
'''
    result = subprocess.run([sys.executable,'-c',program,str(tmp_path)],capture_output=True,text=True,timeout=15,
                            env={**os.environ,'AGENTSCRIBE_LOG_DIR':str(tmp_path/'logs')})
    assert result.returncode == 0, result.stderr
