"""Exercise owned check processes without network, model imports or audio devices."""
import os
import subprocess
import sys


def test_isolated_checks_deliver_on_qt_thread_and_reap_failure_timeout(tmp_path):
    code = '''
import sys,time
from PySide6.QtCore import QProcess,QThread,QTimer
from PySide6.QtWidgets import QApplication
from linguaflow import ui_checks
app=QApplication([])
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
        assert QThread.currentThread() == app.thread()
        results.append(value)
    check.result.connect(received)
    check.completed.connect(lambda:done.append(1))
    check.begin()
    if name=='slow': check.timeout.start(30)
    deadline=time.monotonic()+3
    while not done and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    assert done == [1] and results == ([[1,2]] if name=='good' else [None]), (name,results,done)
    assert check.state() == QProcess.ProcessState.NotRunning
    check.deliver(None)
    assert done == [1] and len(results) == 1
assert len(ticks)>3
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 0, result.stdout + result.stderr
