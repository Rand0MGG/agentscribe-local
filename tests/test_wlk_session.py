"""Exercise Qt/process lifecycle with a real subprocess and deterministic PCM."""
import subprocess
import sys
import time

import numpy as np
from PySide6.QtCore import QCoreApplication

from linguaflow.core import Settings
from linguaflow.wlk_session import Session


def execute(monkeypatch, tmp_path, program, capture, stopped=False, cancel_loading=False):
    import linguaflow.wlk_session as module
    script = tmp_path / "worker.py"
    script.write_text(program, encoding="utf8")
    original = subprocess.Popen
    monkeypatch.setattr(module, "runtime_python", lambda: __import__("pathlib").Path(sys.executable))
    monkeypatch.setattr(module.subprocess, "Popen", lambda command, **kw: original(
        [sys.executable, "-u", str(script)], **kw))
    app = QCoreApplication.instance() or QCoreApplication([])
    session = Session(Settings("fixture", translate=False), capture_fn=capture)
    captions, failures = [], []
    session.caption.connect(captions.append)
    session.failure.connect(failures.append)
    if stopped:
        session.stop()
    session.start()
    deadline = time.monotonic() + 10
    while session.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        if cancel_loading and session.process is not None:
            session.stop()
        time.sleep(.01)
    if session.isRunning():
        session.stop(discard=True)
        session.wait(5000)
        raise AssertionError("Session failed to finish")
    app.processEvents()
    return captions, failures


PROGRAM = '''
import sys, json, base64
settings = json.loads(sys.stdin.readline())
print(json.dumps({'type':'ready'}), flush=True)
total = 0
for line in sys.stdin:
    message = json.loads(line)
    if message['type'] == 'stop': break
    total += len(base64.b64decode(message['pcm']))
print(json.dumps({'type':'caption','data':{'id':1,'start':0,'end':total/32000,
    'source':str(total),'language':'en','final':True}}), flush=True)
print(json.dumps({'type':'done'}), flush=True)
'''


def test_captured_pcm_is_drained_before_process_stops(monkeypatch, tmp_path):
    def capture(settings, stop, block):
        for _ in range(13):
            block(np.ones(1600, dtype=np.float32) * .01)
    captions, failures = execute(monkeypatch, tmp_path, PROGRAM, capture)
    assert not failures
    assert captions[0].source == str(13 * 1600 * 2)


def test_stop_before_ready_does_not_open_audio(monkeypatch, tmp_path):
    opened = []
    captions, failures = execute(monkeypatch, tmp_path, PROGRAM,
                                 lambda *args: opened.append(True), stopped=True)
    assert not opened and not failures
    assert captions[0].source == "0"


def test_crashed_worker_reports_failure_without_hanging(monkeypatch, tmp_path):
    program = "import sys; sys.stdin.readline(); sys.exit(7)"
    opened = []
    _, failures = execute(monkeypatch, tmp_path, program, lambda *args: opened.append(True))
    assert not opened and failures and "7" in failures[0]


def test_capture_exception_terminates_waiting_worker(monkeypatch, tmp_path):
    def broken(*args):
        raise RuntimeError("device disconnected")
    _, failures = execute(monkeypatch, tmp_path, PROGRAM, broken)
    assert any("device disconnected" in error for error in failures)


def test_unresponsive_startup_is_terminated(monkeypatch, tmp_path):
    monkeypatch.setattr(Session, "startup_idle_timeout", .1)
    opened = []
    _, failures = execute(monkeypatch, tmp_path,
                          "import sys,time; sys.stdin.readline(); time.sleep(30)",
                          lambda *args: opened.append(True))
    assert not opened
    assert any("启动长时间没有进展" in error for error in failures)


def test_stop_cancels_model_loading_without_waiting(monkeypatch, tmp_path):
    opened = []
    _, failures = execute(monkeypatch, tmp_path,
                          "import sys,time; sys.stdin.readline(); time.sleep(30)",
                          lambda *args: opened.append(True), cancel_loading=True)
    assert not opened and not failures
