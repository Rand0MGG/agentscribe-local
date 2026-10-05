"""Long recording history must never become an unbounded model background."""
import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from linguaflow.backends import HyMtTranslator
from linguaflow.core import Caption
from linguaflow.llama_translation import LlamaTranslator
from linguaflow.translation_context import ContextPlanner, TranslationContext
from linguaflow.translation_models import batch_translation_prompt, fit_translation_prompt, translation_prompt
from linguaflow.translation_queue import TranslationQueue
from linguaflow.translation_service import (
    publish_translation_batch,
    publish_translation_result,
    run_translations,
)


def translator_fixture(engine, output):
    """Exercise production prompt/generation methods with only model IO replaced."""
    prompts, generated = [], []
    if engine == 'llama':
        translator = LlamaTranslator.__new__(LlamaTranslator)
        translator.closed = False
        translator.process = SimpleNamespace(poll=lambda: None)

        def request(path, payload):
            if path == '/apply-template':
                prompts.append(payload['messages'][0]['content'])
                return {'prompt': prompts[-1]}
            if path == '/tokenize':
                return {'tokens': [1] * 100}
            assert path == '/v1/chat/completions'
            generated.append(payload['messages'][0]['content'])
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': output}}]}

        translator.request = request
    else:
        translator = HyMtTranslator.__new__(HyMtTranslator)

        class Inputs(dict):
            def to(self, device):
                return self

        def template(messages, **kwargs):
            prompts.append(messages[0]['content'])
            return Inputs(input_ids=SimpleNamespace(shape=(1, 100)))

        def generate(**kwargs):
            generated.append(prompts[-1])
            return [[0] * 100 + [7, 2]]

        translator.tokenizer = SimpleNamespace(apply_chat_template=template, decode=lambda *a, **k: output)
        translator.model = SimpleNamespace(device='cpu', generate=generate,
                                          generation_config=SimpleNamespace(eos_token_id=2))
        translator.torch = SimpleNamespace(inference_mode=nullcontext)
    translator.target, translator.source = 'zho_Hans', 'eng_Latn'
    translator.report = lambda _: None
    translator.close = lambda: None
    return translator, prompts, generated


@pytest.mark.parametrize('engine', ['pytorch', 'llama'])
@pytest.mark.parametrize('before', [0, 1, 3, 10])
@pytest.mark.parametrize('final', [False, True])
@pytest.mark.parametrize('batch_size', [1, 4])
def test_long_history_model_requests_only_include_selected_neighbours(engine, before, final, batch_size):
    async def exercise():
        history = [Caption(i, i, i + 1, f'HISTORY_MARKER_{i:04d}.', 'en') for i in range(500)]
        rows = [Caption(500 + i, 500 + i, 501 + i, f'CURRENT_MARKER_{i}.', 'en',
                        final=final, ready=True) for i in range(batch_size)]
        initial_before = 1 if before else 0
        planner = ContextPlanner(before, 0, initial_before)
        planner.update(history)  # Previously processed history does not need new translations.
        queue, lock = TranslationQueue(), asyncio.Lock()
        latest = {c.id: c for c in [*history, *rows]}
        for job in planner.update(latest.values()):
            queue.put_nowait(job)
        queue.put_nowait(None)
        output = (json.dumps({str(c.id): f'Translation {c.id}' for c in rows})
                  if engine == 'llama' and batch_size > 1 else 'Translation')
        translator, prompts, generated = translator_fixture(engine, output)
        published = []

        async def single(caption, context):
            await publish_translation_result(caption, latest.get, lock, published.append,
                                             context, planner.get, planner)

        async def batch(captions, contexts):
            return await publish_translation_batch(captions, contexts, latest.get, lock,
                                                   published.append, planner)

        await run_translations(queue, lambda: translator, latest.get, single, lambda _: None,
                               lambda _: None, planner.get, planner, batch)
        await asyncio.wait_for(queue.join(), 1)
        expected_calls = 1 if engine == 'llama' else batch_size
        assert len(generated) == expected_calls and len(published) == batch_size
        count = before if final else initial_before
        assert prompts == generated
        for index, prompt in enumerate(generated):
            assert '[Source Text]\n' in prompt and 'HISTORY_MARKER_0000' not in prompt
            history_count = max(0, count - index) if engine == 'pytorch' and final else count
            for i in range(500):
                assert (f'HISTORY_MARKER_{i:04d}' in prompt) == (i >= 500 - history_count)
            if engine == 'llama':
                assert all(c.source in prompt for c in rows)
            else:
                assert prompt.endswith('[Source Text]\n' + rows[index].source)
                assert 'JSON object' not in prompt
        assert all(c.source == latest[c.id].source and not c.error for c in published)

    asyncio.run(exercise())


@pytest.mark.parametrize('context', [TranslationContext(tuple('row' for _ in range(11))),
                                     TranslationContext((), ('row', 'row', 'row')),
                                     TranslationContext(('x' * 601,)),
                                     TranslationContext((), ('x' * 601,))])
@pytest.mark.parametrize(('engine', 'batch'), [('pytorch', False), ('llama', False), ('llama', True)])
def test_model_boundary_rejects_oversized_background_before_tokenization_or_generation(context, engine, batch):
    translator, prompts, generated = translator_fixture(engine, '{"1":"Translation"}')
    with pytest.raises(ValueError, match='翻译背景'):
        if batch:
            translator.translate_batch([Caption(1, 0, 1, 'Current source.', 'en')], context)
        else:
            translator.translate('Current source.', 'en', context)
    assert prompts == generated == []


def test_direct_prompt_and_budget_helpers_cannot_bypass_the_background_limit():
    context = TranslationContext(tuple(f'History {i}' for i in range(500)))
    row = Caption(1, 0, 1, 'Complete current source.', 'en')
    with pytest.raises(ValueError, match='翻译背景'):
        translation_prompt(row.source, 'zho_Hans', context)
    with pytest.raises(ValueError, match='翻译背景'):
        batch_translation_prompt([row], 'zho_Hans', context)
    with pytest.raises(ValueError, match='翻译背景'):
        fit_translation_prompt(lambda c: pytest.fail('Unbounded background must not be built'),
                               context, lambda p: 1, 8192)


@pytest.mark.parametrize('engine', ['pytorch', 'llama'])
def test_rejected_full_history_keeps_existing_translation_and_releases_the_queue(engine):
    async def exercise():
        row = Caption(1, 0, 1, 'Complete current source.', 'en', translation='Previous valid translation',
                      translation_phase='initial', translation_source='Earlier source')
        planner, queue, lock = ContextPlanner(), TranslationQueue(), asyncio.Lock()
        queue.put_nowait(planner.update([row])[0])
        queue.put_nowait(None)
        planner.contexts[row.id] = TranslationContext(tuple(f'History {i}' for i in range(500)))
        translator, prompts, generated = translator_fixture(engine, 'Unexpected translation')
        published = []

        async def single(caption, context):
            await publish_translation_result(caption, lambda _: row, lock, published.append,
                                             context, planner.get, planner)

        await run_translations(queue, lambda: translator, lambda _: row, single, lambda _: None,
                               lambda _: None, planner.get, planner)
        await asyncio.wait_for(queue.join(), 1)
        assert prompts == generated == []
        assert len(published) == 1 and '翻译背景' in published[0].error
        assert published[0].source == row.source
        assert published[0].translation == row.translation
        assert published[0].translation_phase == row.translation_phase
        assert published[0].translation_source == row.translation_source

    asyncio.run(exercise())
