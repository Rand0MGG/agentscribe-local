import asyncio
from dataclasses import replace
from threading import Event

import pytest

from linguaflow.core import Caption
from linguaflow.translation_queue import TranslationQueue
from linguaflow.translation_service import publish_translation_result, run_translations


def test_revision_during_inference_drops_old_translation_and_drains_queue():
    async def exercise():
        first = Caption(1, 0, 1, 'old', 'en', final=False, ready=True)
        latest = {1: first}
        queue, lock = TranslationQueue(), asyncio.Lock()
        started = asyncio.Event()
        release = Event()
        loop = asyncio.get_running_loop()
        calls, results, metrics = [], [], []

        class Translator:
            def translate(self, text, language):
                calls.append(text)
                if text == 'old':
                    loop.call_soon_threadsafe(started.set)
                    assert release.wait(5), 'test must release inference'
                return text + ' translated'

        async def publish(caption):
            await publish_translation_result(caption, latest.get, lock, results.append)

        queue.put_nowait(first)
        task = asyncio.create_task(run_translations(queue, Translator, latest.get, publish,
                                                    lambda _: None, metrics.append))
        try:
            await asyncio.wait_for(started.wait(), 3)
            latest[1] = replace(first, source='correct', revision=2, final=True)
            queue.put_nowait(latest[1])
            release.set()
            await asyncio.wait_for(queue.join(), 3)
            queue.put_nowait(None)
            await asyncio.wait_for(task, 3)
            await asyncio.wait_for(queue.join(), 3)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert calls == ['old', 'correct']
        assert len(results) == 1 and results[0].source == 'correct'
        assert results[0].translation == 'correct translated' and results[0].final
        assert len(metrics) == 2
    asyncio.run(exercise())


def test_load_failure_preserves_source_and_reports_each_caption():
    async def exercise():
        queue, lock = TranslationQueue(), asyncio.Lock()
        caption = Caption(1, 0, 1, 'keep original', 'en')
        latest, results, statuses, metrics = {1: caption}, [], [], []

        def unavailable():
            raise RuntimeError('missing model')

        async def publish(result):
            await publish_translation_result(result, latest.get, lock, results.append)

        queue.put_nowait(caption)
        queue.put_nowait(None)
        await run_translations(queue, unavailable, latest.get, publish, statuses.append, metrics.append)
        await asyncio.wait_for(queue.join(), 1)
        assert results[0].source == caption.source and results[0].error == 'missing model'
        assert 'missing model' in statuses[0] and metrics[0]['error'] == 'missing model'
        assert caption.error == ''  # Published results never mutate ASR state.
    asyncio.run(exercise())


def test_publication_uses_latest_metadata_and_releases_lock_on_error():
    async def exercise():
        requested = Caption(1, 0, 1, 'text', 'en', translation='译文')
        latest = {1: replace(requested, end=2, translation='')}
        results, lock = [], asyncio.Lock()
        await publish_translation_result(requested, latest.get, lock, results.append)
        assert results[0].end == 2 and results[0].translation == '译文'
        latest[1] = replace(latest[1], source='', revision=2)
        await publish_translation_result(requested, latest.get, lock, results.append)
        assert len(results) == 1

        queue = TranslationQueue()
        queue.put_nowait(requested)

        class Translator:
            def translate(self, *args):
                return 'result'

        async def fail_publish(result):
            raise OSError('closed pipe')

        with pytest.raises(OSError, match='closed pipe'):
            await run_translations(queue, Translator, lambda _: requested, fail_publish,
                                   lambda _: None, lambda _: None)
        await asyncio.wait_for(queue.join(), 1)
        assert not lock.locked()
    asyncio.run(exercise())
