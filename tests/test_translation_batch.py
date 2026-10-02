import asyncio
import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from linguaflow.core import Caption
from linguaflow.llama_translation import LlamaTranslator
from linguaflow.translation_context import ContextPlanner, TranslationContext
from linguaflow.translation_models import (
    batch_translation_prompt,
    fit_translation_prompt,
    parse_batch_translation,
)
from linguaflow.translation_queue import TranslationQueue
from linguaflow.translation_service import (
    publish_translation_batch,
    publish_translation_result,
    run_translations,
)


def test_small_initial_context_and_large_final_context_only_use_final_source():
    planner = ContextPlanner()
    history = [Caption(i, i, i + 1, f'Context {i}.', 'en') for i in range(12)]
    pending = Caption(12, 12, 13, 'Unfinished neighbour.', 'en', final=False,
                      stable_source='Unfinished neighbour.')
    current = Caption(13, 13, 14, 'The current sentence.', 'en', final=False, ready=True)
    planner.update([*history, pending, current])
    assert planner.get(13) == TranslationContext(('Context 11.',))
    revised = replace(current, source='The corrected sentence.', revision=2, ready=False)
    jobs = planner.update([*history, pending, revised])
    assert len(jobs) == 1 and jobs[0].source == revised.source
    assert planner.update([*history, pending, replace(revised, revision=3)]) == []
    planner.update([*history, pending, replace(revised, final=True, revision=4)])
    assert planner.get(13).before == tuple(f'Context {i}.' for i in range(2, 12))
    assert 'Unfinished neighbour.' not in planner.get(13).before


def test_batch_queue_preserves_deferred_head_updates_and_stop_count():
    async def exercise():
        queue = TranslationQueue()
        rows = [Caption(i, i, i + 1, f'Source {i}', 'en') for i in range(3)]
        for row in rows:
            queue.put_nowait(row)
        first = await queue.get()
        batch = queue.take_batch(first, lambda left, right: True, max_rows=4, max_chars=10)
        assert len(batch) == 1 and queue.qsize() == 2
        newer = replace(rows[1], source='Revised source', revision=2)
        queue.put_nowait(newer)
        assert queue.qsize() == 2
        queue.task_done()
        next_item = await queue.get()
        assert next_item[0] == newer
        queue.task_done()
        last = await queue.get()
        queue.put_nowait(None)
        assert queue.take_batch(last, lambda left, right: True) == [last]
        queue.task_done()
        assert await queue.get() is None
        queue.task_done()
        await asyncio.wait_for(queue.join(), 1)
    asyncio.run(exercise())


def test_batch_bounds_and_phase_language_or_gap_keep_separate_requests():
    async def exercise():
        planner, queue = ContextPlanner(), TranslationQueue()
        rows = [Caption(i, i, i + 1, f'Source {i}.', 'en') for i in range(8)]
        rows[5] = replace(rows[5], language='zh')
        rows[6] = replace(rows[6], final=False, ready=True)
        jobs = planner.update(rows)
        for job in jobs:
            queue.put_nowait(job)
        queue.put_nowait(None)
        blocks = []
        while (item := await queue.get()) is not None:
            batch = queue.take_batch(item, planner.adjacent)
            blocks.append([c.id for c, _ in batch])
            for _ in batch:
                queue.task_done()
        queue.task_done()
        await asyncio.wait_for(queue.join(), 1)
        assert blocks == [[0, 1, 2, 3], [4], [5], [6], [7]]
        assert not planner.adjacent(jobs[0], jobs[2])
    asyncio.run(exercise())


@pytest.mark.parametrize('final', [False, True])
def test_adjacent_requests_share_one_context_without_losing_subtitle_alignment(final):
    async def exercise():
        planner, queue, lock = ContextPlanner(), TranslationQueue(), asyncio.Lock()
        history = [Caption(i, i, i + 1, f'Background {i}.', 'en') for i in range(10)]
        planner.update(history)
        body = [Caption(i, i, i + 1, f'Source {i}.', 'en', final=final, ready=True) for i in range(10, 13)]
        latest = {c.id: c for c in [*history, *body]}
        for job in planner.update(latest.values()):
            queue.put_nowait(job)
        calls, output, metrics = [], [], []
        class Translator:
            def translate_batch(self, captions, context):
                calls.append(([c.id for c in captions], context))
                return {c.id: f'Translation {c.id}.' for c in reversed(captions)}
            def translate(self, *args):
                pytest.fail('Adjacent segments should share one model call')
        def apply(caption):
            latest[caption.id] = caption
            output.append(caption)
        async def single(caption, context):
            await publish_translation_result(caption, latest.get, lock, apply, context, planner.get, planner)
        async def batch(captions, contexts):
            return await publish_translation_batch(captions, contexts, latest.get, lock, apply, planner)
        queue.put_nowait(None)
        await run_translations(queue, Translator, latest.get, single, lambda _: None, metrics.append,
                               planner.get, planner, batch)
        await asyncio.wait_for(queue.join(), 1)
        assert len(calls) == 1 and calls[0][0] == [10, 11, 12]
        expected = tuple(c.source for c in history) if final else (history[-1].source,)
        assert calls[0][1] == TranslationContext(expected)
        assert [c.id for c in output] == [10, 11, 12]
        assert all(c.translation == f'Translation {c.id}.' for c in output)
        assert all((c.start, c.end, c.source, c.final) == (original.start, original.end, original.source, final)
                   for c, original in zip(output, body, strict=True))
        assert metrics[0]['batch_size'] == 3
    asyncio.run(exercise())


@pytest.mark.parametrize('failure', ['inference', 'publisher', 'cancel'])
def test_batch_failure_or_cancel_releases_all_taken_tasks(failure):
    async def exercise():
        planner, queue = ContextPlanner(), TranslationQueue()
        rows = [Caption(i, i, i + 1, f'Source {i}.', 'en', translation='Previous translation',
                        translation_phase='initial') for i in range(2)]
        latest = {c.id: c for c in rows}
        for job in planner.update(rows):
            queue.put_nowait(job)
        output, closed = [], []
        entered, release, loop = asyncio.Event(), Event(), asyncio.get_running_loop()
        class Translator:
            def translate_batch(self, captions, context):
                if failure == 'inference':
                    return {captions[0].id: 'Missing the second row'}
                if failure == 'cancel':
                    loop.call_soon_threadsafe(entered.set)
                    assert release.wait(3)
                return {c.id: 'New translation' for c in captions}
            def close(self):
                closed.append(True)
        async def batch(captions, contexts):
            if failure == 'publisher':
                raise RuntimeError('Publish failed')
            return await publish_translation_batch(captions, contexts, latest.get, asyncio.Lock(), output.append, planner)
        task = asyncio.create_task(run_translations(queue, Translator, latest.get, None, lambda _: None,
                                                    lambda _: None, planner.get, planner, batch))
        try:
            if failure == 'cancel':
                await asyncio.wait_for(entered.wait(), 1)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            elif failure == 'publisher':
                with pytest.raises(RuntimeError, match='Publish failed'):
                    await task
            else:
                await asyncio.wait_for(queue.join(), 1)
                queue.put_nowait(None)
                await task
                assert len(output) == 2 and all(c.error for c in output)
                assert all(c.translation == 'Previous translation' and c.translation_phase == 'initial' for c in output)
            await asyncio.wait_for(queue.join(), 1)
            assert closed == [True]
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_source_change_during_batch_requeues_valid_members_and_rejects_all_old_results():
    async def exercise():
        planner, queue, lock = ContextPlanner(), TranslationQueue(), asyncio.Lock()
        rows = [Caption(i, i, i + 1, f'Source {i}.', 'en') for i in range(2)]
        latest = {c.id: c for c in rows}
        for job in planner.update(rows):
            queue.put_nowait(job)
        calls, output = [], []
        entered, release, loop = asyncio.Event(), Event(), asyncio.get_running_loop()
        class Translator:
            def translate_batch(self, captions, context):
                calls.append(tuple(c.source for c in captions))
                if len(calls) == 1:
                    loop.call_soon_threadsafe(entered.set)
                    assert release.wait(3)
                return {c.id: c.source + ' translated' for c in captions}
        def apply(caption):
            latest[caption.id] = caption
            output.append(caption)
        async def batch(captions, contexts):
            return await publish_translation_batch(captions, contexts, latest.get, lock, apply, planner)
        task = asyncio.create_task(run_translations(queue, Translator, latest.get, None, lambda _: None,
                                                    lambda _: None, planner.get, planner, batch))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            latest[0] = replace(latest[0], source='Corrected first sentence.', revision=2)
            for job in planner.update(latest.values()):
                queue.put_nowait(job)
            release.set()
            await asyncio.wait_for(queue.join(), 2)
            assert len(calls) == 2 and len(output) == 2
            assert output[0].source == latest[0].source
            assert output[1].source == rows[1].source
            assert all(c.translation == c.source + ' translated' for c in output)
            queue.put_nowait(None)
            await asyncio.wait_for(task, 1)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


@pytest.mark.parametrize('output', ['{}', '{"1":"one"}', '{"1":"one","2":""}',
                                    '{"1":"one","2":"two","3":"extra"}',
                                    '{"1":"one","1":"again","2":"two"}', 'not JSON'])
def test_batch_parser_rejects_missing_extra_duplicate_or_empty_segments(output):
    rows = [Caption(i, i, i + 1, 'Source', 'en') for i in (1, 2)]
    with pytest.raises(ValueError, match='合并翻译'):
        parse_batch_translation(output, rows)


def test_budget_removes_only_background_and_never_truncates_source():
    context = TranslationContext(('Old context', 'Recent context'), ('Following context',))
    prompt, trimmed = fit_translation_prompt(lambda c: '|'.join((*c.before, 'COMPLETE SOURCE', *c.after)),
                                            context, len, 50)
    assert trimmed and 'Old context' not in prompt and 'Recent context' in prompt and 'COMPLETE SOURCE' in prompt
    with pytest.raises(ValueError, match='完整原文'):
        fit_translation_prompt(lambda c: 'COMPLETE SOURCE', context, len, 2)


def test_llama_batch_uses_one_schema_constrained_generation_after_budget_checks():
    translator = LlamaTranslator.__new__(LlamaTranslator)
    translator.closed, translator.target, translator.source = False, 'zho_Hans', 'eng_Latn'
    translator.process = SimpleNamespace(poll=lambda: None)
    rows = [Caption(i, i, i + 1, f'Source {i}', 'en') for i in (1, 2)]
    calls = []
    def request(path, payload):
        calls.append(path)
        if path == '/apply-template':
            return {'prompt': payload['messages'][0]['content']}
        if path == '/tokenize':
            return {'tokens': [1] * 100}
        assert path == '/v1/chat/completions'
        assert payload['response_format']['type'] == 'json_schema'
        assert 'schema' not in payload['response_format']
        schema = payload['response_format']['json_schema']['schema']
        assert schema['required'] == ['1', '2'] and not schema['additionalProperties']
        assert 'Shared background' in payload['messages'][0]['content']
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"2":"译文二","1":"译文一"}'}}]}
    translator.request = request
    assert translator.translate_batch(rows, TranslationContext(('Shared background',))) == {1: '译文一', 2: '译文二'}
    assert calls == ['/apply-template', '/tokenize', '/v1/chat/completions']
    assert 'preserving its ID' in batch_translation_prompt(rows, 'zho_Hans')
    assert parse_batch_translation(json.dumps({'2': ' two ', '1': ' one '}), rows) == {1: 'one', 2: 'two'}
