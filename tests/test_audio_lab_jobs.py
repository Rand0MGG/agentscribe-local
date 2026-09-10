"""Exercise real QProcess cancellation without installing or opening audio devices."""
import os
import subprocess
import sys


def test_lab_can_cancel_and_close_running_job():
    code = r'''
import sys, time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer
import linguaflow.audio_processing.lab as module
module.runtime_python = lambda: Path(sys.executable)
app = QApplication([])
def wait_until(predicate, timeout=8000):
    loop=QEventLoop()
    poll=QTimer()
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    poll.start(20)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    poll.stop()
    assert predicate(), 'operation did not finish'
lab=module.AudioLab()
lab.show()
lab.launch(['-u','-c','import time; print("READY",flush=True); time.sleep(90)'], 'process')
wait_until(lambda: 'READY' in lab.log.toPlainText())
assert lab.cancel_button.isEnabled()
lab.reject()
wait_until(lambda: not lab.busy and not lab.isVisible())
assert lab.cancelled
lab2=module.AudioLab()
lab2.launch(['-u','-c','import time; print("READY",flush=True); time.sleep(90)'], 'process')
wait_until(lambda: 'READY' in lab2.log.toPlainText())
lab2.started_at=time.monotonic()-181
lab2.check_timeout()
wait_until(lambda: not lab2.busy)
assert lab2.prepare.isEnabled()
lab2.reject()
'''
    result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
