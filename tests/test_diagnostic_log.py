import asyncio
import gzip
import io
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
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


def log_text(path):
    return gzip.decompress(path.read_bytes()).decode('utf-8') if path.suffix == '.gz' else path.read_text(encoding='utf-8')


def read_rows(path):
    assert diag.flush()
    paths = [path] if path.exists() else list(path.parent.glob(path.name + '*.gz'))
    assert paths
    return sorted([json.loads(line) for part in paths for line in log_text(part).splitlines()],
                  key=lambda row: row['monotonic'])


@pytest.mark.p0
def test_rotation_retention_and_private_exception(logs):
    logs.mkdir()
    stale = logs / 'support-desktop-20000101T000000-999999999-12345678.jsonl'
    stale.write_text('old', encoding='utf-8')
    os.utime(stale, (time.time() - 15 * 86400,) * 2)
    unrelated = logs / 'keep.txt'
    unrelated.write_text('keep', encoding='utf-8')
    live = logs / f'support-desktop-20000101T000000-{os.getpid()}-12345678.jsonl'
    live.write_bytes(b'live evidence')
    path = diag.start_logging('test', max_bytes=1800)
    for i in range(30):
        diag.event('progress', index=i)
    try:
        raise ValueError('private transcript api_key=SECRET C:/Users/private-name/recording.wav')
    except ValueError as exc:
        diag.exception('failure', exc)
    assert diag.flush()
    assert not stale.exists() and unrelated.read_text() == 'keep'
    assert live.read_bytes() == b'live evidence'
    assert gzip.decompress(Path(str(stale) + '.gz').read_bytes()) == b'old'
    files = list(logs.glob(path.name + '*'))
    assert len(files) > 4  # No per-process count cap; the old record is retained too.
    raw = ''.join(log_text(p) for p in files)
    all_rows = [json.loads(line) for line in raw.splitlines()]
    assert sorted(r['index'] for r in all_rows if r['event'] == 'progress') == list(range(30))
    assert 'SECRET' not in raw and 'private transcript' not in raw and 'private-name' not in raw
    for file in files:
        for line in log_text(file).splitlines():
            record = json.loads(line)
            assert record['schema'] == 3 and record['session'] == 'test-session'
            assert record['pid'] == os.getpid() and record['role'] == 'test'
            assert record['utc'] and record['monotonic'] and record['thread']
            assert line == diag.encode_record(record)  # Self-contained even without the first file.
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
    files = list(logs.glob('support-*.jsonl*.gz'))
    assert len(files) == 2
    for path in files:
        records = read_rows(path)
        errors = [r for r in records if r['event'] == 'uncaught_exception']
        assert len(errors) == 1 and errors[0]['session'] == 'linked-session'
        assert 'out_of_memory' in errors[0]['exceptions'][0]['categories']
        assert 'PRIVATE_TRANSCRIPT' not in log_text(path)


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
    rows = read_rows(next(logs.glob('support-*.jsonl*.gz')))
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
    assert read_rows(path)[-1]['event'] == 'process_log_close'


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


@pytest.mark.p1
def test_worker_logging_does_not_require_desktop_psutil(logs, monkeypatch):
    monkeypatch.setitem(sys.modules, 'psutil', None)
    path = diag.start_logging('worker')
    diag.event('worker_ready')
    assert read_rows(path)[-1]['event'] == 'worker_ready'


@pytest.mark.p1
def test_default_budget_readable_severity_and_idle_shutdown(logs):
    path = diag.start_logging('test')
    assert diag._handler.maxBytes == 8 * 1024 * 1024
    assert diag._handler.backupCount == 0  # History uses compressed bytes, not a file count.
    assert diag._handler.history_bytes == 128 * 1024 * 1024
    diag.event('preparation_started', stage='准备模型')
    diag.exception('preparation_failed', ValueError('PRIVATE'))
    rows = read_rows(path)
    assert rows[-2]['level'] == 'INFO' and rows[-1]['level'] == 'ERROR'
    assert '准备模型' in path.read_text(encoding='utf-8')
    writer = diag._writer
    # The idle writer blocks on its queue; close must wake it and retain the tail.
    diag.close_logging()
    assert not writer.is_alive()
    assert read_rows(path)[-1]['event'] == 'process_log_close'


@pytest.mark.p0
def test_pipeline_trace_links_audio_source_sat_and_translation_without_content(logs):
    from linguaflow.qwen_revisions import install_revision_bridge
    from linguaflow.semantic_model import SemanticModel
    from linguaflow.translation_context import ContextPlanner
    from linguaflow.translation_queue import TranslationQueue
    from linguaflow.translation_service import publish_translation_result, run_translations
    from linguaflow.wlk_captions import CaptionMapper

    path = diag.start_logging('test')
    source = 'PRIVATE_SOURCE_MARKER alpha beta. PRIVATE_SECOND_MARKER gamma delta.'
    asr = QwenAccurateOnline(lambda _: source, lambda audio, _: len(audio), 'en',
                            token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.zeros(32000), 2.)
    asr.process_iter()
    asr.finish()
    snapshot = {}
    store.augment_snapshot(snapshot)
    semantic = SemanticModel.__new__(SemanticModel)
    def split(text, **kwargs):
        point = text.index('PRIVATE_SECOND_MARKER')
        return [text[:point], text[point:]]
    semantic.model = SimpleNamespace(split=split)
    mapper = CaptionMapper('en', predictor=semantic.boundaries)
    planner, queue = ContextPlanner(), TranslationQueue()
    applied = []

    async def exercise():
        with diag.trace_scope(mapping_id='mapping-test', **snapshot['_diagnostic_source']):
            captions = await asyncio.to_thread(mapper.update, snapshot, done=True)
            for caption in planner.update_changes(captions):
                queue.put_nowait(caption)
        queue.put_nowait(None)
        class Translator:
            def translate(self, text, language, context):
                return 'PRIVATE_TRANSLATION_MARKER'
        lock = asyncio.Lock()
        async def publish(caption, context):
            await publish_translation_result(caption, mapper.previous.get, lock, applied.append,
                                             context, planner.get, planner)
        await run_translations(queue, Translator, mapper.previous.get, publish, lambda _: None,
                               lambda _: None, planner.get, planner)
        await asyncio.wait_for(queue.join(), 1)
    asyncio.run(exercise())
    assert [c.source for c in applied] == ['PRIVATE_SOURCE_MARKER alpha beta.',
                                         'PRIVATE_SECOND_MARKER gamma delta.']
    assert all(c.translation == 'PRIVATE_TRANSLATION_MARKER' and c.final for c in applied)
    rows = read_rows(path)
    source_row = [r for r in rows if r['event'] == 'source_revision'][-1]
    assert source_row['decode_id'] == 1 and source_row['audio_end'] == 2 and source_row['closed']
    mapping = next(r for r in rows if r['event'] == 'caption_mapping_end')
    assert mapping['source_version'] == source_row['source_version']
    assert mapping['source_stream'] == source_row['source_stream']
    sat = next(r for r in rows if r['event'] == 'sat_call_start')
    result = next(r for r in rows if r['event'] == 'sat_call_end')
    assert sat['mapping_id'] == 'mapping-test' and result['sat_call_id'] == sat['sat_call_id']
    assert result['model']['threshold'] == .5 and result['model']['cleaned_chars'] > 0
    assert result['model']['elapsed_seconds'] >= 0 and result['model']['started_monotonic'] > 0
    assert not any(r['event'].startswith('sat_model_') for r in rows)
    queued = [r for r in rows if r['event'] == 'translation_queued']
    assert len(queued) == 2
    for task in queued:
        assert task['mapping_id'] == 'mapping-test' and task['source_version'] == source_row['source_version']
        lifecycle = [r for r in rows if r.get('translation_task_id') == task['translation_task_id']
                     or any(m['translation_task_id'] == task['translation_task_id'] for m in r.get('members', []))]
        assert [r['event'] for r in lifecycle] == ['translation_queued', 'translation_dequeued',
            'translation_batch_start', 'translation_batch_compute_end', 'translation_publication', 'translation_batch_end']
        assert lifecycle[-2]['outcome'] == 'applied'
    assert 'PRIVATE_' not in path.read_text(encoding='utf-8')
    assert diag.trace_fields() == {}


@pytest.mark.p1
def test_trace_explains_frozen_prefix_without_changing_confirmation(logs):
    path = diag.start_logging('test')
    values = iter(['one two three four five six seven eight nine ten eleven twelve'] +
                  ['three four five six seven eight nine ten eleven twelve thirteen'] * 3)
    asr = QwenAccurateOnline(lambda _: next(values), lambda audio, _: 8 * 16000, 'en',
                            window_seconds=8, token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    for duration, end in [(13, 13), (2, 15), (2, 17), (2, 19)]:
        asr.insert_audio_chunk(np.ones(duration * 16000), end)
        asr.process_iter()
    row = [r for r in read_rows(path) if r['event'] == 'asr_revision'][-1]
    assert row['candidate_stable_chars'] > 0 and row['stable_chars'] == asr.confirmed_end == 0
    assert row['confirmation_limited'] and row['confirmation_limits'] == ['frozen_prefix']
    assert row['frozen_limit'] == 0 and row['window_text_start'] > 0
    assert row['agreement']['reason'] == 'agreement_prefix'


@pytest.mark.p0
def test_sat_trace_preserves_all_offsets_cache_origin_and_failure_privacy(logs):
    from linguaflow.wlk_captions import BoundaryPolicy
    path = diag.start_logging('test')
    calls = []
    def predict(text):
        calls.append(text)
        return list(range(1, 81))
    policy = BoundaryPolicy(predict)
    source = 'PRIVATE_BOUNDARY_MARKER' * 5
    first = policy.split(source, source_offset=100)
    before_cache = read_rows(path)
    assert policy.split(source, source_offset=200) == first and len(calls) == 1
    rows = read_rows(path)
    assert rows == before_cache  # Reusing cached boundaries alone is not a log event.
    start = next(r for r in rows if r['event'] == 'sat_call_start')
    hit = policy.trace_uses[-1]
    assert hit['cache_hit'] and hit['split_id'] == start['split_id'] and hit['source_offset'] == 200
    accepted = [r['boundaries'] if r['event'] == 'sat_call_end' else r for r in rows
                if r['event'] in ('sat_call_end', 'sat_boundaries')]
    assert [x for r in accepted for x in r['positions']] == list(range(101, 181))
    def fail(text):
        raise RuntimeError('PRIVATE_FAILURE_MARKER')
    with pytest.raises(RuntimeError):
        BoundaryPolicy(fail).split(source)
    failure = read_rows(path)[-1]
    assert failure['event'] == 'sat_call_end' and failure['outcome'] == 'failed'
    assert 'PRIVATE_' not in path.read_text(encoding='utf-8')


@pytest.mark.p1
def test_translation_trace_distinguishes_replaced_stale_applied_and_cache(logs):
    from linguaflow.core import Caption
    from linguaflow.translation_queue import TranslationQueue
    from linguaflow.translation_service import publish_translation_result, run_translations
    path = diag.start_logging('test')

    async def exercise():
        queue, lock = TranslationQueue(), asyncio.Lock()
        old = Caption(1, 0, 1, 'PRIVATE_OLD', 'en', revision=1)
        new = replace(old, source='PRIVATE_NEW', revision=2)
        duplicate = replace(new, id=2)
        latest = {1: new, 2: duplicate}
        queue.put_nowait(old)
        queue.put_nowait(new)
        queue.put_nowait(duplicate)
        queue.put_nowait(None)
        calls, applied = [], []
        class Translator:
            def translate(self, text, language):
                calls.append(text)
                # Inference succeeded, but its original source is now obsolete.
                latest[1] = replace(new, source='PRIVATE_LATEST', revision=3)
                return 'PRIVATE_RESULT'
        async def publish(caption):
            await publish_translation_result(caption, latest.get, lock, applied.append)
        await run_translations(queue, Translator, latest.get, publish, lambda _: None, lambda _: None)
        await asyncio.wait_for(queue.join(), 1)
        assert calls == ['PRIVATE_NEW'] and [c.id for c in applied] == [2]
    asyncio.run(exercise())
    rows = read_rows(path)
    superseded = next(r for r in rows if r.get('outcome') == 'superseded')
    assert superseded['replaced_by'] == next(r['translation_task_id'] for r in rows
        if r['event'] == 'translation_queued' and r['caption_id'] == 1 and r['caption_revision'] == 2)
    publications = [r for r in rows if r['event'] == 'translation_publication']
    assert [r['outcome'] for r in publications] == ['rejected', 'applied']
    assert [r['cache_hit'] for r in rows if r['event'] == 'translation_batch_compute_end'] == [False, True]
    assert 'PRIVATE_' not in path.read_text(encoding='utf-8')


@pytest.mark.p1
def test_translation_trace_closes_active_and_waiting_tasks_on_cancel(logs):
    from linguaflow.core import Caption
    from linguaflow.translation_queue import TranslationQueue
    from linguaflow.translation_service import run_translations
    path = diag.start_logging('test')

    async def exercise():
        queue, started, release = TranslationQueue(), asyncio.Event(), threading.Event()
        latest = {i: Caption(i, i, i + 1, 'PRIVATE_CANCEL_MARKER', 'en') for i in (1, 2)}
        for caption in latest.values():
            queue.put_nowait(caption)
        loop = asyncio.get_running_loop()
        class Translator:
            def translate(self, *args):
                loop.call_soon_threadsafe(started.set)
                assert release.wait(3)
                return 'PRIVATE_RESULT'
        async def publish(caption):
            pytest.fail('cancelled inference must not publish')
        task = asyncio.create_task(run_translations(queue, Translator, latest.get, publish,
                                                   lambda _: None, lambda _: None))
        try:
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            result, = await asyncio.gather(task, return_exceptions=True)
            assert isinstance(result, asyncio.CancelledError)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())
    rows = read_rows(path)
    ends = [r for r in rows if r['event'] == 'translation_task_end']
    assert [(r['caption_id'], r['outcome']) for r in ends] == [
        (1, 'cancelled'), (2, 'consumer_closed_before_start')]
    assert ends[0]['inference_may_still_run']
    assert not any(r['event'] == 'translation_publication' for r in rows)
    assert 'PRIVATE_' not in path.read_text(encoding='utf-8')


@pytest.mark.p1
def test_unchanged_mapping_polls_do_not_write_logs_or_repeat_inference(logs):
    from linguaflow.wlk_captions import CaptionMapper
    path = diag.start_logging('test')
    calls, clock = [], [0.]
    prefix = 'PRIVATE_FIRST sentence.'
    def predict(text):
        calls.append(text)
        return [len(prefix)] if text.startswith(prefix) else []
    mapper = CaptionMapper('en', predictor=predict, clock=lambda: clock[0])
    snapshot = dict(revision_text=prefix + ' PRIVATE_TAIL words', stable_end=len(prefix),
                    revision_spans=[], closed_ends=[])
    assert mapper.update(snapshot)
    # Exercise the stable-row reconsideration and mutable-tail cache paths too.
    snapshot['revision_text'] += ' and more context'
    snapshot['stable_end'] = len(snapshot['revision_text'])
    mapper.update(snapshot)
    mapper.update(snapshot)
    before = read_rows(path)
    inference_count = len(calls)
    for _ in range(1000):
        assert mapper.update(snapshot) == []
    assert len(calls) == inference_count
    assert len(mapper.policy.trace_uses) == 2 and all(use['cache_hit'] for use in mapper.policy.trace_uses)
    assert read_rows(path) == before
    assert 'PRIVATE_' not in path.read_text(encoding='utf-8')


@pytest.mark.p1
def test_cached_readiness_and_finalization_changes_still_have_trace(logs):
    from linguaflow.wlk_captions import CaptionMapper
    path = diag.start_logging('test')
    calls, clock = [], [0.]
    def predict(text):
        calls.append(text)
        return []
    mapper = CaptionMapper('en', predictor=predict, clock=lambda: clock[0])
    source = 'PRIVATE_PENDING words'
    snapshot = dict(revision_text=source, stable_end=len(source), revision_spans=[], closed_ends=[])
    first, = mapper.update(snapshot)
    assert not first.ready and not first.final
    before = read_rows(path)
    for _ in range(100):
        assert mapper.update(snapshot) == []
    assert read_rows(path) == before
    clock[0] = 3.1
    ready, = mapper.update(snapshot)
    assert ready.ready and not ready.final
    records = read_rows(path)
    mapping = [r for r in records if r['event'] == 'caption_mapping_end'][-1]
    change = [r for r in records if r['event'] == 'caption_revision'][-1]
    assert change['changes'] == ['readiness'] and change['mapping_id'] == mapping['mapping_id']
    assert mapping['splits'][0]['cache_hit']
    origin = next(r for r in records if r['event'] == 'sat_call_start')
    assert mapping['splits'][0]['split_id'] == origin['split_id']
    final, = mapper.update(snapshot, done=True)
    assert final.final and len(calls) == 1
    assert [r for r in read_rows(path) if r['event'] == 'caption_mapping_end'][-1]['done']


@pytest.mark.p1
def test_actual_sat_work_and_failure_are_logged_even_without_caption_changes(logs):
    from linguaflow.wlk_captions import CaptionMapper
    path = diag.start_logging('test')
    mapper = CaptionMapper('en', predictor=lambda text: [], clock=lambda: 0.)
    snapshot = dict(revision_text='PRIVATE_PENDING', stable_end=0, revision_spans=[], closed_ends=[])
    mapper.update(snapshot)
    # Evicted/invalidated cache means real inference, even if its output agrees.
    mapper.policy.cache.clear()
    before = len(read_rows(path))
    assert mapper.update(snapshot) == []
    records = read_rows(path)[before:]
    assert any(r['event'] == 'sat_call_start' for r in records)
    assert records[-1]['event'] == 'caption_mapping_end' and records[-1]['changed_captions'] == 0
    assert not records[-1]['splits'][0]['cache_hit']
    def fail(text):
        raise RuntimeError('PRIVATE_FAILURE')
    mapper.policy.cache.clear()
    mapper.policy.predictor = fail
    with pytest.raises(RuntimeError):
        mapper.update(snapshot)
    failure = read_rows(path)[-1]
    assert failure['event'] == 'caption_mapping_end' and failure['outcome'] == 'failed'
    assert failure['error_type'] == 'RuntimeError' and failure['mapping_id']
    assert 'PRIVATE_' not in path.read_text(encoding='utf-8')


@pytest.mark.p1
def test_compact_sat_chunks_reconstruct_rejections_and_duplicates(logs):
    from linguaflow.wlk_captions import BoundaryPolicy
    path = diag.start_logging('test')
    text = 'x' * 31 + ',' + 'x' * 1168
    offsets = list(range(1, 70)) + [32, 1024, 1025, 1152]
    calls = []
    def predict(window):
        values = offsets if not calls else [1, 128, 129, len(window)]
        calls.append(values)
        return values
    policy = BoundaryPolicy(predict)
    result = policy.split(text, source_offset=500)
    rows = read_rows(path)
    ends = [r for r in rows if r['event'] == 'sat_call_end']
    accepted = set()
    for call_number, end in enumerate(ends):
        chunks = [end['boundaries']] + [r for r in rows if r['event'] == 'sat_boundaries'
                                       and r['sat_call_id'] == end['sat_call_id']]
        positions = [pos for chunk in chunks for pos in chunk['positions']]
        window_start = max(0, call_number * 1024 - 128)
        assert positions == [500 + window_start + pos for pos in calls[call_number]]
        for chunk in chunks:
            assert len(chunk['positions']) <= 32
            for index, position in enumerate(chunk['positions']):
                absolute = position - 500
                if index in chunk.get('outside_core', []):
                    assert not call_number * 1024 < absolute <= (call_number + 1) * 1024
                elif index in chunk.get('separator', []):
                    assert text[:absolute].rstrip().endswith(',')
                else:
                    accepted.add(absolute)
        assert end['candidate_count'] == len(positions)
    assert [end for end, _ in result] == sorted(accepted)
    assert sum(len(c.get('separator', [])) for r in ends for c in [r['boundaries']]) == 1
    # The duplicate comma candidate lands in a continuation chunk, not the first.
    assert any(r.get('separator') for r in rows if r['event'] == 'sat_boundaries')


@pytest.mark.p1
def test_compact_sat_failure_keeps_model_cause_and_timing(logs):
    from linguaflow.semantic_model import SemanticModel
    from linguaflow.wlk_captions import BoundaryPolicy
    path = diag.start_logging('test')
    model = SemanticModel.__new__(SemanticModel)
    def fail(*args, **kwargs):
        raise ValueError('PRIVATE_MODEL_ERROR')
    model.model = SimpleNamespace(split=fail)
    with pytest.raises(RuntimeError):
        BoundaryPolicy(model.boundaries).split('PRIVATE_SOURCE')
    rows = read_rows(path)
    end = rows[-1]
    assert end['event'] == 'sat_call_end' and end['error_type'] == 'RuntimeError'
    assert end['model']['outcome'] == 'failed' and end['model']['error_type'] == 'ValueError'
    assert end['model']['elapsed_seconds'] >= 0
    assert not any(r['event'].startswith('sat_model_') for r in rows)
    assert 'PRIVATE_' not in path.read_text(encoding='utf-8')


@pytest.mark.p1
@pytest.mark.parametrize('fail', [False, True])
def test_compact_translation_batch_keeps_each_task_and_publication(logs, fail):
    from linguaflow.core import Caption
    from linguaflow.translation_context import ContextPlanner
    from linguaflow.translation_queue import TranslationQueue
    from linguaflow.translation_service import publish_translation_batch, run_translations
    path = diag.start_logging('test')
    async def exercise():
        planner, queue, lock = ContextPlanner(), TranslationQueue(), asyncio.Lock()
        captions = [Caption(i, i, i + 1, 'PRIVATE_SOURCE', 'en') for i in range(4)]
        latest = {c.id: c for c in captions}
        jobs = planner.update(captions)
        for job in jobs:
            with diag.trace_scope(mapping_id=f'map-{job.id}', source_stream='stream', source_version=job.id):
                queue.put_nowait(job)
        queue.put_nowait(None)
        class Translator:
            def translate_batch(self, captions, context):
                if fail:
                    raise ValueError('PRIVATE_FAILURE')
                return {c.id: 'PRIVATE_RESULT' for c in captions}
        published = []
        async def publish(captions, contexts):
            return await publish_translation_batch(captions, contexts, latest.get, lock, published.append, planner)
        await run_translations(queue, Translator, latest.get, None, lambda _: None, lambda _: None,
                               planner.get, planner, publish)
        await asyncio.wait_for(queue.join(), 1)
        assert len(published) == 4 and all(bool(c.error) == fail for c in published)
    asyncio.run(exercise())
    rows = read_rows(path)
    queued = {r['translation_task_id']: r for r in rows if r['event'] == 'translation_queued'}
    batches = [r for r in rows if r['event'].startswith('translation_batch_')]
    assert [r['event'] for r in batches] == [
        'translation_batch_start', 'translation_batch_compute_end', 'translation_batch_end']
    assert len({r['translation_batch_id'] for r in batches}) == 1
    for row in batches:
        assert len(row['members']) == 4
        for member in row['members']:
            original = queued[member['translation_task_id']]
            for key in ('caption_id', 'caption_revision', 'segmentation_revision', 'phase',
                        'mapping_id', 'source_stream', 'source_version'):
                assert member[key] == original[key]
    assert all(m['failed'] == fail for m in batches[1]['members'])
    publications = [r for r in rows if r['event'] == 'translation_publication']
    assert len(publications) == 4 and all(r['outcome'] == 'applied' for r in publications)
    assert {r['caption_id'] for r in publications} == {m['caption_id'] for m in batches[0]['members']}
    assert all(r['translation_batch_id'] == batches[0]['translation_batch_id'] for r in publications)
    assert 'PRIVATE_' not in path.read_text(encoding='utf-8')


@pytest.mark.p1
def test_compression_stays_on_writer_and_producer_can_continue(logs, monkeypatch):
    from linguaflow import diagnostic_archive as archive
    entered, release = threading.Event(), threading.Event()
    original = archive._compress
    threads = []
    def slow(path):
        threads.append(threading.current_thread().name)
        entered.set()
        assert release.wait(3)
        original(path)
    monkeypatch.setattr(archive, '_compress', slow)
    diag.start_logging('test', max_bytes=700)
    try:
        for i in range(4):
            diag.event('linked', index=i, translation_task_id=f'task-{i}')
        assert entered.wait(1)
        # This returns before the compressor is released: producers only enqueue.
        diag.event('producer_continues', translation_task_id='task-after-rotation')
        assert diag._writer.pending.qsize() > 0
    finally:
        release.set()
    assert diag.flush()
    diag.close_logging()
    assert threads and set(threads) == {'support-log-writer'}
    rows = [row for path in logs.glob('*.gz') for row in read_rows(path)]
    assert sorted(r['index'] for r in rows if r['event'] == 'linked') == list(range(4))
    assert any(r.get('translation_task_id') == 'task-after-rotation' for r in rows)
