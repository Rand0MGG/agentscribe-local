"""Live translation must progress while recognition is busy or has queued audio."""
import asyncio
import sys
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from test_shared_qwen_worker import stub_worker

from linguaflow import backends, wlk_captions, wlk_worker
from linguaflow.core import Caption, Settings
from linguaflow.translation_models import HY_MODEL


@pytest.mark.parametrize('busy', ['inference', 'backlog'])
def test_worker_publishes_translation_before_recognition_becomes_idle(monkeypatch, busy):
    _, online, _ = stub_worker(monkeypatch)
    base_processor = sys.modules['whisperlivekit'].AudioProcessor

    async def exercise():
        started, release, source_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
        stopped, translated = asyncio.Event(), asyncio.Event()
        processors, events = [], []

        class Processor(base_processor):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.active_call = None
                processors.append(self)

            async def _run_counted_transcription_call(self, method, *args):
                started.set()
                await release.wait()
                return [], 1.

            async def cleanup(self):
                release.set()
                if self.active_call:
                    await self.active_call
                await super().cleanup()

        class Mapper:
            def __init__(self, *args, **kwargs):
                self.previous = {}
                self.last_text = ''
                self.ranges = {}

            def update(self, snapshot, done=False):
                if not source_ready.is_set() or self.previous:
                    return []
                row = Caption(1, 0, 1, 'Submitted source.', 'en', ready=True)
                self.previous[row.id] = row
                self.last_text = row.source
                self.ranges[row.id] = (0, len(row.source))
                return [row]

        monkeypatch.setattr(sys.modules['whisperlivekit'], 'AudioProcessor', Processor)
        monkeypatch.setattr(wlk_captions, 'CaptionMapper', Mapper)
        monkeypatch.setattr(backends, 'create_translator', lambda *args:
                            SimpleNamespace(translate=lambda *args: '译文'))

        def emit(event):
            events.append(event)
            if event['type'] == 'caption' and event['data']['translation']:
                translated.set()

        async def read():
            processor = processors[0]
            if busy == 'inference':
                processor.active_call = asyncio.create_task(processor._run_counted_transcription_call(None))
                await started.wait()
            else:
                processor.transcription_queue.put_nowait(b'pending audio')
            source_ready.set()
            online[0].revisions.update(0, 0., 1., 'Submitted source.', len('Submitted source.'), False)
            await stopped.wait()
            return {'type': 'stop'}

        settings = Settings('fake', backend='qwen3-streaming', asr_device='cpu', source='en',
                            translate=True, translation_model=HY_MODEL)
        task = asyncio.create_task(wlk_worker.serve(asdict(settings), emit, read))
        try:
            await asyncio.wait_for(translated.wait(), 2)
            assert not stopped.is_set() and not task.done()
            processor = processors[0]
            if busy == 'inference':
                assert not processor.active_call.done() and not release.is_set()
            else:
                assert not processor.transcription_queue.empty()
            release.set()
            stopped.set()
            await asyncio.wait_for(task, 3)
            assert events[-1]['type'] == 'done'
        finally:
            release.set()
            stopped.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for processor in processors:
                if processor.active_call:
                    await asyncio.gather(processor.active_call, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize('backend', ['qwen3-streaming', 'qwen3-mlx'])
def test_worker_translates_stable_sentences_while_asr_prefix_is_frozen(monkeypatch, backend):
    from linguaflow import mlx_asr, qwen_accurate, semantic_model

    platform = 'darwin' if backend == 'qwen3-mlx' else 'win32'
    _, online, stores = stub_worker(monkeypatch, platform)
    build = qwen_accurate.build_official_online
    monkeypatch.setattr(mlx_asr, 'build_mlx_online', lambda model, language, interval, report,
        *, window_seconds, own: build(model, 'mlx', language, interval, window_seconds))
    prefix = 'This sentence needs an initial translation.'
    monkeypatch.setattr(semantic_model, 'SemanticModel', lambda: SimpleNamespace(
        boundaries=lambda text: [len(prefix)] if text.startswith(prefix) else []))
    clock = [0.]
    mapper = wlk_captions.CaptionMapper
    monkeypatch.setattr(wlk_captions, 'CaptionMapper', lambda *args, **kwargs:
        mapper(*args, **kwargs, clock=lambda: clock[0]))
    monkeypatch.setattr(backends, 'create_translator', lambda *args:
        SimpleNamespace(translate=lambda *args: '实时初译'))

    async def exercise():
        first, second, translated, stopped = (asyncio.Event() for _ in range(4))
        events = []
        def emit(event):
            events.append(event)
            if event['type'] != 'caption':
                return
            row = event['data']
            if row['source'] == prefix:
                first.set()
                if row['translation']:
                    assert not row['asr_final'] and not row['boundary_final'] and not row['final']
                    assert row['translation_phase'] == 'initial'
                    translated.set()
            if row['source'] == 'Following words keep arriving':
                second.set()
        async def read():
            store = online[0].revisions
            store.update(0, 0., 5., prefix + ' Following words', 0, False)
            await first.wait()
            clock[0] = 1.
            store.update(0, 0., 6., prefix + ' Following words keep arriving', 0, False)
            await second.wait()
            assert not translated.is_set()
            clock[0] = 3.1
            store.update(0, 0., 9., prefix + ' Following words keep arriving now', 0, False)
            await stopped.wait()
            return {'type': 'stop'}
        settings = Settings('fake', backend=backend,
            asr_device='mlx' if backend == 'qwen3-mlx' else 'cpu', source='en',
            translate=True, translation_model=HY_MODEL)
        task = asyncio.create_task(wlk_worker.serve(asdict(settings), emit, read))
        try:
            await asyncio.wait_for(translated.wait(), 2)
            assert not stopped.is_set() and not task.done()
            assert stores[0].rows[0]['stable_end'] == 0 and not stores[0].rows[0]['closed']
            stopped.set()
            await asyncio.wait_for(task, 3)
            assert events[-1]['type'] == 'done'
        finally:
            stopped.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())
