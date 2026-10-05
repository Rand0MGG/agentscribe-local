"""Real process handoff, cancellation and reused-session isolation without models."""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

import linguaflow.runtime_preparation as preparation
import linguaflow.wlk_session as session_module
from linguaflow.core import Settings
from linguaflow.wlk_session import Session

PROGRAM = '''
import sys,json,base64
print(json.dumps({'type':'runtime_ready'}), flush=True)
for line in sys.stdin:
    settings=json.loads(line)
    print(json.dumps({'type':'ready'}), flush=True)
    total=0
    for line in sys.stdin:
        message=json.loads(line)
        if message['type']=='stop': break
        total+=len(base64.b64decode(message['pcm']))
    print(json.dumps({'type':'caption','data':{'id':1,'start':0,'end':total/32000,
        'source':settings['source']+':'+str(total),'language':settings['source'],'final':True}}), flush=True)
    print(json.dumps({'type':'done'}), flush=True)
    print(json.dumps({'type':'runtime_ready'}), flush=True)
'''


def pool(monkeypatch, tmp_path, program=PROGRAM):
    path=tmp_path/'prepared-worker.py'
    path.write_text(program)
    original=subprocess.Popen
    calls=[]
    def spawn(command, **kwargs):
        if 'linguaflow.wlk_worker' not in command:
            return original(command, **kwargs)
        calls.append(command)
        return original([sys.executable, '-u', str(path)], **kwargs)
    monkeypatch.setattr(preparation, 'runtime_python', lambda: Path(sys.executable))
    monkeypatch.setattr(session_module, 'runtime_python', lambda: Path(sys.executable))
    monkeypatch.setattr(preparation.subprocess, 'Popen', spawn)
    runtime=preparation.RuntimePreparation()
    runtime.prepare()
    return runtime, calls


def execute(runtime, source, count):
    app=QCoreApplication.instance() or QCoreApplication([])
    captions, failures=[], []
    def capture(settings, stopped, block):
        for _ in range(count):
            block(np.full(1600, .01, dtype=np.float32))
    session=Session(Settings('fixture', source=source, translate=False),
                    capture_fn=capture, runtime=runtime)
    session.caption.connect(captions.append)
    session.failure.connect(failures.append)
    session.start()
    if not session.wait(5000):
        session.stop(discard=True)
        session.wait(5000)
        pytest.fail('reused session hung')
    app.processEvents()
    return session, captions, failures


def test_successful_sessions_reuse_process_with_fresh_language_and_audio(monkeypatch, tmp_path):
    runtime, calls=pool(monkeypatch, tmp_path)
    try:
        first, captions, failures=execute(runtime, 'en', 3)
        assert not failures and captions[-1].source=='en:9600'
        first.stop(discard=True)
        assert first.process.poll() is None, 'a finished session must not cancel the next lease'
        second, captions, failures=execute(runtime, 'zh', 1)
        assert not failures and captions[-1].source=='zh:3200'
        assert first.process is second.process and first.process.poll() is None
        assert len(calls)==1 and not runtime.busy
        assert calls[0][-1]=='linguaflow.wlk_worker'
    finally:
        worker=runtime.worker
        runtime.close()
    assert worker.process.poll() is not None and not worker.reader.is_alive()
    assert all(p.closed for p in (worker.process.stdin,worker.process.stdout,worker.process.stderr))


def test_second_lease_is_rejected_without_disrupting_first(monkeypatch,tmp_path):
    runtime,_=pool(monkeypatch,tmp_path)
    try:
        worker=runtime.acquire(Event())
        with pytest.raises(RuntimeError, match='另一会话'):
            runtime.acquire(Event())
        runtime.release(worker, reusable=False)
        assert not runtime.busy and runtime.worker is None
    finally:
        runtime.close()


def test_cancel_before_runtime_ready_never_captures_and_reaps_process(monkeypatch,tmp_path):
    runtime,_=pool(monkeypatch,tmp_path,'import time; time.sleep(30)')
    worker=runtime.worker
    worker.ready.wait(.05)
    session=Session(Settings('fixture',translate=False),runtime=runtime,
                    capture_fn=lambda *args:pytest.fail('cancelled preparation must not capture'))
    session.stop()
    session.start()
    try:
        assert session.wait(5000) and not session.last_error
        assert runtime.worker is None and not runtime.busy
        assert worker.process.poll() is not None
    finally:
        runtime.close()


def test_preparation_timeout_reaps_owned_process(monkeypatch,tmp_path):
    monkeypatch.setattr(preparation.PreparedWorker,'timeout',.1)
    runtime,_=pool(monkeypatch,tmp_path,'import time; time.sleep(30)')
    worker=runtime.worker
    try:
        with pytest.raises(RuntimeError,match='超时'):
            runtime.acquire(Event())
        assert worker.process.poll() is not None and runtime.worker is None
    finally:
        runtime.close()


def test_idle_preparation_timeout_is_bounded_without_a_session(monkeypatch,tmp_path):
    monkeypatch.setattr(preparation.PreparedWorker,'timeout',.1)
    runtime,_=pool(monkeypatch,tmp_path,'import time; time.sleep(30)')
    worker=runtime.worker
    try:
        assert worker.ready.wait(3)
        worker.close()
        assert worker.process.poll() is not None and '超时' in str(worker.error)
    finally:
        runtime.close()


@pytest.mark.parametrize('woken', [False, True])
def test_timeout_cleanup_after_wait_keeps_the_failure_reason(woken):
    # The watchdog may close between Event.wait timing out and the state check.
    worker=object.__new__(preparation.PreparedWorker)
    worker.error=None
    worker.closed=Event()
    def wait(timeout):
        worker.error=RuntimeError('运行环境准备超时')
        worker.closed.set()
        return woken
    worker.ready=SimpleNamespace(wait=wait)
    with pytest.raises(RuntimeError, match='超时') as caught:
        worker.wait(Event())
    assert caught.value.__cause__ is worker.error


@pytest.mark.parametrize('completed', ['cancelled', 'ready'])
def test_watchdog_does_not_overwrite_completion_at_timeout(completed):
    worker=object.__new__(preparation.PreparedWorker)
    worker.error=None
    worker.lock=Lock()
    worker.closed=Event()
    if completed=='cancelled':
        worker.closed.set()
    worker.ready=SimpleNamespace(wait=lambda timeout:False, is_set=lambda:completed=='ready')
    worker.close=lambda:pytest.fail('completed preparation must not be timed out')
    worker.watch_startup()
    assert worker.error is None


def test_missing_dependency_is_reported_and_next_attempt_is_fresh(monkeypatch,tmp_path):
    runtime,calls=pool(monkeypatch,tmp_path,"import json; print(json.dumps({'type':'error','text':'missing library'}),flush=True)")
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError,match='missing library'):
                runtime.acquire(Event())
            assert runtime.worker is None and not runtime.busy
        assert len(calls)==2
    finally:
        runtime.close()


def test_crashed_session_is_not_reused(monkeypatch,tmp_path):
    runtime,_=pool(monkeypatch,tmp_path,PROGRAM.split('for line in sys.stdin:')[0]+'sys.stdin.readline();sys.exit(7)')
    try:
        _,_,failures=execute(runtime,'en',1)
        assert failures and runtime.worker is None and not runtime.busy
    finally:
        runtime.close()


def test_missing_runtime_does_not_spawn(monkeypatch,tmp_path):
    monkeypatch.setattr(preparation,'runtime_python',lambda:tmp_path/'missing')
    runtime=preparation.RuntimePreparation()
    try:
        runtime.prepare()
        with pytest.raises(RuntimeError, match='未安装'):
            runtime.acquire(Event())
    finally:
        runtime.close()


def test_idle_expiry_releases_imports_and_active_lease_is_protected(monkeypatch,tmp_path):
    monkeypatch.setattr(preparation.RuntimePreparation,'idle_timeout',.1)
    runtime,calls=pool(monkeypatch,tmp_path)
    worker=runtime.worker
    try:
        deadline=time.monotonic()+3
        while runtime.worker is not None and time.monotonic()<deadline:
            time.sleep(.01)
        worker.close()
        assert runtime.worker is None and worker.process.poll() is not None
        leased=runtime.acquire(Event())
        assert len(calls)==2
        time.sleep(.15)
        assert runtime.worker is leased and leased.process.poll() is None
        runtime.release(leased,reusable=False)
    finally:
        runtime.close()


def test_preparation_imports_only_runtime_without_constructing_models(monkeypatch):
    import importlib

    from linguaflow.wlk_worker import prepare_runtime
    calls=[]
    monkeypatch.setattr(importlib,'import_module',calls.append)
    prepare_runtime()
    assert calls==['onnxruntime','wtpsplit','torch','whisperlivekit']


def test_models_are_released_before_accepting_next_settings(monkeypatch):
    import linguaflow.wlk_worker as worker
    calls=[]
    async def serve(settings,emit,read):
        calls.append(('serve',settings['source']))
        emit({'type':'done'})
    monkeypatch.setattr(worker,'serve',serve)
    monkeypatch.setattr(worker,'prepare_runtime',lambda:calls.append('imports'))
    monkeypatch.setattr(worker,'release_runtime_models',lambda:calls.append('release'))
    monkeypatch.setattr(worker.sys,'argv',['worker','--prepared'])
    monkeypatch.setattr(worker.sys,'stdin',io.StringIO('{"source":"en"}\n{"source":"zh"}\n'))
    output=io.StringIO()
    monkeypatch.setattr(worker.sys,'stdout',output)
    worker.main()
    assert calls==['imports',('serve','en'),'release',('serve','zh'),'release']
    assert [json.loads(s)['type'] for s in output.getvalue().splitlines()]==[
        'runtime_ready','done','runtime_ready','done','runtime_ready']


def test_cleanup_does_not_initialize_unused_cuda(monkeypatch):
    import gc

    from linguaflow.wlk_worker import release_runtime_models
    calls=[]
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=SimpleNamespace(
        is_initialized=lambda:False,empty_cache=lambda:pytest.fail('must not initialize CUDA'))))
    monkeypatch.setitem(sys.modules,'whisperlivekit',SimpleNamespace(TranscriptionEngine=SimpleNamespace(
        reset=lambda:calls.append('reset'))))
    monkeypatch.setattr(gc,'collect',lambda:calls.append('gc'))
    release_runtime_models()
    assert calls==['reset','gc']


@pytest.mark.parametrize('windows',[False,True])
def test_platform_spawn_keeps_utf8_and_hides_windows_console(monkeypatch,windows):
    flags=[]
    def spawn(command,**kwargs):
        flags.append(kwargs)
        return SimpleNamespace(stdout=io.StringIO('{"type":"runtime_ready"}\n'),stderr=io.StringIO(),
                               stdin=io.StringIO(),poll=lambda:0)
    monkeypatch.setattr(preparation,'os',SimpleNamespace(name='nt' if windows else 'posix',environ=os.environ))
    monkeypatch.setattr(preparation.subprocess,'CREATE_NO_WINDOW',123,raising=False)
    monkeypatch.setattr(preparation.subprocess,'Popen',spawn)
    worker=preparation.PreparedWorker(Path(sys.executable))
    assert worker.ready.wait(2) and worker.error is None
    worker.close()
    assert flags[0]['creationflags']==(123 if windows else 0)
    assert flags[0]['encoding']=='utf-8'
    assert flags[0]['env']['PYTHONIOENCODING']=='utf-8'


def test_preparation_preserves_network_and_resets_each_sessions_trace(monkeypatch):
    import linguaflow.wlk_worker as worker
    seen=[]
    async def serve(settings,emit,read):
        seen.append((os.environ.get('HF_HUB_OFFLINE'),os.environ.get('LINGUAFLOW_TRACE_REVISIONS')))
    monkeypatch.delenv('HF_HUB_OFFLINE',raising=False)
    monkeypatch.setattr(worker,'serve',serve)
    monkeypatch.setattr(worker,'prepare_runtime',lambda:seen.append(os.environ.get('HF_HUB_OFFLINE')))
    monkeypatch.setattr(worker,'release_runtime_models',lambda:None)
    monkeypatch.setattr(worker.sys,'argv',['worker','--prepared'])
    monkeypatch.setattr(worker.sys,'stdin',io.StringIO(
        '{"offline":true,"_diagnostic":true}\n{"offline":false,"_diagnostic":false}\n'))
    monkeypatch.setattr(worker.sys,'stdout',io.StringIO())
    worker.main()
    assert seen==[None,(None,'1'),(None,'0')]


def test_compatible_preparation_is_reused_without_a_device_profile(monkeypatch, tmp_path):
    runtime, calls = pool(monkeypatch, tmp_path)
    try:
        original = runtime.worker
        runtime.prepare()
        assert runtime.worker is original and len(calls) <= 1
        leased = runtime.acquire(Event())
        runtime.prepare()
        assert runtime.worker is leased and leased.process.poll() is None
        with pytest.raises(RuntimeError, match='另一会话'):
            runtime.acquire(Event())
        runtime.release(leased, reusable=False)
    finally:
        runtime.close()


def test_worker_ignores_retired_onnx_device_and_preserves_asr_device(monkeypatch):
    import linguaflow.wlk_worker as worker
    seen = []
    async def serve(settings, emit, read):
        seen.append(settings)
        emit({'type': 'done'})
    monkeypatch.setattr(worker, 'prepare_runtime', lambda: None)
    monkeypatch.setattr(worker, 'release_runtime_models', lambda: None)
    monkeypatch.setattr(worker, 'serve', serve)
    monkeypatch.setattr(worker.sys, 'stdin', io.StringIO(
        '{"semantic_device":"cuda","asr_device":"cuda"}\n'))
    output = io.StringIO()
    monkeypatch.setattr(worker.sys, 'stdout', output)
    worker.main()
    assert seen[0]['asr_device'] == 'cuda'
    assert [json.loads(line)['type'] for line in output.getvalue().splitlines()] == [
        'runtime_ready', 'done', 'runtime_ready']
