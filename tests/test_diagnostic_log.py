import io
import json
import os
import subprocess
import sys
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
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def test_rotation_retention_and_private_exception(logs):
    logs.mkdir()
    stale = logs / 'support-desktop-old.jsonl'
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
    assert not stale.exists() and unrelated.exists()
    files = list(logs.glob('support-*'))
    assert len(files) <= 3
    raw = ''.join(p.read_text(encoding='utf-8') for p in files)
    assert 'SECRET' not in raw and 'private transcript' not in raw and 'private-name' not in raw
    row = read_rows(path)[-1]
    assert row['session'] == 'test-session'
    assert row['exceptions'][0]['type'] == 'ValueError'
    assert row['exceptions'][0]['frames'][-1]['function'] == 'test_rotation_retention_and_private_exception'


def test_log_write_failure_does_not_break_application(logs, monkeypatch):
    diag.start_logging('test')
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(diag._handler, 'shouldRollover', fail)
    diag.event('recording_continues')
    assert '写入失败' in diag.log_error()


def test_log_creation_failure_visible_without_throwing(logs):
    logs.write_text('not a directory', encoding='utf-8')
    assert diag.start_logging('test') is None
    assert '无法创建' in diag.log_error()


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
