"""Advisory VAD, original PCM, window bounds and never dropping unseen speech."""
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_audio import VADTimeline, fallback_cut, reference_cut
from linguaflow.qwen_revisions import install_revision_bridge

RATE = 16000


def online(window=30):
    calls = []
    def decode(audio):
        calls.append(audio.copy())
        return 'The lesson continues with more words.'
    asr = QwenAccurateOnline(decode, 'en', window_seconds=window,
                            token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    return asr, calls


@pytest.mark.p1
@pytest.mark.parametrize('window', [8, 25, 30, 40])
def test_backlog_admission_is_one_to_ten_seconds_without_losing_pcm(window):
    asr, calls = online(window)
    # Begin with a completely full model window; then a sub-minimum tail and
    # 100 seconds of backlog. The next call must not re-decode the full old cap.
    duration = window + 5
    end = duration + .75 + 100
    audio = np.arange(round(end * RATE), dtype=np.float32)
    asr.insert_audio_chunk(audio[:duration * RATE], duration)
    asr.process_iter()
    before = len(calls)
    asr.insert_audio_chunk(audio[duration * RATE:round((duration + .75) * RATE)], duration + .75)
    asr.process_iter()
    assert len(calls) == before
    asr.insert_audio_chunk(audio[round((duration + .75) * RATE):], end)
    asr.process_iter()
    previous = 0
    for part in calls:
        reached = int(part[-1]) + 1
        assert RATE <= reached - previous <= 10 * RATE
        assert len(part) <= (window + 5) * RATE
        previous = reached
    # Stopping may flush less than 1 second, and must not lose it.
    asr.finish()
    np.testing.assert_array_equal(np.unique(np.concatenate(calls)), audio)
    assert all(0 < len(part) <= (window + 5) * RATE for part in calls)


@pytest.mark.p1
@pytest.mark.parametrize('window', [25, 30])
def test_idle_threshold_tracks_window_and_protection_does_not_satisfy_minimum(window):
    asr, calls = online(window)
    quiet(asr, 1, 100)
    audio = np.arange(101 * RATE, dtype=np.float32)
    asr.insert_audio_chunk(audio[:window * RATE], window)
    asr.process_iter()
    assert asr._idle_start is None
    asr.insert_audio_chunk(audio[window * RATE:(window + 1) * RATE], window + 1)
    asr.process_iter()
    assert asr._idle_start == 1  # exactly W seconds of continuous quiet
    count = len(calls)
    asr.insert_audio_chunk(audio[(window + 1) * RATE:100 * RATE], 100)
    asr.process_iter()
    assert len(calls) == count  # no minimum input requirement during long idle
    start = 100 * RATE
    for end in (100.25, 100.99, 101):
        asr.insert_audio_chunk(audio[start:round(end * RATE)], end)
        asr.process_iter()
        start = round(end * RATE)
        assert len(calls) == count + (end == 101)
    np.testing.assert_array_equal(calls[-1], audio[99 * RATE:])


@pytest.mark.p1
def test_resumed_protection_is_separate_from_ten_second_new_audio_budget():
    asr, calls = online(25)
    quiet(asr, 0, 40)
    audio = np.arange(60 * RATE, dtype=np.float32)
    asr.insert_audio_chunk(audio, 60)
    asr.process_iter()
    resumed = [part for part in calls if part[-1] >= 40 * RATE]
    assert len(resumed) == 2
    np.testing.assert_array_equal(resumed[0], audio[39 * RATE:50 * RATE])
    np.testing.assert_array_equal(resumed[1], audio[39 * RATE:60 * RATE])


def quiet(asr, a, b=None):
    asr.observe_capture_event('silence_started', a)
    if b is not None:
        asr.observe_capture_event('speech_started', b)


@pytest.mark.p1
def test_longest_five_then_earliest_excluding_first_not_longest():
    gaps = [(0, 5), (2, 2.1), (4, 4.2), (6, 6.3), (8, 8.4), (10, 10.5), (12, 16)]
    # First quiet is excluded; the shortest remaining gap loses the top-five
    # vote. Among the selected five, choose position 4, not the longest at 12.
    assert reference_cut(gaps, 0, 20) == 4
    assert reference_cut([(0, 1), (7, 8)], 0, 30) == 7
    assert reference_cut([(0, 10)], 0, 30) is None


@pytest.mark.p1
def test_ongoing_silence_uses_observed_duration_and_no_future_detector_events():
    vad = VADTimeline()
    vad.event('silence_started', 0)
    vad.event('speech_started', 1)
    vad.event('silence_started', 5, observed_at=5.55)
    vad.event('speech_started', 20, observed_at=20.1)
    assert vad.snapshot(0, 5.5) == [(0, 1)]
    assert vad.snapshot(0, 6) == [(0, 1), (5, 6)]
    assert reference_cut(vad.snapshot(0, 6), 0, 6) == 5
    assert vad.snapshot(0, 21)[-1] == (5, 20)


@pytest.mark.p1
@pytest.mark.parametrize('duration,points,expected', [
    (34, [0, 2], 32), (39, [0, 5], 34),
    (39, [0, 3, 7, 11], 28),  # 39->36->32->28, sticky contraction
    (35, [], 35), (36, [], 29),
])
def test_one_normal_release_then_sticky_force_below_target(duration, points, expected):
    asr, calls = online()
    for a in points:
        quiet(asr, a, a + .6)
    # All possible discarded speech already recognized in a previous window.
    asr.insert_audio_chunk(np.ones(29 * RATE), 29)
    asr.process_iter()
    asr.insert_audio_chunk(np.ones((duration - 29) * RATE), duration)
    asr.process_iter()
    assert len(asr.audio_buffer) == expected * RATE
    assert all(len(a) <= 35 * RATE for a in calls)
    assert asr.start == duration - expected


@pytest.mark.p1
def test_continuous_voice_backlog_decodes_every_sample_before_releasing():
    asr, calls = online()
    store = install_revision_bridge(asr)
    audio = np.arange(100 * RATE, dtype=np.float32)
    asr.insert_audio_chunk(audio, 100)
    asr.process_iter()
    assert len(asr.audio_buffer) < 30 * RATE
    assert all(0 < len(a) <= 35 * RATE for a in calls)
    np.testing.assert_array_equal(np.unique(np.concatenate(calls)), audio)
    assert list(store.rows) == [0] and not store.rows[0]['closed']
    asr.finish()
    assert store.rows[0]['closed']


@pytest.mark.p1
def test_reference_cannot_remove_unseen_speech_even_with_a_far_ahead_cut():
    asr, calls = online()
    for a in (0, 40, 70):
        quiet(asr, a, a + .6)
    audio = np.arange(90 * RATE, dtype=np.float32)
    asr.insert_audio_chunk(audio, 90)
    asr.process_iter()
    seen = np.unique(np.concatenate(calls))
    # Known quiet may be skipped; every speech sample must have reached a model.
    speech = np.ones(len(audio), dtype=bool)
    for a in (0, 40, 70):
        speech[a * RATE:round((a + .6) * RATE)] = False
    assert np.isin(audio[speech], seen).all()
    assert max(map(len, calls)) <= 35 * RATE


@pytest.mark.p1
def test_fallback_relative_dip_or_exact_target_without_synthetic_padding():
    audio = np.ones(36 * RATE, dtype=np.float32)
    assert fallback_cut(audio, 29) == 7 * RATE
    audio[round(7.2 * RATE):round(7.24 * RATE)] = .01
    assert 7.2 <= fallback_cut(audio, 29) / RATE < 7.24


@pytest.mark.p1
@pytest.mark.parametrize('packets', [[31, 40, 50, 51], [50, 51], [51]])
def test_long_idle_resume_retains_real_protection_and_absolute_time(packets):
    asr, calls = online()
    store = install_revision_bridge(asr)
    quiet(asr, 1, 50)
    audio = np.arange(51 * RATE, dtype=np.float32)
    asr.insert_audio_chunk(audio[:RATE], 1)
    asr.process_iter()
    for end in packets:
        start = round(asr.end * RATE)
        asr.insert_audio_chunk(audio[start:end * RATE], end)
        asr.process_iter()
        if end <= 50:
            assert not store.rows[0]['closed']
            assert len(asr._idle_tail.samples) <= RATE
    np.testing.assert_array_equal(calls[-1], audio[49 * RATE:])
    assert asr.start == 49 and store.rows[1]['start'] == 49
    assert store.rows[0]['end'] == 31 and not store.rows[0]['closed']
    asr.finish()
    assert all(row['closed'] for row in store.rows.values())
    assert asr.finish()[0] == []


@pytest.mark.p1
def test_only_long_quiet_waits_and_short_pause_keeps_original_samples():
    asr, calls = online()
    quiet(asr, 0, 40)
    noise = np.full(40 * RATE, .001, dtype=np.float32)
    asr.insert_audio_chunk(noise, 40)
    asr.process_iter()
    assert calls and all(len(part) <= 35 * RATE for part in calls)
    count = len(calls)
    asr.get_buffer()
    assert len(calls) == count
    voice = np.ones(RATE, dtype=np.float32)
    asr.insert_audio_chunk(voice, 41)
    asr.process_iter()
    np.testing.assert_array_equal(calls[-1], np.concatenate((noise[-RATE:], voice)))
    quiet(asr, 41, 42)
    pause = np.full(RATE, .002, dtype=np.float32)
    asr.insert_audio_chunk(np.concatenate((pause, voice)), 43)
    asr.process_iter()
    np.testing.assert_array_equal(calls[-1][-2 * RATE:], np.concatenate((pause, voice)))


@pytest.mark.p1
def test_natural_pause_never_confirms_but_explicit_pause_closes_once():
    asr, _ = online()
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(RATE), 1)
    asr.process_iter()
    quiet(asr, 1)
    asr.observe_capture_event('audio_advanced', 50)
    for _ in range(5):
        asr.get_buffer()
    assert not store.rows[0]['closed']
    asr.force_next_endpoint(1)
    assert asr.start_silence()[0]
    assert store.rows[0]['closed']
    assert asr.start_silence()[0] == []


@pytest.mark.p1
def test_failure_before_long_idle_preserves_queued_resumed_speech():
    asr, calls = online()
    quiet(asr, 1, 50)
    original = asr.decode
    def fail(audio):
        raise RuntimeError('model failure')
    asr.decode = fail
    audio = np.arange(51 * RATE, dtype=np.float32)
    asr.insert_audio_chunk(audio, 51)
    with pytest.raises(RuntimeError, match='model failure'):
        asr.process_iter()
    asr.decode = original
    asr.finish()
    assert np.isin(audio[:RATE], np.concatenate(calls)).all()
    np.testing.assert_array_equal(calls[-1], audio[49 * RATE:])


@pytest.mark.p1
def test_insert_owns_pcm_snapshot_even_if_capture_reuses_its_array():
    asr, calls = online()
    audio = np.ones(RATE, dtype=np.float32)
    asr.insert_audio_chunk(audio, 1)
    audio[:] = 0
    asr.process_iter()
    np.testing.assert_array_equal(calls[0], np.ones(RATE, dtype=np.float32))


@pytest.mark.p1
def test_margin_window_is_not_released_again_without_new_audio_even_at_eof():
    asr, calls = online()
    for a in (0, 2, 5):
        quiet(asr, a, a + .6)
    asr.insert_audio_chunk(np.ones(29 * RATE), 29)
    asr.process_iter()
    asr.insert_audio_chunk(np.ones(5 * RATE), 34)
    asr.process_iter()
    assert asr.start == 2 and len(asr.audio_buffer) == 32 * RATE
    count = len(calls)
    for _ in range(3):
        asr.process_iter()
        assert asr.start == 2
    asr.finish()
    assert len(calls) == count


@pytest.mark.p1
def test_genuine_agreement_keeps_advancing_across_many_context_rollovers():
    def decode(audio):
        return ' '.join(f'w{int(i)}' for i in np.unique(audio))
    asr = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    for end in range(2, 91, 2):
        asr.insert_audio_chunk(np.repeat(np.arange(end-2, end, dtype=np.float32), RATE), end)
        asr.process_iter()
    assert asr.text == ' '.join(f'w{i}' for i in range(90))
    assert asr.confirmed_end >= len(' '.join(f'w{i}' for i in range(75)))
    assert not store.rows[0]['closed']


@pytest.mark.p1
def test_explicit_pause_vad_reset_still_detects_long_quiet_after_resume():
    asr, calls = online()
    asr.insert_audio_chunk(np.ones(RATE), 1)
    asr.process_iter()
    asr.force_next_endpoint(1)
    asr.start_silence()
    # Silero was reset and emits no boundary while resumed input stays quiet.
    asr.insert_audio_chunk(np.full(39 * RATE, .01), 40)
    asr.process_iter()
    assert asr._idle_start == 1
    count = len(calls)
    asr.insert_audio_chunk(np.full(5 * RATE, .01), 45)
    asr.process_iter()
    assert len(calls) == count
    asr.observe_capture_event('speech_started', 45)
    asr.insert_audio_chunk(np.ones(RATE), 46)
    asr.process_iter()
    np.testing.assert_array_equal(calls[-1], np.concatenate((np.full(RATE, .01, np.float32), np.ones(RATE))))
