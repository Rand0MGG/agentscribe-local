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

            def update(self, snapshot, done=False):
                if not source_ready.is_set() or self.previous:
                    return []
                row = Caption(1, 0, 1, 'Submitted source.', 'en', ready=True)
                self.previous[row.id] = row
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
