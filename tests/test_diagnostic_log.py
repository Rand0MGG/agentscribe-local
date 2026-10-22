import io
import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow import diagnostic_log as diag
from linguaflow.qwen_accurate import QwenAccurateOnline


@pytest.fixture
def logs(tmp_path, monkeypatch):
    diag.close_logging()
    monkeypatch.setenv('AGENTSCRIBE_LOG_DIR', str(tmp_path / '中文日志'))
    diag.set_session('test-session')
    diag.set_sink(None)
    yield tmp_path / '中文日志'
    diag.close_logging()
    diag.set_sink(None)
    diag.set_session(None)


def read_rows(path):
    assert diag.flush()
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


@pytest.mark.p0
def test_rotation_retention_and_private_exception(logs):
    logs.mkdir()
    stale = logs / 'support-desktop-20000101T000000-999999999-12345678.jsonl'
    stale.write_text('old', encoding='utf-8')
    os.utime(stale, (time.time() - 15 * 86400,) * 2)
    unrelated = logs / 'keep.txt'
    unrelated.write_text('keep', encoding='utf-8')
    path = diag.start_logging('test', max_bytes=1800, backups=2)
    for i in range(30):
        diag.event('progress', index=i)
    try:
        raise ValueError('private transcript api_key=SECRET C:/Users/private-name/recording.wav')
    except ValueError as exc:
        diag.exception('failure', exc)
    assert diag.flush()
    assert not stale.exists() and unrelated.exists()
    files = list(logs.glob('support-*'))
    assert len(files) <= 3
    raw = ''.join(p.read_text(encoding='utf-8') for p in files)
    assert 'SECRET' not in raw and 'private transcript' not in raw and 'private-name' not in raw
    row = read_rows(path)[-1]
    assert row['session'] == 'test-session'
    assert row['exceptions'][0]['type'] == 'ValueError'
    assert row['exceptions'][0]['frames'][-1]['function'] == 'test_rotation_retention_and_private_exception'


@pytest.mark.p1
def test_log_write_failure_does_not_break_application(logs, monkeypatch):
    diag.start_logging('test')
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(diag._handler, 'shouldRollover', fail)
    diag.event('recording_continues')
    assert diag.flush()
    assert '写入失败' in diag.log_error()


@pytest.mark.p2
def test_log_creation_failure_visible_without_throwing(logs):
    logs.write_text('not a directory', encoding='utf-8')
    assert diag.start_logging('test') is None
    assert '无法创建' in diag.log_error()


@pytest.mark.p0
def test_decode_trace_retains_real_progress_across_overlap(logs):
    path = diag.start_logging('test')
    sent = []
    diag.set_sink(sent.append)
    calls = []
    def decode(audio):
        calls.append(len(audio))
        return 'private recognized text'
    asr = QwenAccurateOnline(decode, lambda audio, seconds: 8 * 16000, 'en',
                            window_seconds=8, token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    asr.insert_audio_chunk(np.ones(13 * 16000), 13.)
    asr.process_iter()  # rolls at 8+5 seconds; retains 10 seconds
    asr.insert_audio_chunk(np.ones(8000), 13.5)
    asr.process_iter()
    asr.finish()
    rows = read_rows(path)
    decodes = [r for r in rows if r['event'] == 'asr_decode_end']
    assert calls == [208000, 168000]
    assert [r['new_audio_seconds'] for r in decodes] == [13., .5]
    assert [(r['window_start'], r['window_end']) for r in decodes] == [(0., 13.), (3., 13.5)]
    assert decodes[0]['reason'] == 'capacity'
    roll = next(r for r in rows if r['event'] == 'asr_window_roll')
    assert roll['cut_seconds'] == 8 and roll['retained_seconds'] == 10
    assert all(r['compute_seconds'] >= 0 for r in decodes)
    assert len(sent) == 2 and sent[1]['decode_id'] == 2
    assert 'private recognized text' not in path.read_text(encoding='utf-8')


@pytest.mark.p0
def test_failed_decode_has_start_and_failure_without_text(logs):
    path = diag.start_logging('test')
    def decode(audio):
        raise RuntimeError('private audio-derived text')
    asr = QwenAccurateOnline(decode, lambda a, s: len(a), 'en',
                            token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    asr.insert_audio_chunk(np.ones(8000), .5)
    with pytest.raises(RuntimeError):
        asr.process_iter()
    rows = read_rows(path)
    assert [r['event'] for r in rows][-3:] == ['asr_decode_start', 'asr_decode_failed', 'asr_exception']
    assert 'private audio-derived text' not in path.read_text(encoding='utf-8')


@pytest.mark.p0
def test_independent_process_files_and_uncaught_hook(logs):
    program = '''
from linguaflow import diagnostic_log as d
d.start_logging('testchild')
d.install_exception_hooks()
d.install_exception_hooks()
d.set_session('linked-session')
raise RuntimeError('CUDA out of memory; PRIVATE_TRANSCRIPT')
'''
    for _ in range(2):
        run = subprocess.run([sys.executable, '-c', program], capture_output=True, timeout=15)
        assert run.returncode != 0
    files = list(logs.glob('support-*.jsonl'))
    assert len(files) == 2
    for path in files:
        records = read_rows(path)
        errors = [r for r in records if r['event'] == 'uncaught_exception']
        assert len(errors) == 1 and errors[0]['session'] == 'linked-session'
        assert 'out_of_memory' in errors[0]['exceptions'][0]['categories']
        assert 'PRIVATE_TRANSCRIPT' not in path.read_text(encoding='utf-8')


@pytest.mark.p1
@pytest.mark.parametrize('failed', [False, True])
def test_worker_exit_releases_diagnostic_output(logs, monkeypatch, failed):
    from linguaflow import wlk_worker
    protocol = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', protocol)
    monkeypatch.setattr(sys, 'stderr', io.StringIO())
    monkeypatch.setattr(sys, 'stdin', io.StringIO('{"_log_session":"worker-test"}\n'))
    monkeypatch.setattr(diag, 'install_exception_hooks', lambda: None)
    monkeypatch.setattr(wlk_worker, 'prepare_runtime', lambda: None)
    monkeypatch.setattr(wlk_worker, 'release_runtime_models', lambda: None)
    async def serve(*args):
        diag.event('asr_decode_end', decode_id=1, window_end=.5)
        if failed:
            raise RuntimeError('private worker text')
    monkeypatch.setattr(wlk_worker, 'serve', serve)
    if failed:
        with pytest.raises(SystemExit):
            wlk_worker.main()
    else:
        wlk_worker.main()
    assert 'asr_timing' in protocol.getvalue()
    protocol.close()
    # A new task cannot publish into a released worker's closed protocol.
    diag.event('asr_decode_end', decode_id=2)
    assert diag._handler is None
    rows = read_rows(next(logs.glob('support-*.jsonl')))
    assert any(r['event'] == 'worker_exception' for r in rows) == failed


@pytest.mark.p1
def test_slow_disk_is_bounded_and_recovers_without_blocking_producer(logs, monkeypatch):
    path = diag.start_logging('test')
    assert diag.flush()
    entered, release = threading.Event(), threading.Event()
    original = diag._handler.emit
    def slow(record):
        entered.set()
        assert release.wait(3)
        original(record)
    monkeypatch.setattr(diag._handler, 'emit', slow)
    try:
        diag.event('first')
        assert entered.wait(1)
        for index in range(1100):
            diag.event('queued', index=index)
        assert diag._writer.pending.qsize() == 1024
        assert '积压' in diag.log_error()
        assert not diag.flush(timeout=.01)
    finally:
        release.set()
    assert diag.flush()
    diag.event('recovered')
    rows = read_rows(path)
    assert rows[-1]['event'] == 'recovered'
    assert rows[-1]['dropped_events'] == 76
    diag.close_logging()
    assert json.loads(path.read_text(encoding='utf-8').splitlines()[-1])['event'] == 'process_log_close'


@pytest.mark.p0
def test_invalid_metadata_sink_and_console_never_break_logging(logs, monkeypatch):
    path = diag.start_logging('test')
    class Private:
        def __repr__(self):
            raise AssertionError('must not stringify arbitrary objects')
    class BrokenConsole:
        def write(self, value):
            raise OSError('closed')
    def fail(row):
        raise ValueError('PRIVATE')
    monkeypatch.setattr(sys, 'stderr', BrokenConsole())
    diag.set_sink(fail)
    diag.event('asr_decode_end', value=Private(), infinite=float('inf'), long='x' * 1000)
    diag.event('oversized', values=['x' * 512] * 32)
    rows = read_rows(path)
    assert rows[-2]['value'] is None and rows[-2]['infinite'] is None
    assert len(rows[-2]['long']) == 512
    assert rows[-1]['metadata_omitted']
    assert 'PRIVATE' not in path.read_text(encoding='utf-8')


@pytest.mark.p0
def test_actions_correlate_results_without_arguments_and_progress_is_coalesced(logs):
    path = diag.start_logging('test')
    def callback():
        diag.event('result')
        return False
    assert diag.action('recording.start', callback)(True) is False
    for _ in range(20):
        diag.periodic('progress', key='task')
    diag.clear_session('test-session')
    diag.event('after_session')
    rows = read_rows(path)
    action, result, dispatched = rows[1:4]
    assert action['operation'] == result['operation'] == dispatched['operation']
    assert dispatched['outcome'] == 'rejected'
    assert sum(r['event'] == 'progress' for r in rows) == 1
    assert rows[-1]['session'] is None and rows[-1]['operation'] is None


@pytest.mark.p0
def test_retention_preserves_live_and_unrelated_files(logs, monkeypatch):
    logs.mkdir()
    live = logs / f'support-desktop-20000101T000000-{os.getpid()}-12345678.jsonl'
    unrelated = logs / 'support-unrelated.jsonl'
    for path in (live, unrelated):
        path.write_text('preserve', encoding='utf-8')
        os.utime(path, (time.time() - 15 * 86400,) * 2)
    diag.start_logging('test')
    assert live.exists() and unrelated.exists()


@pytest.mark.p1
def test_worker_logging_does_not_require_desktop_psutil(logs, monkeypatch):
    monkeypatch.setitem(sys.modules, 'psutil', None)
    path = diag.start_logging('worker')
    diag.event('worker_ready')
    assert read_rows(path)[-1]['event'] == 'worker_ready'


@pytest.mark.p2
def test_directory_budget_removes_oldest_inactive_logs(logs):
    logs.mkdir()
    paths = [logs / f'support-desktop-20261020T000000-999999999-{index:08x}.jsonl'
             for index in range(2)]
    for index, path in enumerate(paths):
        with path.open('wb') as stream:
            stream.truncate(65 * 1024 * 1024)
        os.utime(path, (time.time() - 100 + index,) * 2)
    diag.start_logging('test')
    assert not paths[0].exists() and paths[1].exists()


@pytest.mark.p1
def test_default_budget_readable_severity_and_idle_shutdown(logs):
    path = diag.start_logging('test')
    assert diag._handler.maxBytes == 8 * 1024 * 1024
    assert diag._handler.backupCount == 3  # Current file plus three backups = 32 MiB.
    diag.event('preparation_started', stage='准备模型')
    diag.exception('preparation_failed', ValueError('PRIVATE'))
    rows = read_rows(path)
    assert rows[-2]['level'] == 'INFO' and rows[-1]['level'] == 'ERROR'
    assert '准备模型' in path.read_text(encoding='utf-8')
    writer = diag._writer
    # The idle writer blocks on its queue; close must wake it and retain the tail.
    diag.close_logging()
    assert not writer.is_alive()
    assert json.loads(path.read_text(encoding='utf-8').splitlines()[-1])['event'] == 'process_log_close'
