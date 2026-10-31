"""Zero frames never enter Qwen; real recording time and old PCM survive gaps."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_audio import KeptAudioClock, NonzeroPCM, ZeroAudioGap
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
def test_zero_input_never_decodes_even_when_vad_says_speech():
    asr, calls, store = online()
    asr.observe_capture_event('speech_started', 0)
    for _ in range(100):
        feed(asr, np.zeros(RATE, np.float32))
    assert asr.end == 100 and not len(asr.audio_buffer)
    assert not calls and not store.rows
    assert asr.finish() == ([], 100)
    assert not calls


@pytest.mark.p1
def test_zero_transition_flushes_short_tail_once_and_keeps_context_and_recording_time():
    asr, calls, store = online()
    feed(asr, np.zeros(2 * RATE, np.float32))
    feed(asr, np.ones(RATE // 4, np.float32))
    assert not calls
    feed(asr, np.zeros(RATE, np.float32))
    np.testing.assert_array_equal(calls[0], np.ones(RATE // 4, np.float32))
    assert not store.rows[0]['closed']  # Zero is not a forced endpoint.
    for _ in range(99):
        feed(asr, np.zeros(RATE, np.float32))
    assert len(calls) == 1
    feed(asr, np.full(RATE, 2, np.float32))
    np.testing.assert_array_equal(calls[1], np.r_[np.ones(RATE // 4), np.full(RATE, 2)])
    assert asr.submission.last_audio_end == 1.25  # Zero samples do not advance voting time.
    assert store.rows[0]['stable_ranges'] == []  # Only two direct observations, despite 100 s of zero input.
    view = {}
    store.augment_snapshot(view)
    assert view['revision_spans'][0][2] == 2
    assert view['revision_spans'][-1][3] == 103.25
    resumed = view['revision_spans'][len('First words.'):]
    assert all(a >= 102.25 for _, _, a, _, _ in resumed)
    before = len(calls)
    asr.finish()
    assert len(calls) == before


@pytest.mark.p1
@pytest.mark.parametrize('packet', [1, 73, 160, 801])
def test_filter_is_packet_independent_and_retains_zero_crossings_and_weak_audio(packet):
    waveform = np.ones(160, np.float32)
    waveform[[0, 50, 159]] = 0  # Individual zero samples belong to real sound.
    weak = np.full(160, 1e-12, np.float32)
    audio = np.r_[np.zeros(320, np.float32), waveform, np.zeros(480, np.float32), weak, np.zeros(80, np.float32)]
    gate, parts = NonzeroPCM(RATE), []
    for start in range(0, len(audio), packet):
        parts.extend(gate.feed(audio[start:start+packet], start / RATE))
    parts.extend(gate.flush())
    kept = np.concatenate([part for _, part in parts if not isinstance(part, ZeroAudioGap)])
    np.testing.assert_array_equal(kept, np.r_[waveform, weak])
    assert sum(round((part.end - part.start) * RATE) for _, part in parts
               if isinstance(part, ZeroAudioGap)) == 880


@pytest.mark.p1
def test_failed_zero_tail_flush_preserves_tail_for_retry():
    asr, calls, _ = online()
    decode = asr.decode
    asr.decode = lambda _: (_ for _ in ()).throw(RuntimeError('decode failed'))
    feed(asr, np.ones(RATE // 4, np.float32))
    with pytest.raises(RuntimeError, match='decode failed'):
        feed(asr, np.zeros(RATE, np.float32))
    assert len(asr.audio_buffer) == RATE // 4
    asr.decode = decode
    asr.process_iter()
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0], np.ones(RATE // 4, np.float32))
    asr.finish()
    assert len(calls) == 1


@pytest.mark.p1
def test_mixed_backlog_keeps_all_nonzero_audio_bounded_and_clock_gaps():
    calls = []
    def decode(audio):
        calls.append((round(asr.start * RATE), audio.copy()))
        return 'Real words remain available in the retained audio context.'
    asr = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    first = np.arange(1, 40 * RATE + 1, dtype=np.float32)
    second = np.arange(len(first) + 1, 80 * RATE + 1, dtype=np.float32)
    feed(asr, np.r_[np.zeros(2 * RATE, np.float32), first, np.zeros(100 * RATE, np.float32), second])
    asr.finish()
    reached, parts = 0, []
    for start, part in calls:
        end = start + len(part)
        assert 0 < end - reached <= 10 * RATE
        assert len(part) <= 35 * RATE
        parts.append(part[reached-start:])
        reached = end
    np.testing.assert_array_equal(np.concatenate(parts), np.r_[first, second])
    assert asr.end == 182


@pytest.mark.p1
def test_removed_zero_gap_still_supplies_original_vad_release_reference():
    asr, calls, _ = online()
    for kind, at in [('silence_started', 0), ('speech_started', .5),
                     ('silence_started', 10), ('speech_started', 110)]:
        asr.observe_capture_event(kind, at)
    feed(asr, np.r_[np.ones(10 * RATE, np.float32), np.zeros(100 * RATE, np.float32),
                   np.full(25 * RATE, 2, np.float32)])
    # At 30 s of retained PCM, the original 100 s quiet gap remains the
    # release reference. Its source duration is not confused with zero PCM.
    np.testing.assert_array_equal(asr.audio_buffer, np.full(25 * RATE, 2, np.float32))
    assert asr.get_buffer().start == 110
    assert all(len(part) <= 35 * RATE for part in calls)


@pytest.mark.p1
@pytest.mark.parametrize('value,expected_calls', [(0., 0), (.002, 1)])
def test_explicit_pause_flushes_partial_frame_without_manufacturing_zero_input(value, expected_calls):
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
