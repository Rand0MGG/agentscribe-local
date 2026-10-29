"""Real isolated transport failures; no course SDK, cloud or audio required."""
import os
import subprocess
import sys

import pytest


@pytest.mark.p1
@pytest.mark.parametrize('launcher_exits', [False, True])
@pytest.mark.parametrize('operation', ['close', 'cancel_import'])
def test_close_reaps_descendant_holding_transport(tmp_path, launcher_exits, operation):
    child = tmp_path / 'course_worker.py'
    child.write_text('''import subprocess, sys, time, json, os
from pathlib import Path
p = subprocess.Popen([sys._base_executable, '-c', 'import time; time.sleep(60)'])
Path(__file__).with_suffix('.pid').write_text(str(p.pid))
print(json.dumps({'type': 'view'}), flush=True)
''' + ("while not Path(__file__).with_suffix('.exit').exists(): time.sleep(.01)\nos._exit(0)"
       if launcher_exits else 'time.sleep(60)'), encoding='utf-8')
    code = '''
import sys, time
from pathlib import Path
from types import SimpleNamespace
import psutil
from linguaflow.events import Dispatcher as QCoreApplication
import linguaflow.knowledge.client as module
app = QCoreApplication([])
client = module.KnowledgeClient()
original = module.subprocess.Popen
def spawn(command, **options):
    command[-1] = sys.argv[1]
    # Old direct entry and new ownership bootstrap both execute the same helper.
    if command[-2] == '-m':
        command.pop(-2)
    return original(command, **options)
module.subprocess.Popen = spawn
module.knowledge_python = lambda: Path(sys.executable)
client.open(SimpleNamespace(root=Path(sys.argv[1]).parent), {'id':'test', 'folder':'inbox'})
process = client.process
pid_file = Path(sys.argv[1]).with_suffix('.pid')
deadline = time.monotonic() + 8
while not pid_file.exists():
    app.process()
    assert time.monotonic() < deadline
    time.sleep(.01)
descendant = psutil.Process(int(pid_file.read_text()))
try:
    if sys.argv[2] == 'True':
        Path(sys.argv[1]).with_suffix('.exit').touch()
        process.wait(timeout=8)
    if sys.argv[3] == 'cancel_import':
        from linguaflow.knowledge.lifecycle import cancel_task
        assert cancel_task(client, 'import')
    else:
        assert client.close(), client.close_error or 'course cleanup remained blocked'
    descendant.wait(timeout=3)
    assert process.poll() is not None and not client.threads
    assert process.stdin.closed and process.stdout.closed
    assert client.close()
finally:
    if descendant.is_running():
        descendant.kill()
        descendant.wait(timeout=5)
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
    deadline = time.monotonic() + 5
    while client.closing and time.monotonic() < deadline:
        app.process()
        time.sleep(.01)
'''
    result = subprocess.run([sys.executable, '-c', code, str(child), str(launcher_exits), operation],
                            capture_output=True, text=True, encoding='utf-8', timeout=30,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.p1
def test_failed_cleanup_retains_threads_and_allows_retry():
    code = '''
from threading import Thread, Event
from types import SimpleNamespace
from linguaflow.events import Dispatcher as QCoreApplication
import linguaflow.knowledge.client as module
app = QCoreApplication([])
client = module.KnowledgeClient()
release = Event()
reader = Thread(target=lambda: release.wait(10))
reader.start()
process = SimpleNamespace(poll=lambda: 0)
client.process, client.threads = process, [reader]
closed = []
import linguaflow.process_platform as platform
platform.stop_tree = lambda *a, **kw: None
platform.close_process_pipes = lambda p: closed.append(p)
try:
    assert not client.close()
    assert client.close_error and not client.closing
    assert client.process is process and client.threads == [reader]
    assert not client.connected
    assert not closed, 'a live reader must never have its buffered stream closed'
finally:
    release.set()
    reader.join(timeout=3)
assert client.close()
assert closed == [process] and client.process is None and not client.threads
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                            text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
