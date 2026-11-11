"""Reject only fully VAD-labelled quiet windows, without text observations."""
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_audio import VADTimeline
from linguaflow.qwen_revisions import install_revision_bridge

RATE = 16000


def online(text='Actual speech stays.'):
    calls = []
    def decode(audio):
        calls.append(audio.copy())
        return text
    asr = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace,
                            transcript_type=SimpleNamespace)
    return asr, calls, install_revision_bridge(asr)


def feed(asr, audio):
    end = asr.end + len(audio) / RATE
    asr.observe_capture_event('audio_advanced', end)
    asr.insert_audio_chunk(audio, end)
    asr.process_iter()


@pytest.mark.p1
@pytest.mark.parametrize('text', ['Oh, yeah.', 'Thank you for watching.', '任意模型幻觉', 'yeah ' * 255])
@pytest.mark.parametrize('packet', [RATE, 100 * RATE])
def test_entire_quiet_nonzero_window_never_calls_model_or_submits(text, packet):
    asr, calls, store = online(text)
    asr.observe_capture_event('silence_started', 0)
    noise = np.full(100 * RATE, .02, np.float32)
    for start in range(0, len(noise), packet):
        feed(asr, noise[start:start + packet])
    assert not calls and not store.rows
    assert asr.decode_sequence == 0 and not asr._queued_audio
    assert len(asr.audio_buffer) <= 35 * RATE
    assert asr.finish() == ([], 100)
    assert not calls and not store.rows


@pytest.mark.p1
@pytest.mark.parametrize('where', ['first', 'middle', 'last'])
def test_even_one_sample_of_labelled_speech_keeps_entire_window(where):
    asr, calls, _ = online()
    start = {'first': 0., 'middle': .5, 'last': 1 - 1 / RATE}[where]
    asr.observe_capture_event('silence_started', 0)
    asr.observe_capture_event('speech_started', start, observed_at=1.1)
    asr.observe_capture_event('silence_started', start + 1 / RATE, observed_at=1.6)
    # The capture thread has already seen backdated labels beyond this queued
    # window. Do not hide its known speech just because observation was later.
    asr.observe_capture_event('audio_advanced', 1.6)
    audio = np.full(RATE, 1e-12, np.float32)
    asr.insert_audio_chunk(audio, 1.)
    asr.process_iter()
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0], audio)
    asr.finish()
    assert len(calls) == 1


@pytest.mark.p1
@pytest.mark.parametrize('label,horizon', [(False, 1.), (True, 0.), (True, 1 - 1 / RATE)])
def test_missing_or_incomplete_vad_coverage_preserves_normal_inference(label, horizon):
    asr, calls, _ = online()
    if label:
        asr.observe_capture_event('silence_started', 0)
    asr.observe_capture_event('audio_advanced', horizon)
    audio = np.full(RATE, .01, np.float32)
    asr.insert_audio_chunk(audio, 1.)
    asr.process_iter()
    np.testing.assert_array_equal(calls[0], audio)


@pytest.mark.p1
def test_skipped_noise_preserves_existing_text_votes_timestamps_and_eof():
    asr, calls, store = online()
    asr.observe_capture_event('speech_started', 0)
    feed(asr, np.full(RATE, .2, np.float32))
    asr.observe_capture_event('silence_started', 1)
    asr.observe_capture_event('speech_started', 1.5)
    feed(asr, np.full(RATE, .2, np.float32))
    asr.observe_capture_event('silence_started', 2, observed_at=2.5)
    # Exercise the normal window release rather than replacing PCM or state.
    for _ in range(31):
        feed(asr, np.full(RATE, .01, np.float32))
    assert asr.start >= 2
    state = (asr.text, repr(store.rows), asr.submission.last_audio_end,
             asr.decoded_end, asr.decode_sequence, len(calls))
    for _ in range(10):
        feed(asr, np.full(RATE, .01, np.float32))
    assert state == (asr.text, repr(store.rows), asr.submission.last_audio_end,
                     asr.decoded_end, asr.decode_sequence, len(calls))
    assert asr.text == 'Actual speech stays.'
    tokens, end = asr.finish()
    assert tokens and end == 43
    assert all(row['closed'] for row in store.rows.values())
    assert asr.finish()[0] == []


@pytest.mark.p1
@pytest.mark.parametrize('quiet_seconds', [3, 40])
def test_speech_after_quiet_still_requires_two_real_observations(quiet_seconds):
    asr, calls, store = online()
    asr.observe_capture_event('silence_started', 0)
    feed(asr, np.full(quiet_seconds * RATE, .01, np.float32))
    assert not calls
    asr.observe_capture_event('speech_started', quiet_seconds)
    feed(asr, np.full(RATE, .2, np.float32))
    assert len(calls) == 1 and not asr.confirmed_ranges
    np.testing.assert_array_equal(calls[-1][-RATE:], np.full(RATE, .2, np.float32))
    feed(asr, np.full(RATE, .2, np.float32))
    assert len(calls) == 2 and asr.confirmed_ranges
    asr.finish()
    assert len(calls) == 2 and all(row['closed'] for row in store.rows.values())
    assert max(row['end'] for row in store.rows.values()) == quiet_seconds + 2


@pytest.mark.p1
@pytest.mark.parametrize('pause', [False, True])
def test_subsecond_quiet_tail_does_not_infer_on_pause_or_eof(pause):
    asr, calls, store = online()
    asr.observe_capture_event('silence_started', 0)
    feed(asr, np.full(8000, .01, np.float32))
    if pause:
        asr.force_next_endpoint(.5)
        assert asr.start_silence()[0] == []
    assert asr.finish() == ([], .5)
    assert not calls and not store.rows


@pytest.mark.p1
def test_coverage_uses_received_backdated_speech_and_exact_window_bounds():
    vad = VADTimeline()
    vad.event('silence_started', 73.79, observed_at=74.38)
    assert vad.is_silent(73.79, 102.790625, observed_until=102.790625)
    assert not vad.is_silent(73.79 - 1 / RATE, 102.790625, observed_until=103.)
    assert not vad.is_silent(73.79, 102.790625, observed_until=102.)
    vad.event('speech_started', 102.78, observed_at=103.)
    assert not vad.is_silent(73.79, 102.790625, observed_until=103.)
    assert vad.is_silent(73.79, 102.78, observed_until=103.)


@pytest.mark.p1
def test_quiet_diagnostics_only_record_transitions_without_text_or_fake_decodes(monkeypatch):
    from linguaflow import diagnostic_log as diag
    records = []
    monkeypatch.setattr(diag, 'event', lambda name, **fields: records.append((name, fields)))
    asr, calls, _ = online('PRIVATE_WORDS')
    asr.observe_capture_event('silence_started', 0)
    for _ in range(3):
        feed(asr, np.full(RATE, .01, np.float32))
    assert not calls and asr.decode_sequence == 0
    asr.observe_capture_event('speech_started', 3)
    feed(asr, np.full(RATE, .2, np.float32))
    transitions = [(name, fields) for name, fields in records if name.startswith('asr_vad_window_')]
    assert [name for name, _ in transitions] == ['asr_vad_window_start', 'asr_vad_window_end']
    assert transitions[0][1]['window_start'] == 0 and transitions[0][1]['window_end'] == 1
    assert transitions[1][1]['window_end'] == 4
    assert all(fields['decode_id'] == 0 for _, fields in transitions)
    assert 'PRIVATE_WORDS' not in repr(records)
    assert len(calls) == asr.decode_sequence == 1


@pytest.mark.p1
@pytest.mark.parametrize('value', [0., .01])
def test_waiting_does_not_repeat_window_processing_even_at_eof(value):
    asr, calls, store = online()
    asr.observe_capture_event('silence_started', 0)
    processed = []
    original = asr._recognize
    def observe(count, reason='update'):
        original(count, reason)
        processed.append(asr.processed_end)
    asr._recognize = observe
    for _ in range(25):
        feed(asr, np.full(RATE // 10, value, np.float32))
    assert processed == ([] if value == 0 else [1.])
    tokens, end = asr.finish()
    assert not tokens and end == pytest.approx(2.5)
    assert processed == ([] if value == 0 else [1.])
    assert not calls and not store.rows


@pytest.mark.p1
def test_zero_guard_remains_independent_when_vad_claims_speech():
    asr, calls, store = online()
    asr.observe_capture_event('speech_started', 0)
    for end in (1, 2, 3):
        feed(asr, np.zeros(RATE, np.float32))
        assert asr.end == end and asr._clock.count == 0
        assert not len(asr.audio_buffer) and not asr._queued_audio
    assert not calls and not store.rows


@pytest.mark.p1
def test_late_vad_speech_recovers_more_than_one_second_of_recent_audio():
    asr, calls, _ = online()
    asr.observe_capture_event('silence_started', 0)
    noise = np.full(40 * RATE, .01, np.float32)
    feed(asr, noise)
    # Four seconds of speech were initially mislabelled quiet; retain them.
    missed = np.arange(1, 4 * RATE + 1, dtype=np.float32)
    feed(asr, missed)
    assert not calls
    asr.observe_capture_event('speech_started', 40, observed_at=44.1)
    resumed = np.full(RATE, .2, np.float32)
    feed(asr, resumed)
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0][-5 * RATE:], np.r_[missed, resumed])


@pytest.mark.p1
def test_waiting_wakes_if_vad_has_not_covered_new_audio():
    asr, calls, _ = online()
    asr.observe_capture_event('silence_started', 0)
    feed(asr, np.full(3 * RATE, .01, np.float32))
    assert not calls
    # Unknown is not evidence of silence. Deliberately do not advance VAD.
    asr.insert_audio_chunk(np.full(RATE, .2, np.float32), 4.)
    asr.process_iter()
    assert len(calls) == 1 and not asr._waiting_for_speech


@pytest.mark.p1
def test_speech_returns_to_normal_cadence_without_waiting_for_quiet_timer():
    asr, calls, _ = online()
    asr.observe_capture_event('silence_started', 0)
    feed(asr, np.full(4 * RATE, .01, np.float32))
    assert not calls and asr.processed_end == 4
    asr.observe_capture_event('speech_started', 4)
    feed(asr, np.full(RATE, .2, np.float32))
    assert len(calls) == 1 and asr.processed_end == 5
    feed(asr, np.full(RATE, .2, np.float32))
    assert len(calls) == 2 and asr.processed_end == 6


@pytest.mark.p1
def test_resume_failure_keeps_old_draft_and_retries_same_speech_window():
    asr, calls, store = online('Old draft.')
    feed(asr, np.full(2 * RATE, .2, np.float32))
    asr._release(RATE, 'test_roll')
    asr.observe_capture_event('silence_started', 2)
    # Advance the ordinary window far enough to leave only known quiet.
    for _ in range(40):
        feed(asr, np.full(RATE, .01, np.float32))
    assert asr._skipped_window
    old = dict(store.rows[0])
    asr.observe_capture_event('speech_started', 42)
    def fail(audio):
        raise RuntimeError('resume failed')
    asr.decode = fail
    with pytest.raises(RuntimeError, match='resume failed'):
        feed(asr, np.full(RATE, .3, np.float32))
    expected = asr.audio_buffer.copy()
    assert store.rows[0] == old and not old['closed']
    def recover(audio):
        np.testing.assert_array_equal(audio, expected)
        return 'New speech.'
    asr.decode = recover
    asr.process_iter()
    assert store.rows[0] == old and store.rows[1]['text'] == 'New speech.'
    assert store.rows[1]['start'] == 42
    asr.finish()
    assert all(row['closed'] for row in store.rows.values())
