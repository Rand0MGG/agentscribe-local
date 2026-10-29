"""Exercise owned check processes without network, model imports or audio devices."""
import os
import subprocess
import sys

import pytest
from ui_support import assert_ui_process


@pytest.mark.p1
def test_isolated_checks_deliver_on_owner_thread_and_reap_failure_timeout(tmp_path):
    code = '''
import sys,time
from linguaflow.events import Dispatcher, Timer as QTimer
import threading
from linguaflow import ui_checks
app=Dispatcher()
ticks=[]
timer=QTimer()
timer.timeout.connect(lambda:ticks.append(1))
timer.start(5)
scripts={'good':'import time;time.sleep(.15);print("[1,2]")',
 'bad':'print("invalid JSON")','error':'raise SystemExit(1)',
 'slow':'import time;time.sleep(30)'}
ui_checks.installation_command=lambda module,*args: ([sys.executable,'-c',scripts[module]]
 if module in scripts else ['/nonexistent/agentscribe-check'])
for name in ['good','bad','error','slow','missing']:
    results,done=[],[]
    check=ui_checks.BackgroundCheck(name)
    def received(value):
        assert threading.get_ident() == app.owner
        results.append(value)
    check.result.connect(received)
    check.completed.connect(lambda:done.append(1))
    check.begin()
    if name=='slow': check.timeout_seconds=.03
    deadline=time.monotonic()+3
    while not done and time.monotonic()<deadline:
        app.process();time.sleep(.005)
    assert done == [1] and results == ([[1,2]] if name=='good' else [None]), (name,results,done)
    expected_reason = {'good':'', 'bad':'返回内容无法解析', 'error':'退出码 1',
                       'slow':'超时', 'missing':'无法启动'}[name]
    assert expected_reason in check.failure_reason, (name, check.failure_reason)
    assert not check.isRunning()
    assert check.process is None or check.process.poll() is not None
    check._completed()
    assert done == [1] and len(results) == 1
assert len(ticks)>3
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, errors='backslashreplace', timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert_ui_process(result)
