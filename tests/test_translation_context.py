import asyncio
from dataclasses import replace
from threading import Event

import pytest

from linguaflow.core import Caption
from linguaflow.translation_context import ContextPlanner, TranslationContext
from linguaflow.translation_queue import TranslationQueue
from linguaflow.translation_service import publish_translation_result, run_translations


def test_neighbours_do_not_retranslate_final_rows_and_corrections_do():
    planner = ContextPlanner(1, 1)
    rows = [Caption(i, i, i+1, f'source {i}', 'en') for i in range(4)]
    assert [c.id for c in planner.update(rows[:1])] == [0]
    assert planner.get(0) == TranslationContext()
    assert [c.id for c in planner.update(rows[:2])] == [1]
    assert planner.get(0).after == ()
    assert planner.get(1).before == ('source 0',)
    assert [c.id for c in planner.update(rows)] == [2, 3]
    assert planner.update(rows) == []
    rows[1] = replace(rows[1], source='corrected', revision=2)
    assert [c.id for c in planner.update(rows)] == [1]
    assert planner.update([rows[0], *rows[2:]]) == []
    assert planner.get(1) is None


def test_first_snapshot_survives_revisions_and_final_context_is_frozen():
    planner = ContextPlanner(3, 1)
    first = Caption(1, 0, 1, 'project', 'en', final=False, ready=True)
    job = planner.update([first])[0]
    assert job.translation_phase == 'initial' and planner.get(1) == TranslationContext()
    revised = replace(first, source='plan with budget 9000', revision=4, ready=False)
    assert planner.update([revised]) == []
    assert planner.accepts(job)
    final = replace(revised, final=True, revision=5)
    neighbour = Caption(2, 2, 3, 'next', 'en', final=False, stable_source='next')
    last = planner.update([final, neighbour])[0]
    assert last.source == final.source and last.translation_phase == 'final'
    assert not planner.accepts(job)
    assert planner.get(1).after == ('next',)
    assert planner.update([final, replace(neighbour, source='different', stable_source='different')]) == []
    assert planner.get(1).after == ('next',)


def test_drafts_excluded_and_context_bounded():
    planner = ContextPlanner(3, 1)
    rows = [Caption(i, i, i+1, str(i)*1000, 'en') for i in range(6)]
    rows[-1] = replace(rows[-1], final=False, ready=False)
    planner.update(reversed(rows))
    assert planner.get(5) is None
    assert len(planner.get(4).before) == 3 and not planner.get(4).after
    assert all(len(s) == 600 for s in planner.get(4).before)
    rows[-1] = replace(rows[-1], ready=True)
    assert [c.id for c in planner.update(rows)] == [5]
    assert planner.get(5) == TranslationContext()
    rows[-1] = replace(rows[-1], final=True, revision=2)
    assert [c.id for c in planner.update(rows)] == [5]
    assert len(planner.get(5).before) == 3
    disabled = ContextPlanner(0, 0)
    disabled.update(rows)
    assert disabled.get(4) == TranslationContext()


def test_initial_inflight_can_publish_after_source_edits_then_final_supersedes():
    async def exercise():
        queue, planner, lock = TranslationQueue(), ContextPlanner(), asyncio.Lock()
        first = Caption(1, 0, 1, 'project', 'en', final=False, ready=True)
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
                return text + ' translated'
        def apply(caption):
            latest[caption.id] = caption
            results.append(caption)
        async def publish(result, context):
            await publish_translation_result(result, latest.get, lock, apply, context, planner.get, planner)
        def schedule():
            for job in planner.update(latest.values()):
                queue.put_nowait(job)
        schedule()
        task = asyncio.create_task(run_translations(queue, Translator, latest.get, publish,
                                                    lambda _: None, lambda _: None, planner.get, planner))
        try:
            await asyncio.wait_for(started.wait(), 3)
            for version in range(2, 6):
                latest[1] = replace(latest[1], source=f'plan {version}', revision=version)
                schedule()
            release.set()
            await asyncio.wait_for(queue.join(), 3)
            assert len(calls) == 1
            assert results[-1].source == 'plan 5' and results[-1].translation == 'project translated'
            assert results[-1].translation_phase == 'initial'
            assert results[-1].translation_source == 'project'
            latest[1] = replace(latest[1], final=True, revision=6)
            schedule()
            await asyncio.wait_for(queue.join(), 3)
            assert len(calls) == 2 and results[-1].translation == 'plan 5 translated'
            assert results[-1].translation_phase == 'final'
            schedule()
            assert queue.qsize() == 0
            queue.put_nowait(None)
            await asyncio.wait_for(task, 3)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_final_replaces_queued_initial_and_unchanged_result_reuses_cache():
    async def exercise(replace_queued):
        queue, planner, lock = TranslationQueue(), ContextPlanner(0, 0), asyncio.Lock()
        first = Caption(1, 0, 1, 'same', 'en', final=False, ready=True)
        latest, calls, results = {1: first}, [], []
        class Translator:
            def translate(self, text, language, context):
                calls.append(text)
                return 'translated'
        async def publish(result, context):
            await publish_translation_result(result, latest.get, lock, results.append, context, planner.get, planner)
        queue.put_nowait(planner.update(latest.values())[0])
        task = None
        if not replace_queued:
            task = asyncio.create_task(run_translations(queue, Translator, latest.get, publish,
                lambda _: None, lambda _: None, planner.get, planner))
            await asyncio.wait_for(queue.join(), 3)
        latest[1] = replace(first, final=True, revision=2)
        queue.put_nowait(planner.update(latest.values())[0])
        if task is None:
            task = asyncio.create_task(run_translations(queue, Translator, latest.get, publish,
                lambda _: None, lambda _: None, planner.get, planner))
        queue.put_nowait(None)
        await asyncio.wait_for(task, 3)
        await asyncio.wait_for(queue.join(), 3)
        assert calls == ['same']
        assert results[-1].translation_phase == 'final'
    asyncio.run(exercise(True))
    asyncio.run(exercise(False))


@pytest.mark.parametrize('delete', [False, True])
def test_finalization_or_deletion_discards_late_initial(delete):
    async def exercise():
        queue, planner, lock = TranslationQueue(), ContextPlanner(), asyncio.Lock()
        latest = {1: Caption(1, 0, 1, 'initial source', 'en', final=False, ready=True)}
        initial = planner.update(latest.values())[0]
        queue.put_nowait(initial)
        started, release = asyncio.Event(), Event()
        loop, results = asyncio.get_running_loop(), []
        class Translator:
            def translate(self, text, language, context):
                if text == initial.source:
                    loop.call_soon_threadsafe(started.set)
                    assert release.wait(5)
                return text + ' translated'
        async def publish(result, context):
            await publish_translation_result(result, latest.get, lock, results.append, context, planner.get, planner)
        task = asyncio.create_task(run_translations(queue, Translator, latest.get, publish,
            lambda _: None, lambda _: None, planner.get, planner))
        try:
            await asyncio.wait_for(started.wait(), 3)
            if delete:
                latest.clear()
            else:
                latest[1] = replace(latest[1], final=True, source='final source', revision=2)
            for job in planner.update(latest.values()):
                queue.put_nowait(job)
            # Source already final while the initial translation is still blocked.
            assert delete or latest[1].final
            release.set()
            await asyncio.wait_for(queue.join(), 3)
            assert all(r.translation_phase == 'final' for r in results)
            assert len(results) == (0 if delete else 1)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_empty_final_translation_keeps_initial_and_marks_failure():
    async def exercise():
        queue, planner, lock = TranslationQueue(), ContextPlanner(), asyncio.Lock()
        current = Caption(1, 0, 2, 'final source', 'en', translation='old translation',
                          translation_phase='initial', translation_source='old source')
        latest, results = {1: current}, []
        class Translator:
            def translate(self, *args):
                return '  '
        async def publish(result, context):
            await publish_translation_result(result, latest.get, lock, results.append, context, planner.get, planner)
        queue.put_nowait(planner.update(latest.values())[0])
        queue.put_nowait(None)
        await run_translations(queue, Translator, latest.get, publish,
            lambda _: None, lambda _: None, planner.get, planner)
        await queue.join()
        assert results[0].translation == 'old translation'
        assert results[0].translation_phase == 'initial' and results[0].error
        assert results[0].source == 'final source' and results[0].final
    asyncio.run(exercise())
