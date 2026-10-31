"""P1: current-window evidence progresses independently of uncertain history."""
import re
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_revisions import RevisionStore, install_revision_bridge
from linguaflow.translation_context import ContextPlanner
from linguaflow.wlk_captions import CaptionMapper


def sentences(text):
    return [i + 1 for i, char in enumerate(text) if char == '.']


def snapshot(store):
    result = {}
    store.augment_snapshot(result)
    return result


@pytest.mark.p1
@pytest.mark.parametrize('overlap', ['', 'Extra old words still need checking. '])
def test_current_window_recovers_after_uncertain_prefix_roll_and_reaches_translation(overlap):
    outputs = iter([
        'Wrong old opening. Extra old words still need checking.',
        'Another old opening. Extra old words still need checking.',
        'Different old opening. Extra old words still need checking.',
        *[overlap + 'Current lesson is reliable. More useful context words are arriving here ' + tail
          for tail in ('one', 'one two', 'one two three')],
    ])
    asr = QwenAccurateOnline(lambda audio: next(outputs), 'en',
                            token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    mapper = CaptionMapper('en', predictor=sentences)
    for end in (2, 4, 6):
        asr.insert_audio_chunk(np.ones(2 * asr.SAMPLING_RATE), end)
        asr.process_iter()
        mapper.update(snapshot(store))
    assert asr.confirmed_end == 0
    asr._release(2 * asr.SAMPLING_RATE, 'test_roll')
    for end in (8, 10, 12):
        asr.insert_audio_chunk(np.ones(2 * asr.SAMPLING_RATE), end)
        asr.process_iter()
        mapper.update(snapshot(store))
        current = next(c for c in mapper.previous.values() if c.source == 'Current lesson is reliable.')
        assert current.asr_final == (end == 12)
    assert current.final
    assert any(not c.asr_final for c in mapper.previous.values() if 'old' in c.source)
    plans = ContextPlanner().update(mapper.previous.values())
    assert any(plan.id == current.id and plan.final for plan in plans)
    # EOF finalizes all remaining drafts, including text outside the PCM window.
    asr.finish()
    mapper.update(snapshot(store), done=True)
    assert all(c.asr_final and c.final for c in mapper.previous.values())


@pytest.mark.p1
def test_suspended_open_interval_does_not_block_later_confirmation_or_hide_old_rows():
    store = RevisionStore('test')
    mapper = CaptionMapper('en', predictor=sentences)
    store.update(0, 0, 30, 'Uncertain opening.', 0)
    for tail in ('one', 'one two'):
        value = 'Current lesson is reliable. More useful context words are arriving ' + tail
        store.update(1, 110, 120, value, len(value))
        mapper.update(snapshot(store))
    old = next(c for c in mapper.previous.values() if c.source == 'Uncertain opening.')
    current = next(c for c in mapper.previous.values() if c.source == 'Current lesson is reliable.')
    assert not old.asr_final and current.final
    for _ in range(3):
        mapper.update(snapshot(store))
        assert mapper.previous[old.id].source == old.source
        assert mapper.previous[current.id].final
    # A confirmation-only withdrawal must reopen this row without changing its text.
    store.update(1, 110, 120, value, 0)
    mapper.update(snapshot(store))
    assert not mapper.previous[current.id].asr_final


@pytest.mark.p1
def test_confirmation_cannot_jump_an_uncertain_piece_inside_one_sentence():
    store = RevisionStore('test')
    store.update(0, 0, 2, 'Uncertain', 0)
    store.update(1, 3, 8, 'continuation ends here. More known words follow.', 47)
    mapper = CaptionMapper('en', predictor=sentences)
    mapper.update(snapshot(store), done=True)
    first = next(c for c in mapper.previous.values() if c.source.startswith('Uncertain'))
    assert not first.asr_final


@pytest.mark.p1
def test_long_idle_resume_keeps_old_draft_open_until_eof():
    old_round = [0]
    def decode(audio):
        if audio[-1] < 40 * 16000:
            old_round[0] += 1
            return f'Uncertain{old_round[0]} old opening.'
        return 'Current lesson is reliable. More useful context words are arriving here today ' + str(audio[-1])
    asr = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    mapper = CaptionMapper('en', predictor=sentences)
    asr.observe_capture_event('silence_started', 0)
    asr.observe_capture_event('speech_started', 40)
    start = 0
    for end in (41, 43, 45):
        asr.insert_audio_chunk(np.arange(start * 16000, end * 16000, dtype=np.float32), end)
        asr.process_iter()
        mapper.update(snapshot(store))
        start = end
    assert not store.rows[0]['closed'] and store.rows[0]['stable_end'] == 0
    assert any(c.final and c.source == 'Current lesson is reliable.' for c in mapper.previous.values())
    asr.finish()
    mapper.update(snapshot(store), done=True)
    assert store.rows[0]['closed'] and store.rows[0]['stable_end'] == len(store.rows[0]['text'])
    assert all(c.asr_final and c.final for c in mapper.previous.values())


@pytest.mark.p1
def test_submitted_text_survives_later_model_rewrite_and_polling_does_not_vote():
    values = iter(['Old uncertain opening. Extra old words.',
                   *['Current lesson is reliable. More useful context words are arriving here.'] * 3,
                   'Revised lesson is reliable. More useful context words are arriving here.'])
    asr = QwenAccurateOnline(lambda audio: next(values), 'en',
                            token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    mapper = CaptionMapper('en', predictor=sentences)
    asr.insert_audio_chunk(np.ones(2 * 16000), 2)
    asr.process_iter()
    asr._release(16000, 'test_roll')
    for end in (4, 6, 8):
        asr.insert_audio_chunk(np.ones(2 * 16000), end)
        asr.process_iter()
        mapper.update(snapshot(store))
        for _ in range(5):
            asr.process_iter()
        row = next(c for c in mapper.previous.values() if c.source == 'Current lesson is reliable.')
        assert row.asr_final == (end == 8)
    asr.insert_audio_chunk(np.ones(2 * 16000), 10)
    asr.process_iter()
    mapper.update(snapshot(store))
    row = next(c for c in mapper.previous.values() if c.source == 'Current lesson is reliable.')
    assert row.asr_final
    assert 'Revised' not in store.rows[0]['text']


@pytest.mark.p1
def test_chinese_ranges_shift_with_old_correction_and_reject_stale_translation():
    store = RevisionStore('test')
    mapper = CaptionMapper('zh', predictor=lambda text: [i + 1 for i, c in enumerate(text) if c == '。'])
    planner = ContextPlanner()
    store.update(0, 0, 2, '存疑。', 0)
    store.update(1, 4, 10, '当前已确认。后文也有依据。', 13)
    mapper.update(snapshot(store), done=True)
    old_request = next(c for c in planner.update(mapper.previous.values()) if c.source == '当前已确认。')
    assert old_request.final
    # The character coordinates move, but evidence belongs to the later source.
    store.update(0, 0, 2, '前面的内容仍然存疑。', 0)
    mapper.update(snapshot(store), done=True)
    planner.update(mapper.previous.values())
    assert not planner.accepts(old_request)
    assert any(c.source == '当前已确认。' and c.asr_final for c in mapper.previous.values())
    assert any(c.source == '前面的内容仍然存疑。' and not c.asr_final for c in mapper.previous.values())


@pytest.mark.p1
def test_cumulative_submission_reaches_preview_mapping_final_translation_and_export():
    from linguaflow.core import export_txt, source_is_final
    values = iter(['Apple stays here.', 'Apple stays here.', 'Orange stays here.',
                   'Apple stays here.', 'Orange stays here. New ending.'])
    events = []
    asr = QwenAccurateOnline(lambda _: next(values), 'en', token_type=SimpleNamespace,
                            transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr, emit=events.append)
    mapper = CaptionMapper('en', predictor=sentences)
    planner = ContextPlanner()
    for end in range(1, 6):
        asr.insert_audio_chunk(np.ones(16000), end)
        asr.process_iter()
        mapper.update(snapshot(store))
        planner.update(mapper.previous.values())
        if end == 3:
            assert asr.text == 'Orange stays here.'
            assert asr.confirmed_end == 0
        if end == 4:
            assert asr.text == 'Apple stays here.' and asr.confirmed_end == len(asr.text)
    assert events[-1]['data']['text'] == 'Apple stays here. New ending.'
    assert asr.text == 'Apple stays here. New ending.'
    assert asr.confirmed_end == len('Apple stays here.')
    asr.finish()
    mapper.update(snapshot(store), done=True)
    captions = list(mapper.previous.values())
    assert all(source_is_final(c) for c in captions)
    assert all(plan.final for plan in planner.update(captions))
    exported = export_txt(captions)
    assert 'Apple stays here.' in exported and 'New ending.' in exported
    assert 'Orange' not in exported
    assert store.rows[0]['closed'] and store.rows[0]['stable_end'] == len(store.rows[0]['text'])


@pytest.mark.p1
def test_ten_minute_rollovers_keep_votes_locks_and_all_words_at_eof():
    def decode(audio):
        words = [f'w{int(i)-1}' for i in np.unique(audio)]
        # A late model correction must not overwrite earlier three-vote words.
        if len(words) > 6:
            words[2] = 'wrong'
        return ' '.join(words)
    asr = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    previous = {}
    for end in range(1, 601):
        asr.insert_audio_chunk(np.full(16000, end, np.float32), end)
        asr.process_iter()
        # Every previously locked word is still present in the same order.
        words = asr.text.split()
        for index, word in previous.items():
            assert words[index] == word
        spans = list(re.finditer(r'\S+', asr.text))
        previous = {i: m.group() for i, m in enumerate(spans)
                    if any(a <= m.start() and m.end() <= b for a, b in asr.confirmed_ranges)}
        assert len(asr.audio_buffer) <= 35 * 16000
    assert len(asr.text.split()) == 600
    assert asr.confirmed_end > len(asr.text) - 40
    asr.finish()
    assert store.rows[0]['closed'] and store.rows[0]['stable_end'] == len(store.rows[0]['text'])
    mapper = CaptionMapper('en', predictor=lambda text: [])
    mapper.update(snapshot(store), done=True)
    assert all(c.asr_final and c.final for c in mapper.previous.values())
