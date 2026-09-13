import asyncio
from dataclasses import replace

from linguaflow.core import Caption
from linguaflow.translation_queue import TranslationQueue
from linguaflow.translation_queue import translation_is_current


def test_new_revision_replaces_queued_work_and_can_follow_inflight_work():
    async def exercise():
        queue = TranslationQueue()
        first = Caption(1, 0, 1, "old", "en", final=False, ready=True)
        queue.put_nowait(first)
        second = replace(first, source="correct", revision=2)
        queue.put_nowait(second)
        assert queue.qsize() == 1
        item, _ = await queue.get()
        assert item == second
        queue.put_nowait(replace(second, final=True, revision=3))
        queue.task_done()
        item, _ = await queue.get()
        assert item.final
        queue.task_done()
        await queue.join()
    asyncio.run(exercise())


def test_inflight_result_cannot_overwrite_new_version_even_if_text_returns():
    old = Caption(1, 0, 1, 'original', 'en', revision=1, ready=True)
    assert translation_is_current(old, old)
    assert not translation_is_current(replace(old, revision=3), old)
    assert not translation_is_current(replace(old, source='', revision=2), old)
    assert not translation_is_current(None, old)
