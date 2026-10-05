from dataclasses import replace

from linguaflow.core import Caption, translation_status
from linguaflow.qwen_revisions import RevisionStore
from linguaflow.translation_context import ContextPlanner
from linguaflow.wlk_captions import CaptionMapper


def test_submitted_project_change_requests_new_initial_translation_then_final():
    clock = [0.]
    mapper = CaptionMapper('zh', predictor=lambda text: [], lookahead=1, clock=lambda: clock[0])
    planner = ContextPlanner()
    store = RevisionStore('test')
    jobs = []

    def update(value, closed=False):
        store.update(0, 0, 5, value, len(value), closed)
        snapshot = {}
        store.augment_snapshot(snapshot)
        events = mapper.update(snapshot)
        jobs.extend(planner.update(mapper.previous.values()))
        return events

    update('我们今天讨论这个项目的预算')
    clock[0] = 2
    update('我们今天讨论这个项目的预算')
    first_id = jobs[0].id
    update('我们今天讨论这个方案的预算是9000')
    assert len(jobs) == 2 and not mapper.previous[first_id].final
    assert jobs[1].translation_source.endswith('方案的预算是9000')
    assert mapper.previous[first_id].source == '我们今天讨论这个方案的预算是9000'
    update('我们今天讨论这个方案的预算是9000', closed=True)
    assert len(jobs) == 2 and not mapper.previous[first_id].boundary_final
    snapshot = {}
    store.augment_snapshot(snapshot)
    mapper.update(snapshot, done=True)
    jobs.extend(planner.update(mapper.previous.values()))
    assert len(jobs) == 3
    assert [c.translation_phase for c in jobs] == ['initial', 'initial', 'final']
    assert jobs[2].id == first_id and jobs[2].source.endswith('方案的预算是9000')
    assert mapper.previous[first_id].final


def test_submitted_rows_merge_and_request_updated_initial_translation():
    boundaries = [[6]]
    mapper = CaptionMapper('en', predictor=lambda text: boundaries[0])
    planner = ContextPlanner()
    first = mapper.update({'lines': [{'text': 'Hello world', 'start': 0, 'end': 3}]})
    job = planner.update(mapper.previous.values())[0]
    mapper.previous[first[0].id] = replace(mapper.previous[first[0].id], translation='你好',
        translation_phase='initial', translation_source='Hello')
    boundaries[0] = []
    mapper.update({'lines': [{'text': 'Hello world again', 'start': 0, 'end': 4}]})
    assert mapper.previous[first[0].id].source == 'Hello world again'
    assert first[1].id not in mapper.previous
    newer = planner.update(mapper.previous.values())
    assert len(newer) == 1 and newer[0].source == 'Hello world again'
    assert planner.accepts(newer[0]) and not planner.accepts(job)
    assert mapper.previous[first[0].id].translation == '你好'
    boundaries[0] = [2, 6, 9]
    mapper.update({'lines': [{'text': 'Hello world again!', 'start': 0, 'end': 5}]})
    assert mapper.previous[first[0].id].source == 'He'
    assert mapper.previous[first[0].id].segmentation_revision > newer[0].segmentation_revision
    assert ''.join(c.source.replace(' ', '') for c in mapper.previous.values()) == 'Helloworldagain!'


def test_acoustic_end_inside_sentence_is_not_a_text_boundary():
    mapper = CaptionMapper('zh', predictor=lambda text: [])
    mapper.update({'revision_text': '我们今天讨论这个方案的预算是9000',
                   'stable_end': 18, 'revision_spans': [], 'closed_ends': [10, 18]})
    assert [c.source for c in mapper.previous.values()] == ['我们今天讨论这个方案的预算是9000']
    assert all(c.asr_final and not c.boundary_final and not c.final for c in mapper.previous.values())


def test_asr_completed_tail_waits_for_sat_context_and_rejoins_continuation():
    mapper = CaptionMapper('en', predictor=lambda text: [])
    first = mapper.update({'lines': [{'text': 'The budget for this plan', 'start': 0, 'end': 2}],
                           'closed_audio_time': 2})[0]
    assert first.asr_final and not first.final
    changed = mapper.update({'lines': [
        {'text': 'The budget for this plan', 'start': 0, 'end': 2},
        {'text': 'is 9000.', 'start': 3, 'end': 4}], 'closed_audio_time': 2})
    assert changed[0].id == first.id and not changed[0].final
    assert len(mapper.previous) == 1 and changed[0].source == 'The budget for this plan is 9000.'
    final = mapper.update({'lines': [
        {'text': 'The budget for this plan', 'start': 0, 'end': 2},
        {'text': 'is 9000.', 'start': 3, 'end': 4}], 'closed_audio_time': 4}, done=True)
    assert len(final) == 1 and final[0].id == first.id and final[0].final


def test_merging_rows_does_not_steal_following_caption_id():
    cuts = [[6, 12]]
    mapper = CaptionMapper('en', predictor=lambda text: cuts[0])
    first = mapper.update({'lines': [{'text': 'Hello world. Next sentence.', 'start': 0, 'end': 5}]})
    cuts[0] = [12]
    events = mapper.update({'lines': [{'text': 'Hello world. Next sentence!', 'start': 0, 'end': 5}]})
    assert mapper.previous[first[0].id].source == 'Hello world.'
    assert mapper.previous[first[2].id].source == 'Next sentence!'
    assert first[1].id not in mapper.previous
    assert any(c.id == first[1].id and not c.source for c in events)


def test_closed_utterance_cannot_close_sat_tail_without_context_or_stop():
    store = RevisionStore('test')
    mapper = CaptionMapper('en', predictor=lambda text: [])
    store.update(0, 0, 4, 'Last sentence.', 14)
    snapshot = {}
    store.augment_snapshot(snapshot)
    mapper.update(snapshot)
    assert not mapper.previous[1].final
    store.update(0, 0, 4, 'Last sentence.', 14, closed=True)
    store.augment_snapshot(snapshot)
    mapper.update(snapshot)
    assert mapper.previous[1].asr_final and not mapper.previous[1].boundary_final
    store.update(1, 5, 6, 'New draft', 0)
    store.augment_snapshot(snapshot)
    mapper.update(snapshot)
    assert len(mapper.previous) == 1
    assert mapper.previous[1].source == 'Last sentence. New draft' and not mapper.previous[1].final


def test_timestamp_endpoint_does_not_finalize_later_speech():
    mapper = CaptionMapper('en', predictor=lambda text: [])
    mapper.update({'lines': [
        {'text': 'Ended.', 'start': 0, 'end': 2},
        {'text': 'Continuing', 'start': 3, 'end': 4}], 'closed_audio_time': 2.1})
    assert len(mapper.previous) == 1
    assert mapper.previous[1].source == 'Ended. Continuing' and not mapper.previous[1].boundary_final


def test_initial_translation_is_marked_stale_and_final_errors_are_not_complete():
    c = Caption(1, 0, 1, 'new', 'en', final=False, ready=True, translation='old translated',
                translation_source='old', translation_phase='initial')
    assert translation_status(c) == '初译 · 原文已更新'
    assert translation_status(replace(c, final=True)) == '初译 · 等待最终译文'
    assert translation_status(replace(c, final=True, error='failed')) == '最终翻译失败'
    assert translation_status(replace(c, final=True, translation_phase='final')) == '译文已定稿'


def test_closed_timestamp_groups_tokens_into_one_utterance():
    mapper = CaptionMapper('en', predictor=lambda text: [])
    mapper.update({'lines': [{'text': 'Hello world.', 'tokens': [
        {'text': 'Hello', 'start': 0, 'end': 1},
        {'text': ' world', 'start': 1, 'end': 2},
        {'text': '.', 'start': 2, 'end': 2.1}]}], 'closed_audio_time': 2.1})
    assert len(mapper.previous) == 1
    assert mapper.previous[1].source == 'Hello world.' and mapper.previous[1].asr_final
    assert not mapper.previous[1].boundary_final
