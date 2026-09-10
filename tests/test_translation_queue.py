import asyncio
from dataclasses import replace

from linguaflow.core import Caption
from linguaflow.translation_queue import TranslationQueue


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
