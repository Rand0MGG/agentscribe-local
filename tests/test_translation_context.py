import asyncio
from dataclasses import replace
from threading import Event

from linguaflow.core import Caption
from linguaflow.translation_context import ContextPlanner, TranslationContext
from linguaflow.translation_queue import TranslationQueue
from linguaflow.translation_service import publish_translation_result, run_translations


def test_neighbours_revisions_deletion_and_tail():
    planner = ContextPlanner(1, 1)
    rows = [Caption(i, i, i+1, f'source {i}', 'en') for i in range(4)]
    assert planner.update(rows[:1]) == rows[:1]  # No wait for future speech.
    assert planner.get(0) == TranslationContext()
    assert planner.update(rows[:2]) == rows[:2]
    assert planner.get(0).after == ('source 1',)
    assert planner.get(1).before == ('source 0',)
    assert planner.update(rows) == rows[1:]
    assert planner.update(rows) == []
    rows[1] = replace(rows[1], source='corrected', revision=2)
    assert planner.update(rows) == rows[:3]  # Distant captions are not retransmitted.
    assert planner.update([rows[0], *rows[2:]]) == [rows[0], rows[2]]
    assert planner.get(1) is None
    # Stop/final metadata never requires a future segment to flush the tail.
    assert planner.update([replace(c, final=True) for c in [rows[0], *rows[2:]]]) == []


def test_drafts_are_excluded_and_context_is_bounded():
    planner = ContextPlanner(3, 1)
    rows = [Caption(i, i, i+1, str(i)*1000, 'en') for i in range(6)]
    rows[-1] = replace(rows[-1], final=False, ready=False)
    planner.update(reversed(rows))
    assert planner.get(5) is None
    assert len(planner.get(4).before) == 3 and not planner.get(4).after
    assert all(len(s) == 600 for s in planner.get(4).before)
    rows[-1] = replace(rows[-1], source='partial changed')
    assert planner.update(rows) == []
    rows[-1] = replace(rows[-1], ready=True)
    assert planner.update(rows) == rows[-2:]
    disabled = ContextPlanner(0, 0)
    disabled.update(rows)
    assert disabled.get(4) == TranslationContext()


def test_inflight_context_is_rejected_and_cache_includes_context():
    async def exercise():
        queue, planner, lock = TranslationQueue(), ContextPlanner(), asyncio.Lock()
        first = Caption(1, 0, 1, 'It was heavy.', 'en')
        latest = {1: first}
        calls, results = [], []
        started, release = asyncio.Event(), Event()
        loop = asyncio.get_running_loop()

        class Translator:
            def translate(self, text, language, context):
                calls.append((text, context))
                if len(calls) == 1:
                    loop.call_soon_threadsafe(started.set)
                    assert release.wait(5)
                return 'new' if context.after else 'old'

        async def publish(result, context):
            await publish_translation_result(result, latest.get, lock, results.append, context, planner.get)

        for caption in planner.update(latest.values()):
            queue.put_nowait(caption)
        task = asyncio.create_task(run_translations(queue, Translator, latest.get, publish,
                                                    lambda _: None, lambda _: None, planner.get))
        try:
            await asyncio.wait_for(started.wait(), 3)
            latest[2] = Caption(2, 1, 2, 'The suitcase was full.', 'en')
            for caption in planner.update(latest.values()):
                queue.put_nowait(caption)
            release.set()
            await asyncio.wait_for(queue.join(), 3)
            queue.put_nowait(None)
            await asyncio.wait_for(task, 3)
            assert len(calls) == 3
            assert [c.translation for c in results if c.id == 1] == ['new']
            assert calls[1][1].after == ('The suitcase was full.',)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())
