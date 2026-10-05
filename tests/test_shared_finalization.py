"""The shared pipeline must not confuse ASR agreement, SaT closure and HY work."""
import asyncio
from dataclasses import asdict, replace
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.asr_stability import StablePrefix, choose_cut, stitch_window
from linguaflow.core import Caption, source_is_final
from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_revisions import install_revision_bridge
from linguaflow.translation_context import ContextPlanner
from linguaflow.translation_queue import TranslationQueue
from linguaflow.translation_service import publish_translation_result
from linguaflow.wlk_captions import CaptionMapper


def snapshot(text, stable=None):
    return {'revision_text': text, 'stable_end': len(text) if stable is None else stable,
            'revision_spans': [], 'closed_ends': []}


def test_agreement_requires_distinct_audio_and_each_new_word_ages_independently():
    agreement = StablePrefix(holdback=0)
    assert agreement.observe('old words', 1) == 0
    for _ in range(20):
        assert agreement.observe('old words', 1) == 0
    assert agreement.observe('old words', 3) == 0
    assert agreement.observe('old words newly spoken', 5) == len('old words')
    assert agreement.observe('old words newly spoken', 7) == len('old words')
    assert agreement.observe('old words newly spoken', 9) == len('old words newly spoken')
    assert agreement.observe('corrected words newly spoken', 10) == 0


@pytest.mark.parametrize('previous,current,expected,result', [
    ('We use soft mass for this vector', 'softmax for this vector and then normalize', 7,
     'We use softmax for this vector and then normalize'),
    ('The first sentence ends. The next starts here', 'The next starts here and continues', 25,
     'The first sentence ends. The next starts here and continues'),
    ('我们先讨论概率模型然后看这个公式', '然后看这个公式的推导过程', 9,
     '我们先讨论概率模型然后看这个公式的推导过程'),
])
def test_overlap_revises_tail_without_repeating_matching_words(previous, current, expected, result):
    merged, start, anchored = stitch_window(previous, current, expected)
    assert anchored and merged == result and start <= len(merged)


def test_capacity_one_decode_never_confirms_punctuated_fragment():
    asr = QwenAccurateOnline(lambda audio: 'So we want to.', choose_cut, 'en', window_seconds=8,
                            pause_context_seconds=3, token_type=SimpleNamespace,
                            transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(13 * 16000), 13)
    assert asr.process_iter()[0] == []
    assert store.rows[0]['stable_end'] == 0 and not store.rows[0]['closed']
    data = {}
    store.augment_snapshot(data)
    mapper = CaptionMapper('en', predictor=lambda text: [])
    row = mapper.update(data)[0]
    assert not row.asr_final and not row.boundary_final and not row.final


def test_overlapping_windows_correct_old_words_and_keep_one_revision_interval():
    phrases = iter(['We use soft mass for this vector',
                    'softmax for this vector and then normalize'])
    asr = QwenAccurateOnline(lambda audio: next(phrases), lambda audio, sec: 8 * 16000,
                            'en', window_seconds=8, token_type=SimpleNamespace,
                            transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(13 * 16000), 13)
    asr.process_iter()
    asr.insert_audio_chunk(np.ones(16000), 14)
    asr.process_iter()
    assert store.rows[0]['text'] == 'We use softmax for this vector and then normalize'
    assert not store.rows[0]['closed'] and list(store.rows) == [0]
    assert asr.finish()[0] and store.rows[0]['closed']


def test_sat_observations_cannot_close_before_asr_confirmation_or_on_heartbeats():
    prefix = 'So we want to go through the derivation.'
    mapper = CaptionMapper('en', predictor=lambda text: [len(prefix)] if text.startswith(prefix) else [])
    first = mapper.update(snapshot(prefix + ' Next we will use', stable=0))[0]
    for _ in range(20):
        mapper.update(snapshot(prefix + ' Next we will use', stable=len(prefix)))
    assert not mapper.previous[first.id].boundary_final
    continued = prefix + ' Next we will use the following assumptions'
    mapper.update(snapshot(continued, stable=0))
    assert not mapper.previous[first.id].asr_final
    assert not mapper.previous[first.id].boundary_final
    mapper.update(snapshot(continued))
    row = mapper.previous[first.id]
    assert row.asr_final and row.boundary_final and row.final
    assert not mapper.previous[2].final


def test_punctuation_does_not_protect_closed_fragment_from_new_sat_segmentation():
    cuts = [[len('So we want to.')]]
    mapper = CaptionMapper('en', predictor=lambda text: cuts[0])
    first = mapper.update(snapshot('So we want to.'), done=True)[0]
    cuts[0] = []
    value = 'So we want to. Go through the derivation step by step.'
    changed = mapper.update(snapshot(value))[0]
    assert changed.id == first.id and changed.source == value
    assert not changed.boundary_final and not changed.final


def test_boundary_only_version_change_requests_new_hy_and_rejects_old_result():
    async def exercise():
        row = Caption(1, 0, 1, 'Same words', 'en', ready=True, final=False,
                      asr_final=True, boundary_final=False, segmentation_revision=1)
        planner = ContextPlanner()
        old = planner.update_changes([row])[0]
        newer = replace(row, revision=2, segmentation_revision=2)
        request = planner.update_changes([newer])[0]
        assert planner.accepts(request) and not planner.accepts(old)
        outputs = []
        await publish_translation_result(replace(old, translation='obsolete'), lambda _: newer,
                                         asyncio.Lock(), outputs.append, planner=planner)
        assert outputs == []
        await publish_translation_result(replace(request, translation='current'), lambda _: newer,
                                         asyncio.Lock(), outputs.append, planner=planner)
        assert outputs[0].translation == 'current' and outputs[0].translation_phase == 'initial'
    asyncio.run(exercise())


@pytest.mark.parametrize('asr,boundary', [(False, False), (False, True), (True, False)])
def test_final_translation_requires_both_current_states_even_with_legacy_final_flag(asr, boundary):
    async def exercise():
        row = Caption(1, 0, 1, 'words', 'en', final=True, ready=True,
                      asr_final=asr, boundary_final=boundary)
        assert not source_is_final(row)
        planner = ContextPlanner()
        job = planner.update_changes([row])[0]
        assert not job.final and job.translation_phase == 'initial'
        outputs = []
        await publish_translation_result(replace(job, final=True, translation='old final',
                                                 translation_phase='final'),
                                         lambda _: row, asyncio.Lock(), outputs.append)
        assert outputs == []
    asyncio.run(exercise())


def test_queue_merges_latest_splits_and_removes_obsolete_spans_without_join_leak():
    async def exercise():
        queue = TranslationQueue()
        row = Caption(1, 0, 1, 'old merged', 'en', ready=True)
        queue.put_nowait(row)
        queue.put_nowait(Caption(2, 1, 2, 'removed span', 'en'))
        queue.discard(2)
        queue.put_nowait(replace(row, source='latest first part', revision=2))
        queue.put_nowait(Caption(3, 1, 2, 'latest second part', 'en'))
        assert queue.qsize() == 2
        first = await queue.get()
        batch = queue.take_batch(first, lambda a, b: True)
        assert [item[0].id for item in batch] == [1, 3]
        assert batch[0][0].source == 'latest first part'
        for _ in batch:
            queue.task_done()
        queue.put_nowait(Caption(4, 2, 3, 'obsolete', 'en'))
        queue.discard(4)
        queue.put_nowait(None)
        assert await queue.get() is None
        queue.task_done()
        await asyncio.wait_for(queue.join(), 1)
        assert queue.qsize() == 0
    asyncio.run(exercise())


def test_old_saved_caption_without_new_states_keeps_its_final_status():
    row = Caption(**{k: v for k, v in asdict(Caption(1, 0, 1, 'saved', 'en')).items()
                     if k not in ('asr_final', 'boundary_final', 'segmentation_revision')})
    assert source_is_final(row)


@pytest.mark.parametrize('backend', ['pytorch', 'mlx'])
def test_both_model_adapters_use_identical_online_policy(monkeypatch, backend):
    import sys

    import linguaflow.mlx_asr as mlx
    import linguaflow.qwen_accurate as official

    def construct(*args, **kwargs):
        return QwenAccurateOnline(*args, **kwargs, token_type=SimpleNamespace,
                                 transcript_type=SimpleNamespace)
    monkeypatch.setattr(official, 'QwenAccurateOnline', construct)
    monkeypatch.setattr(mlx, 'QwenAccurateOnline', construct)
    if backend == 'mlx':
        client = SimpleNamespace(decode=lambda audio: 'shared words', close=lambda: None,
                                 wait_ready=lambda: None)
        asr = mlx.build_mlx_online('local', 'en', .5, lambda text: None,
                                  window_seconds=8, client=client)
    else:
        model = SimpleNamespace(model=SimpleNamespace(generation_config=SimpleNamespace()),
                                transcribe=lambda *a, **kw: [SimpleNamespace(text='shared words')])
        monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(float32='float32',
                            float16='float16', bfloat16='bfloat16'))
        monkeypatch.setitem(sys.modules, 'qwen_asr', SimpleNamespace(Qwen3ASRModel=SimpleNamespace(
                            from_pretrained=lambda *a, **kw: model)))
        asr = official.build_official_online('local', 'cpu', 'en', .5, 8)
    assert isinstance(asr, QwenAccurateOnline)
    assert asr.pause_context_seconds == 3 and asr.window_seconds == 8
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(13 * 16000), 13)
    asr.process_iter()
    assert not store.rows[0]['closed'] and store.rows[0]['stable_end'] == 0
    asr.finish()
    assert store.rows[0]['closed']


def test_stop_cannot_claim_sat_closure_when_asr_did_not_confirm_text():
    mapper = CaptionMapper('en', predictor=lambda text: [])
    row = mapper.update(snapshot('unconfirmed words', stable=0), done=True)[0]
    assert not row.asr_final and not row.boundary_final and not row.final


def test_copied_prefix_after_one_backlog_decode_is_not_new_asr_agreement():
    phrases = iter(['zero one two three four five six seven eight nine ten eleven',
                    'three four five six seven eight nine ten eleven twelve',
                    'three four five six seven eight nine ten eleven twelve thirteen',
                    'three four five six seven eight nine ten eleven twelve thirteen fourteen'])
    asr = QwenAccurateOnline(lambda audio: next(phrases), lambda audio, seconds: 16 * 16000,
                            'en', window_seconds=16, token_type=SimpleNamespace,
                            transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(21 * 16000), 21)
    asr.process_iter()
    for end in (23, 25, 27):
        asr.insert_audio_chunk(np.ones(2 * 16000), end)
        asr.process_iter()
    assert store.rows[0]['text'].startswith('zero one two three')
    assert store.rows[0]['stable_end'] == 0 and not store.rows[0]['closed']


def test_sat_priority_defers_new_hy_until_latest_source_update_finishes():
    from threading import Event

    from linguaflow.translation_service import run_translations

    async def exercise():
        planner, queue = ContextPlanner(), TranslationQueue()
        row = Caption(1, 0, 1, 'old source', 'en', ready=True, final=False)
        old = planner.update_changes([row])[0]
        queue.put_nowait(old)
        called = Event()
        sources = []
        def translate(source, language):
            sources.append(source)
            called.set()
            return 'translation'
        async def publish(caption):
            pass
        queue.begin_source_update()
        queue.begin_source_update()
        consumer = asyncio.create_task(run_translations(queue,
            lambda: SimpleNamespace(translate=translate), lambda _: row, publish,
            lambda _: None, lambda _: None, planner=planner))
        await asyncio.sleep(.02)
        assert not called.is_set()
        queue.end_source_update()
        await asyncio.sleep(.02)
        assert not called.is_set()
        row = replace(row, source='new source', revision=2, segmentation_revision=2)
        queue.put_nowait(planner.update_changes([row])[0])
        queue.end_source_update()
        await asyncio.wait_for(queue.join(), 2)
        queue.put_nowait(None)
        await consumer
        assert sources == ['new source']
    asyncio.run(exercise())


def test_withdrawn_asr_confirmation_reopens_fixed_sat_boundary_without_text_change():
    prefix = 'First sentence.'
    mapper = CaptionMapper('en', predictor=lambda text: [len(prefix)] if text.startswith(prefix) else [])
    value = prefix + ' We continue with the next idea'
    first = mapper.update(snapshot(value), done=True)[0]
    assert first.asr_final and first.boundary_final
    events = mapper.update(snapshot(value, stable=0))
    reopened = next(c for c in events if c.id == first.id)
    assert reopened.source == first.source
    assert not reopened.asr_final and not reopened.boundary_final and not reopened.final


def test_new_internal_boundary_at_old_tail_end_invalidates_same_text_translation():
    clock = [0.]
    prefix = 'First sentence.'
    mapper = CaptionMapper('en', predictor=lambda text: [len(prefix)] if len(text) > len(prefix) else [],
                           lookahead=1, clock=lambda: clock[0])
    planner = ContextPlanner()
    mapper.update(snapshot(prefix))
    clock[0] = 2
    mapper.update(snapshot(prefix))
    old = planner.update_changes(mapper.previous.values())[0]
    events = mapper.update(snapshot(prefix + ' Another sentence begins here.'))
    newer = planner.update_changes(events)[0]
    assert newer.id == old.id and newer.source == old.source
    assert newer.segmentation_revision > old.segmentation_revision
    assert newer.translation_phase == 'initial' and not planner.accepts(old)
