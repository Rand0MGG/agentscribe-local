"""Exercise Qt/process lifecycle with a real subprocess and deterministic PCM."""
import subprocess
import sys
import time

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from linguaflow.core import Settings
from linguaflow.wlk_session import Session


def execute(monkeypatch, tmp_path, program, capture, stopped=False, cancel_loading=False, setup=None, tick=None):
    import linguaflow.runtime_preparation as preparation
    import linguaflow.wlk_session as module
    script = tmp_path / "worker.py"
    script.write_text("import json; print(json.dumps({'type':'runtime_ready'}), flush=True)\n" + program,
                      encoding="utf8")
    original = subprocess.Popen
    monkeypatch.setattr(module, "runtime_python", lambda: __import__("pathlib").Path(sys.executable))
    monkeypatch.setattr(preparation, "runtime_python", lambda: __import__("pathlib").Path(sys.executable))
    def spawn(command, **kwargs):
        if 'linguaflow.wlk_worker' in command:
            return original([sys.executable, '-u', str(script)], **kwargs)
        return original(command, **kwargs)
    monkeypatch.setattr(preparation.subprocess, 'Popen', spawn)
    app = QCoreApplication.instance() or QCoreApplication([])
    session = Session(Settings("fixture", translate=False), capture_fn=capture,
                      recording_path=tmp_path / "recording.wav")
    captions, failures = [], []
    session.caption.connect(captions.append)
    session.failure.connect(failures.append)
    if setup:
        setup(session)
    if stopped:
        session.stop()
    session.start()
    deadline = time.monotonic() + 10
    while session.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        if tick:
            tick(session)
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
    import wave
    with wave.open(str(tmp_path / "recording.wav")) as recording:
        assert recording.getnframes() == 13 * 1600
        assert recording.getframerate() == 16000
        assert recording.getsampwidth() == 2


def test_stop_before_ready_does_not_open_audio(monkeypatch, tmp_path):
    opened = []
    captions, failures = execute(monkeypatch, tmp_path, PROGRAM,
                                 lambda *args: opened.append(True), stopped=True)
    assert not opened and not failures
    assert not captions  # Cancelling before startup must not create a session.


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


@pytest.mark.parametrize('user_stop', [False, True])
def test_stalled_stop_has_total_deadline_preserves_recording_and_caption(monkeypatch, tmp_path, user_stop):
    import wave

    import linguaflow.wlk_session as module
    monkeypatch.setattr(Session, 'stop_timeout', .3)
    opened, forced = [], []
    stop_tree = module.stop_tree
    def terminate(process, force=False):
        forced.append(force)
        stop_tree(process, force=force)
    monkeypatch.setattr(module, 'stop_tree', terminate)
    def capture(settings, stop, block):
        block(np.ones(1600, dtype=np.float32) * .01)
        opened.append(True)
        if user_stop:
            stop.wait()
    # The child continues reporting progress but never completes the stop.
    program = '''
import sys,json,time
sys.stdin.readline()
print(json.dumps({'type':'ready'}),flush=True)
print(json.dumps({'type':'caption','data':{'id':1,'start':0,'end':.1,'source':'retained','language':'en','final':True}}),flush=True)
for line in sys.stdin:
    if json.loads(line)['type']=='stop':
        while True:
            print(json.dumps({'type':'status','text':'still working'}),flush=True)
            time.sleep(.04)
'''
    def tick(session):
        if user_stop and opened:
            session.stop()  # Repeated requests must not extend the deadline.
    started = time.monotonic()
    captions, failures = execute(monkeypatch, tmp_path, program, capture, tick=tick)
    assert time.monotonic() - started < 6
    assert any('收尾超时' in error for error in failures)
    assert forced and all(forced)
    assert captions[0].source == 'retained'
    with wave.open(str(tmp_path / 'recording.wav')) as recording:
        assert recording.getnframes() == 1600


def test_cancelled_worker_does_not_leave_mlx_helper_pipes_open(monkeypatch, tmp_path):
    if sys.platform != 'darwin':
        __import__('pytest').skip('MLX helper is Mac-only')
    monkeypatch.setattr(Session, 'startup_idle_timeout', 1.)
    program = '''
import os,sys,subprocess,time
sys.stdin.readline()
code = 'import sys; from linguaflow.mlx_asr_worker import watch_parent; watch_parent(int(sys.argv[1]))'
subprocess.Popen([sys.executable, '-c', code, str(os.getpid())])
time.sleep(30)
'''
    _, failures = execute(monkeypatch, tmp_path, program,
                         lambda *a: (_ for _ in ()).throw(AssertionError('no capture')))
    assert any('长时间没有进展' in error for error in failures)


def test_model_load_error_prevents_capture(monkeypatch, tmp_path):
    program = '''
import json, sys, time
sys.stdin.readline()
print(json.dumps({'type': 'error', 'text': 'SaT 分句模型加载失败'}), flush=True)
time.sleep(30)
'''
    opened = []
    captions, failures = execute(monkeypatch, tmp_path, program, lambda *args: opened.append(True))
    assert not opened and not captions
    assert any('SaT' in error for error in failures)


def test_pause_closes_capture_drains_audio_and_resumes_same_recording(monkeypatch, tmp_path):
    import wave
    from threading import Event

    captured = Event()
    segments, pauses, status = [], [], []
    phase = [0]
    program = PROGRAM.replace("if message['type'] == 'stop': break", """
    if message['type'] == 'stop': break
    if message['type'] == 'pause':
        print(json.dumps({'type':'status','text':'paused:' + str(total)}), flush=True)
        continue
""")

    def capture(settings, stop, block):
        segments.append(True)
        block(np.full(1600, .1 * len(segments), dtype=np.float32))
        if len(segments) == 1:
            captured.set()
            assert stop.wait(5)
            # A native read already in progress can return after pause is requested.
            block(np.ones(1600, dtype=np.float32))

    def setup(session):
        session.paused.connect(pauses.append)
        session.status.connect(status.append)

    def tick(session):
        if phase[0] == 0 and captured.is_set():
            assert session.pause()
            phase[0] = 1
        elif phase[0] == 1 and pauses == [True] and 'paused:3200' in status:
            assert segments == [True]
            assert session.isRunning() and not session.capture_done.is_set()
            assert session.resume()
            phase[0] = 2

    captions, failures = execute(monkeypatch, tmp_path, program, capture, setup=setup, tick=tick)
    assert not failures
    assert phase == [2] and pauses == [True, False] and len(segments) == 2
    assert captions[-1].source == '6400' and captions[-1].end == .2
    with wave.open(str(tmp_path / 'recording.wav')) as wav:
        assert wav.getnframes() == 3200
        audio = np.frombuffer(wav.readframes(3200), dtype='<i2')
    assert np.all(audio[:1600] == int(.1 * 32767))
    assert np.all(audio[1600:] == int(.2 * 32767))


def test_stop_while_paused_wakes_capture_and_finishes(monkeypatch, tmp_path):
    from threading import Event
    captured = Event()
    pauses = []
    requested = [False]
    def capture(settings, stop, block):
        block(np.ones(1600, dtype=np.float32) * .01)
        captured.set()
        assert stop.wait(5)
    def tick(session):
        if captured.is_set() and not requested[0]:
            assert session.pause()
            requested[0] = True
        if pauses:
            session.stop()
            assert not session.resume()
    program = PROGRAM.replace("if message['type'] == 'stop': break",
                              "if message['type'] == 'stop': break\n    if message['type'] == 'pause': continue")
    captions, failures = execute(monkeypatch, tmp_path, program, capture,
                                 setup=lambda s: s.paused.connect(pauses.append), tick=tick)
    assert not failures and pauses == [True]
    assert captions[-1].source == '3200'


def test_reconnect_failure_after_pause_finishes_without_losing_saved_audio(monkeypatch, tmp_path):
    import wave
    from threading import Event
    captured = Event()
    segments, pauses = [], []
    phase = [0]
    def capture(settings, stop, block):
        segments.append(True)
        if len(segments) == 2:
            raise RuntimeError('fixture device disconnected during pause')
        block(np.ones(1600, dtype=np.float32) * .01)
        captured.set()
        assert stop.wait(5)
    def tick(session):
        if phase[0] == 0 and captured.is_set():
            assert session.pause()
            phase[0] = 1
        elif phase[0] == 1 and pauses:
            assert session.resume()
            phase[0] = 2
    program = PROGRAM.replace("if message['type'] == 'stop': break",
                              "if message['type'] == 'stop': break\n    if message['type'] == 'pause': continue")
    _, failures = execute(monkeypatch, tmp_path, program, capture,
                          setup=lambda s: s.paused.connect(pauses.append), tick=tick)
    assert len(segments) == 2 and any('disconnected' in text for text in failures)
    with wave.open(str(tmp_path / 'recording.wav')) as wav:
        assert wav.getnframes() == 1600


def test_model_inference_error_stops_capture_and_preserves_caption(monkeypatch, tmp_path):
    program = '''
import json, sys, time
sys.stdin.readline()
print(json.dumps({'type': 'ready'}), flush=True)
sys.stdin.readline()
print(json.dumps({'type': 'caption', 'data': {
    'id': 1, 'start': 0, 'end': 1, 'source': 'Hello', 'language': 'en'}}), flush=True)
print(json.dumps({'type': 'error', 'text': 'SaT 分句推理失败'}), flush=True)
time.sleep(30)
'''
    stopped = []
    def capture(settings, stop, block):
        block(np.ones(1600, dtype=np.float32) * .01)
        assert stop.wait(5)
        stopped.append(True)
    captions, failures = execute(monkeypatch, tmp_path, program, capture)
    assert stopped == [True] and captions[0].source == 'Hello'
    assert any('SaT' in error for error in failures)
