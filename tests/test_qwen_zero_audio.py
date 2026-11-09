"""Only entirely zero inference windows are rejected; mixed PCM stays intact."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_audio import KeptAudioClock
from linguaflow.qwen_revisions import install_revision_bridge

RATE = 16000


def online():
    calls = []
    def decode(audio):
        calls.append(audio.copy())
        return 'First words.' if len(calls) == 1 else 'First words. Resumed words.'
    asr = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    return asr, calls, install_revision_bridge(asr)


def feed(asr, audio):
    asr.insert_audio_chunk(audio, asr.end + len(audio) / RATE)
    asr.process_iter()


@pytest.mark.p1
@pytest.mark.parametrize('packet', [160, 1760, 35200])
def test_short_zero_gaps_stay_in_pcm_without_extra_decodes(packet):
    asr, calls, _ = online()
    audio = np.tile(np.r_[np.full(1600, .125, np.float32), np.zeros(160, np.float32)], 20)
    for start in range(0, len(audio), packet):
        feed(asr, audio[start:start+packet])
    assert 1 <= len(calls) <= 2
    for part in calls:
        np.testing.assert_array_equal(part, audio[:len(part)])
    asr.finish()
    np.testing.assert_array_equal(calls[-1], audio)
    assert len(calls) <= 3  # EOF alone may flush the sub-second remainder.


@pytest.mark.p1
@pytest.mark.parametrize('vad_quiet', [False, True])
@pytest.mark.parametrize('packet', [RATE, 100 * RATE])
def test_zero_window_skips_model_and_advances_bounded_queue(vad_quiet, packet):
    asr, calls, store = online()
    asr.observe_capture_event('silence_started' if vad_quiet else 'speech_started', 0)
    audio = np.zeros(100 * RATE, np.float32)
    for start in range(0, len(audio), packet):
        feed(asr, audio[start:start+packet])
    assert asr.end == 100 and len(asr.audio_buffer) <= 35 * RATE
    assert not asr._queued_audio and not calls and not store.rows
    assert asr.decode_sequence == 0
    assert asr.finish() == ([], 100)
    assert not calls


@pytest.mark.p1
@pytest.mark.parametrize('reverse', [False, True])
def test_half_zero_window_passes_unchanged(reverse):
    asr, calls, _ = online()
    audio = np.r_[np.zeros(5 * RATE, np.float32), np.full(5 * RATE, .125, np.float32)]
    if reverse:
        audio = audio[::-1].copy()
    original = audio.copy()
    feed(asr, audio)
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0], original)
    np.testing.assert_array_equal(audio, original)
    assert asr._clock.source_time(5) == 5
    asr.finish()
    assert len(calls) == 1


@pytest.mark.p1
@pytest.mark.parametrize('position', [0, RATE // 2, RATE - 1])
def test_one_nonzero_sample_passes_even_if_very_weak_and_vad_says_quiet(position):
    asr, calls, _ = online()
    asr.observe_capture_event('silence_started', 0)
    audio = np.zeros(RATE, np.float32)
    audio[position] = 1e-12
    feed(asr, audio)
    np.testing.assert_array_equal(calls[0], audio)


@pytest.mark.p1
def test_zero_tail_uses_normal_minimum_and_keeps_earlier_sound_in_window():
    asr, calls, store = online()
    speech = np.full(RATE // 4, .125, np.float32)
    feed(asr, speech)
    feed(asr, np.zeros(RATE // 2, np.float32))
    assert not calls
    feed(asr, np.zeros(RATE // 4, np.float32))
    np.testing.assert_array_equal(calls[0], np.r_[speech, np.zeros(3 * RATE // 4)])
    feed(asr, np.zeros(RATE, np.float32))
    assert len(calls) == 2  # The full window still contains original nonzero PCM.
    assert not store.rows[0]['closed']
    asr.finish()
    assert len(calls) == 2 and store.rows[0]['closed']


@pytest.mark.p1
@pytest.mark.parametrize('vad_quiet', [False, True])
def test_sound_resumes_after_long_zero_without_reconnect(vad_quiet):
    asr, calls, store = online()
    asr.observe_capture_event('silence_started' if vad_quiet else 'speech_started', 0)
    feed(asr, np.zeros(100 * RATE, np.float32))
    assert not calls
    asr.observe_capture_event('speech_started', 100)
    speech = np.full(RATE, .25, np.float32)
    feed(asr, speech)
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0][-RATE:], speech)
    assert np.count_nonzero(calls[0][:-RATE]) == 0
    assert asr.end == 101 and len(calls[0]) <= 35 * RATE
    view = {}
    store.augment_snapshot(view)
    assert view['revision_spans'][-1][3] == 101
    asr.finish()
    assert len(calls) == 1 and all(r['closed'] for r in store.rows.values())


@pytest.mark.p1
def test_skipped_zero_window_does_not_erase_text_vote_or_extend_text_times():
    asr, calls, store = online()
    asr.decode = lambda audio: calls.append(audio.copy()) or 'Keep these words.'
    feed(asr, np.ones(RATE, np.float32))
    # No VAD labels: normal rolling eventually releases all original sound.
    for _ in range(50):
        feed(asr, np.zeros(RATE, np.float32))
    assert not np.any(asr.audio_buffer)
    text = asr.text
    rows = repr(store.rows)
    last_observation = asr.submission.last_audio_end
    count, decode_id = len(calls), asr.decode_sequence
    for _ in range(50):
        feed(asr, np.zeros(RATE, np.float32))
    assert len(calls) == count and asr.decode_sequence == decode_id
    assert asr.text == text == 'Keep these words.' and repr(store.rows) == rows
    assert asr.submission.last_audio_end == last_observation
    asr.finish()
    assert all(r['closed'] for r in store.rows.values())
    assert asr.finish()[0] == []


@pytest.mark.p1
def test_failed_mixed_decode_keeps_samples_for_retry():
    asr, calls, _ = online()
    decode = asr.decode
    asr.decode = lambda _: (_ for _ in ()).throw(RuntimeError('decode failed'))
    audio = np.r_[np.ones(RATE // 4, np.float32), np.zeros(RATE, np.float32)]
    with pytest.raises(RuntimeError, match='decode failed'):
        feed(asr, audio)
    np.testing.assert_array_equal(asr.audio_buffer, audio)
    asr.decode = decode
    asr.process_iter()
    np.testing.assert_array_equal(calls[0], audio)
    asr.finish()
    assert len(calls) == 1


@pytest.mark.p1
def test_mixed_backlog_does_not_drop_nonzero_samples_and_keeps_original_time():
    calls = []
    def decode(audio):
        calls.append((round(asr.start * RATE), audio.copy()))
        return 'Real words remain available in the retained audio context.'
    asr = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    first = np.arange(1, 40 * RATE + 1, dtype=np.float32)
    second = np.arange(len(first) + 1, 80 * RATE + 1, dtype=np.float32)
    original = np.r_[np.zeros(2 * RATE, np.float32), first, np.zeros(100 * RATE, np.float32), second]
    feed(asr, original)
    asr.finish()
    covered = np.zeros(len(original), dtype=bool)
    for start, part in calls:
        assert len(part) <= 35 * RATE and np.any(part)
        np.testing.assert_array_equal(part, original[start:start+len(part)])
        covered[start:start+len(part)] = True
    assert np.all(covered[original != 0])
    assert asr.end == 182


@pytest.mark.p1
@pytest.mark.parametrize('value,expected_calls', [(0., 0), (.002, 1)])
def test_explicit_pause_checks_even_sub_frame_tail(value, expected_calls):
    asr, calls, _ = online()
    feed(asr, np.full(80, value, np.float32))
    assert not calls
    asr.force_next_endpoint(.005)
    asr.start_silence()
    assert len(calls) == expected_calls
    if calls:
        np.testing.assert_array_equal(calls[0], np.full(80, value, np.float32))
    asr.finish()
    assert len(calls) == expected_calls


@pytest.mark.p1
def test_eof_clock_append_is_atomic_for_concurrent_revision_reader():
    clock = KeptAudioClock(RATE)
    entered, release, reading = Event(), Event(), Event()
    class PausingIndex(list):
        def append(self, value):
            super().append(value)
            entered.set()
            assert release.wait(2)
    clock.starts = PausingIndex()
    def read():
        reading.set()
        return clock.source_time(0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(clock.append, 2 * RATE, 80)
        try:
            assert entered.wait(2)
            reader = pool.submit(read)
            assert reading.wait(2)
            with pytest.raises(TimeoutError):
                reader.result(timeout=.05)
        finally:
            release.set()
        assert writer.result(timeout=2) == 0
        assert reader.result(timeout=2) == 2
