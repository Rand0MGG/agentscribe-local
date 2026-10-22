"""Real process handoff, cancellation and reused-session isolation without models."""
import atexit
import errno
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Lock, Thread
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

import linguaflow.runtime_preparation as preparation
import linguaflow.wlk_session as session_module
from linguaflow.core import Settings
from linguaflow.wlk_session import Session


@pytest.mark.p1
@pytest.mark.parametrize('entry', ['close', 'release', 'async_close'])
def test_pool_retains_failed_cleanup_for_explicit_retry(monkeypatch, entry):
    tasks = []
    class Worker:
        attempts = 0
        def close(self):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError('cleanup failed')
    runtime = preparation.RuntimePreparation()
    worker = runtime.worker = Worker()
    try:
        if entry == 'async_close':
            monkeypatch.setattr(preparation, 'Thread',
                lambda target: SimpleNamespace(start=lambda: tasks.append(target)))
            runtime.close(wait=False)
            action = tasks.pop()
        elif entry == 'release':
            runtime.busy = True
            def action():
                runtime.release(worker, reusable=False)
        else:
            action = runtime.close
        with pytest.raises(RuntimeError, match='cleanup failed'):
            action()
        assert runtime.worker is worker and worker.attempts == 1
        runtime.close()
        runtime.close()
        assert worker.attempts == 2 and runtime.worker is None
    finally:
        atexit.unregister(runtime.close)


@pytest.mark.p1
def test_async_pool_close_is_joined_by_synchronous_retry():
    entered, finish = Event(), Event()
    class Worker:
        attempts = 0
        def close(self):
            self.attempts += 1
            entered.set()
            assert finish.wait(5)
    runtime = preparation.RuntimePreparation()
    worker = runtime.worker = Worker()
    retry = Thread(target=runtime.close)
    try:
        runtime.close(wait=False)
        assert entered.wait(3) and runtime.worker is worker
        retry.start()
        finish.set()
        retry.join(5)
        assert not retry.is_alive() and runtime.worker is None and worker.attempts == 1
    finally:
        finish.set()
        runtime.close()


@pytest.mark.p1
@pytest.mark.parametrize('platform,returncode,ignored', [('win32', 0, True), ('win32', None, False),
                                                       ('darwin', 0, False)])
def test_einval_flush_is_ignored_only_for_exited_windows_child(monkeypatch, platform, returncode, ignored):
    import linguaflow.process_platform as module
    error = OSError(errno.EINVAL, 'Invalid argument')
    class Input(io.StringIO):
        def close(self):
            super().close()
            raise error
    process = SimpleNamespace(stdin=Input(), stdout=io.StringIO(), stderr=io.StringIO(), poll=lambda:returncode)
    monkeypatch.setattr(module.sys, 'platform', platform)
    if ignored:
        module.close_process_pipes(process)
    else:
        with pytest.raises(OSError) as caught:
            module.close_process_pipes(process)
        assert caught.value is error
    assert all(stream.closed for stream in (process.stdin, process.stdout, process.stderr))

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


@pytest.mark.p1
@pytest.mark.parametrize('system', ['win32', 'darwin'])
def test_worker_spawn_failure_releases_platform_ownership(monkeypatch, system):
    import linguaflow.process_platform as platform
    closed, calls = [], []
    class Job:
        def environment(self, env):
            return {**env, 'test_job': 'owned'}
        def close(self):
            closed.append(True)
    error = OSError('cannot spawn')
    def spawn(command, **options):
        calls.append((command, options))
        raise error
    monkeypatch.setattr(sys, 'platform', system)
    monkeypatch.setattr(platform, 'WindowsWorkerJob', Job)
    monkeypatch.setattr(platform.subprocess, 'Popen', spawn)
    monkeypatch.setattr(platform.subprocess, 'CREATE_NO_WINDOW', 123, raising=False)
    with pytest.raises(OSError) as caught:
        platform.start_worker('python', 'worker', env={'test': 'kept'}, cwd='.')
    assert caught.value is error
    command, options = calls[0]
    assert command[-2:] == ['linguaflow.process_platform', 'worker']
    assert options['env']['test'] == 'kept'
    assert closed == ([True] if system == 'win32' else [])
    if system == 'win32':
        assert options['env']['test_job'] == 'owned' and options['creationflags'] == 123
    else:
        assert options['start_new_session'] and 'test_job' not in options['env']


@pytest.mark.p1
def test_exited_posix_leader_still_reaps_group_while_transport_is_active(monkeypatch):
    import linguaflow.process_platform as platform
    monkeypatch.setattr(sys, 'platform', 'darwin')
    stopped = []
    process = SimpleNamespace(poll=lambda: 0)
    alive = [True]
    reader = SimpleNamespace(is_alive=lambda: alive[0])
    monkeypatch.setattr(platform, 'stop_tree', lambda p, force: stopped.append((p, force)))
    platform.stop_worker(process, None, [reader])
    assert stopped == [(process, True)]
    alive[0] = False
    platform.stop_worker(process, None, [reader])
    assert len(stopped) == 1  # A completed cleanup must not signal a reused group ID.


def pool(monkeypatch, tmp_path, program=PROGRAM):
    __import__('asyncio')  # Windows subclasses Popen during its first import.
    path=tmp_path/'prepared-worker.py'
    path.write_text(program)
    original=subprocess.Popen
    calls=[]
    def spawn(command, **kwargs):
        if 'linguaflow.wlk_worker' not in command:
            return original(command, **kwargs)
        calls.append(command)
        return original([sys.executable, *command[1:-1], str(path)], **kwargs)
    monkeypatch.setattr(preparation, 'runtime_python', lambda: Path(sys.executable))
    monkeypatch.setattr(session_module, 'runtime_python', lambda: Path(sys.executable))
    monkeypatch.setattr(preparation.subprocess, 'Popen', spawn)
    runtime=preparation.RuntimePreparation()
    runtime.prepare()
    return runtime, calls


@pytest.mark.p1
def test_new_environment_is_used_after_current_session_release(monkeypatch, tmp_path):
    runtime, calls = pool(monkeypatch, tmp_path)
    active = runtime.acquire(Event())
    alternative = tmp_path / 'new-python'
    alternative.write_bytes(b'fixture path; spawn uses the real interpreter')
    monkeypatch.setattr(preparation, 'runtime_python', lambda: alternative)
    try:
        runtime.prepare()  # The active session keeps its original process.
        assert runtime.worker is active and active.process.poll() is None
        runtime.release(active, reusable=False)
        replacement = runtime.acquire(Event())
        assert replacement is not active and replacement.python == alternative
        assert len(calls) == 2
        runtime.release(replacement, reusable=False)
    finally:
        runtime.close()


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


@pytest.mark.p1
def test_successful_sessions_reuse_process_with_fresh_language_and_audio(monkeypatch, tmp_path):
    runtime, calls=pool(monkeypatch, tmp_path)
    try:
        original = runtime.worker
        runtime.prepare()
        assert runtime.worker is original
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


@pytest.mark.p1
def test_second_lease_is_rejected_without_disrupting_first(monkeypatch,tmp_path):
    runtime,_=pool(monkeypatch,tmp_path)
    try:
        worker=runtime.acquire(Event())
        runtime.prepare()
        assert runtime.worker is worker and worker.process.poll() is None
        with pytest.raises(RuntimeError, match='另一会话'):
            runtime.acquire(Event())
        runtime.release(worker, reusable=False)
        assert not runtime.busy and runtime.worker is None
    finally:
        runtime.close()


@pytest.mark.p1
def test_crashed_worker_descendants_and_pipe_readers_are_reaped(monkeypatch, tmp_path):
    import psutil

    child_file = tmp_path / 'descendant.pid'
    program = f'''
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                         stdin=subprocess.DEVNULL)
Path({str(child_file)!r}).write_text(str(child.pid))
print('{{"type":"runtime_ready"}}', flush=True)
sys.stdin.readline()
'''
    runtime, _ = pool(monkeypatch, tmp_path, program)
    worker = runtime.acquire(Event())
    descendants = psutil.Process(worker.process.pid).children(recursive=True)
    assert int(child_file.read_text()) in {p.pid for p in descendants}
    for process in descendants:
        process.create_time()  # Retain identities while ancestry is known.
    failures = []

    def close():
        try:
            runtime.close()
        except Exception as exc:
            failures.append(exc)

    closer = Thread(target=close, daemon=True)
    try:
        worker.process.stdin.write('exit\n')
        worker.process.stdin.flush()
        worker.process.wait(timeout=5)
        closer.start()
        closer.join(8)
        assert not closer.is_alive(), 'cleanup blocked on a pipe held by a descendant'
        assert not failures
        assert not worker.reader.is_alive() and not worker.diagnostics.is_alive()
        assert all(p.closed for p in (worker.process.stdin, worker.process.stdout, worker.process.stderr))
        _, alive = psutil.wait_procs(descendants, timeout=3)
        assert not [p for p in alive if p.status() != psutil.STATUS_ZOMBIE]
    finally:
        for process in reversed(descendants):
            try:
                if process.is_running():
                    process.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(descendants, timeout=3)
        if closer.ident is not None:
            closer.join(5)
        worker.close()
        runtime.close()


@pytest.mark.p1
@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Job Object lifetime')
def test_owner_exit_reaps_worker_job_without_python_cleanup(tmp_path):
    import psutil

    from linguaflow.process_platform import close_process_pipes, spawn_options
    from linguaflow.runtime_paths import python_environment

    ready, exit_owner = tmp_path / 'child.pid', tmp_path / 'exit-owner'
    worker = tmp_path / 'job-worker.py'
    worker.write_text(f'''
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
Path({str(ready)!r}).write_text(str(child.pid))
time.sleep(30)
''')
    owner = tmp_path / 'job-owner.py'
    owner.write_text(f'''
import os, subprocess, sys, time
from pathlib import Path
from linguaflow.process_platform import WindowsWorkerJob, spawn_options
from linguaflow.runtime_paths import python_environment
job = WindowsWorkerJob()
process = subprocess.Popen([sys.executable, '-u', '-m', 'linguaflow.process_platform', {str(worker)!r}],
                           env=job.environment(python_environment()), **spawn_options())
deadline = time.monotonic() + 15
while not Path({str(exit_owner)!r}).exists() and time.monotonic() < deadline:
    time.sleep(.01)
os._exit(0)
''')
    process = subprocess.Popen([sys.executable, str(owner)], env=python_environment(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               **spawn_options())
    descendants = []
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists()
        descendants = psutil.Process(process.pid).children(recursive=True)
        assert int(ready.read_text()) in {p.pid for p in descendants}
        for child in descendants:
            child.create_time()
        exit_owner.touch()
        process.wait(timeout=5)
        _, alive = psutil.wait_procs(descendants, timeout=5)
        assert not alive
    finally:
        for child in reversed(descendants):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(descendants, timeout=3)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        close_process_pipes(process)


@pytest.mark.p1
@pytest.mark.parametrize('broken_pipe', [True, False])
def test_exited_worker_closes_all_pipes_when_stdin_flush_fails(broken_pipe):
    import errno

    error = BrokenPipeError(errno.EPIPE, 'Broken pipe') if broken_pipe else OSError(errno.EIO, 'I/O failure')
    class ExitedChildPipe(io.RawIOBase):
        def writable(self):
            return True
        def write(self, data):
            raise error
    stdin = io.TextIOWrapper(io.BufferedWriter(ExitedChildPipe()), encoding='utf-8')
    stdin.write('{"source":"en"}\n')  # Pending settings encounter the exited child only on close/flush.
    worker = object.__new__(preparation.PreparedWorker)
    worker.lock, worker.close_lock = Lock(), Lock()
    worker.closed, worker.ready = Event(), Event()
    worker.job = None
    joined = []
    worker.reader = SimpleNamespace(join=lambda timeout: joined.append('reader'), is_alive=lambda: False)
    worker.diagnostics = SimpleNamespace(join=lambda timeout: joined.append('diagnostics'), is_alive=lambda: False)
    worker.process = SimpleNamespace(stdin=stdin, stdout=io.StringIO(), stderr=io.StringIO(), poll=lambda:0)
    if broken_pipe:
        worker.close()
    else:
        with pytest.raises(OSError) as caught:
            worker.close()
        assert caught.value is error
    assert worker.closed.is_set() and worker.ready.is_set()
    assert joined == ['reader', 'diagnostics']
    assert all(pipe.closed for pipe in (stdin, worker.process.stdout, worker.process.stderr))
    worker.close()  # Cleanup is repeatable after an expected or unexpected pipe failure.


@pytest.mark.p1
def test_pipe_cleanup_preserves_output_error_and_closes_remaining_streams():
    from linguaflow.process_platform import close_process_pipes
    error = BrokenPipeError('unexpected output failure')
    class Output(io.StringIO):
        def close(self):
            super().close()
            raise error
    process = SimpleNamespace(stdin=io.StringIO(), stdout=Output(), stderr=io.StringIO())
    with pytest.raises(BrokenPipeError) as caught:
        close_process_pipes(process)
    assert caught.value is error
    assert all(pipe.closed for pipe in (process.stdin, process.stdout, process.stderr))
    close_process_pipes(process)


@pytest.mark.p1
def test_reader_timeout_keeps_pipes_owned_and_retry_can_complete(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    worker = object.__new__(preparation.PreparedWorker)
    worker.lock, worker.close_lock = Lock(), Lock()
    worker.closed, worker.ready = Event(), Event()
    worker.job = None
    alive = [True]
    worker.reader = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: alive[0])
    worker.process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(),
                                     stderr=io.StringIO(), poll=lambda: 0)
    with pytest.raises(RuntimeError, match='读取线程未退出'):
        worker.close()
    assert not any(p.closed for p in (worker.process.stdin, worker.process.stdout, worker.process.stderr))
    alive[0] = False
    worker.close()
    assert all(p.closed for p in (worker.process.stdin, worker.process.stdout, worker.process.stderr))


@pytest.mark.p1
def test_shutdown_collects_diagnostics_created_during_startup_join(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    worker = object.__new__(preparation.PreparedWorker)
    worker.lock, worker.close_lock = Lock(), Lock()
    worker.closed, worker.ready = Event(), Event()
    worker.job = None
    joined = []

    def join_startup(timeout):
        worker.diagnostics = SimpleNamespace(join=lambda timeout: joined.append('logs'), is_alive=lambda: False)

    worker.reader = SimpleNamespace(join=join_startup, is_alive=lambda: False)
    worker.process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(),
                                     stderr=io.StringIO(), poll=lambda: 0)
    worker.close()
    assert joined == ['logs']
    assert all(p.closed for p in (worker.process.stdin, worker.process.stdout, worker.process.stderr))


@pytest.mark.p1
def test_cancel_before_session_start_keeps_capture_closed_and_pool_owned(monkeypatch,tmp_path):
    runtime,_=pool(monkeypatch,tmp_path,'import time; time.sleep(30)')
    worker=runtime.worker
    worker.ready.wait(.05)
    session=Session(Settings('fixture',translate=False),runtime=runtime,
                    capture_fn=lambda *args:pytest.fail('cancelled preparation must not capture'))
    session.stop()
    session.start()
    try:
        assert session.wait(5000) and not session.last_error
        # No session lease was acquired. Independent prewarming remains owned
        # by the pool, whose shutdown must still reap it and its reader.
        assert runtime.worker is worker and not runtime.busy
    finally:
        runtime.close()
    assert worker.process.poll() is not None and not worker.reader.is_alive()


@pytest.mark.p1
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


@pytest.mark.p1
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


@pytest.mark.p1
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


@pytest.mark.p1
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


@pytest.mark.p1
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


@pytest.mark.p1
def test_crashed_session_is_not_reused(monkeypatch,tmp_path):
    runtime,_=pool(monkeypatch,tmp_path,PROGRAM.split('for line in sys.stdin:')[0]+'sys.stdin.readline();sys.exit(7)')
    try:
        _,_,failures=execute(runtime,'en',1)
        assert failures and runtime.worker is None and not runtime.busy
    finally:
        runtime.close()


@pytest.mark.p1
def test_missing_runtime_does_not_spawn(monkeypatch,tmp_path):
    monkeypatch.setattr(preparation,'runtime_python',lambda:tmp_path/'missing')
    runtime=preparation.RuntimePreparation()
    try:
        runtime.prepare()
        with pytest.raises(RuntimeError, match='未安装'):
            runtime.acquire(Event())
    finally:
        runtime.close()


@pytest.mark.p1
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


@pytest.mark.p2
def test_preparation_imports_only_runtime_without_constructing_models(monkeypatch):
    import importlib

    from linguaflow.wlk_worker import prepare_runtime
    calls=[]
    monkeypatch.setattr(importlib,'import_module',calls.append)
    prepare_runtime()
    assert calls==['onnxruntime','wtpsplit','torch','whisperlivekit']


@pytest.mark.p1
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


@pytest.mark.p2
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


@pytest.mark.p1
@pytest.mark.parametrize('windows',[False,True])
def test_platform_spawn_keeps_utf8_and_hides_windows_console(monkeypatch,windows):
    import linguaflow.process_platform as platform
    flags=[]
    def spawn(command,**kwargs):
        flags.append(kwargs)
        return SimpleNamespace(stdout=io.StringIO('{"type":"runtime_ready"}\n'),stderr=io.StringIO(),
                               stdin=io.StringIO(),poll=lambda:0)
    monkeypatch.setattr(platform.sys,'platform','win32' if windows else 'darwin')
    monkeypatch.setattr(preparation.subprocess,'CREATE_NO_WINDOW',123,raising=False)
    monkeypatch.setattr(preparation.subprocess,'Popen',spawn)
    worker=preparation.PreparedWorker(Path(sys.executable))
    assert worker.ready.wait(2) and worker.error is None
    worker.close()
    if windows:
        assert flags[0]['creationflags']==123
        assert 'start_new_session' not in flags[0]
    else:
        assert flags[0]['start_new_session'] is True
        assert 'creationflags' not in flags[0]
    assert flags[0]['encoding']=='utf-8'
    assert flags[0]['env']['PYTHONIOENCODING']=='utf-8'


@pytest.mark.p1
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
