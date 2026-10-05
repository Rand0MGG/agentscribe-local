"""MLX publishes full revisions through the existing submission strategy."""
from types import SimpleNamespace

import numpy as np

from linguaflow.mlx_asr import choose_cut
from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_revisions import install_revision_bridge
from linguaflow.translation_context import ContextPlanner
from linguaflow.wlk_captions import CaptionMapper


def online(decode, window=12):
    return QwenAccurateOnline(decode, choose_cut, 'en', window_seconds=window,
                             pause_context_seconds=3, token_type=SimpleNamespace,
                             transcript_type=SimpleNamespace)


def test_short_pause_retains_pcm_and_later_speech_corrects_original_phrase():
    calls = []
    def decode(audio):
        calls.append(audio.copy())
        return 'This is soft mass.' if len(audio) == 16000 else 'This is softmax of the vector.'
    asr = online(decode)
    first = np.ones(16000, np.float32)
    second = np.full(16000, 2, np.float32)
    asr.insert_audio_chunk(first, 1)
    assert asr.start_silence()[0] == []
    snapshot = asr.augment_snapshot({'lines': [], 'buffer_transcription': asr.text})
    assert snapshot['lines'] == []
    assert snapshot['buffer_transcription'] == 'This is soft mass.'
    assert asr.start_silence()[0] == [] and len(calls) == 1
    asr.end_silence(.75, 1)
    asr.insert_audio_chunk(second, 2.75)
    assert asr.process_iter()[0] == []
    np.testing.assert_array_equal(calls[-1], np.concatenate((first, np.zeros(12000), second)))
    assert asr.text == 'This is softmax of the vector.'
    tokens, end = asr.finish()
    assert ''.join(t.text for t in tokens) == 'This is softmax of the vector.'
    assert tokens[0].start == 0 and tokens[-1].end == end == 2.75
    assert asr.finish()[0] == []


def test_long_pause_starts_new_window_and_preserves_token_delivery_and_clock():
    asr = online(lambda audio: 'first phrase' if audio[0] == 1 else 'next phrase')
    asr.insert_audio_chunk(np.ones(16000), 1)
    assert asr.start_silence()[0] == []
    asr.end_silence(4, 1)
    asr.insert_audio_chunk(np.full(16000, 2), 6)
    tokens, _ = asr.process_iter()
    assert ''.join(t.text for t in tokens) == 'first phrase'
    assert tokens[0].start == 0 and tokens[-1].end == 1
    rest, _ = asr.finish()
    assert ''.join(t.text for t in rest).strip() == 'next phrase'
    assert rest[0].start == 5 and rest[-1].end == 6
    assert asr.finish()[0] == []


def test_eof_during_trailing_silence_does_not_extend_word_timestamps():
    asr = online(lambda audio: 'Last sentence.')
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.start_silence()
    asr.end_silence(10, 1)
    tokens, end = asr.finish()
    assert tokens[-1].end == 1 and end == 11
    assert asr.finish()[0] == []


def test_backlog_at_vad_endpoint_keeps_every_sample_and_decode_bounded():
    calls = []
    asr = online(lambda audio: calls.append(audio.copy()) or 'classroom phrase')
    audio = np.arange(50 * 16000, dtype=np.float32)
    asr.insert_audio_chunk(audio, 50)
    committed, _ = asr.start_silence()
    assert committed == []
    held = asr.audio_buffer.copy()
    assert len(held) <= 17 * 16000
    asr.end_silence(5, 50)
    asr.insert_audio_chunk(np.ones(16000), 56)
    queued, _ = asr.process_iter()
    final, _ = asr.finish()
    assert queued and final
    assert all(len(part) <= 17 * 16000 for part in calls)
    # The silence decode is retained as the final hypothesis, without
    # discarding or decoding its PCM again when the long pause is confirmed.
    # Overlaps are recognized again, but every original sample is covered.
    np.testing.assert_array_equal(np.unique(np.concatenate(calls[:-1])), audio)
    assert final[0].start == 55 and final[-1].end == 56


def test_mlx_uses_requested_window_and_retains_short_pauses(monkeypatch):
    import linguaflow.mlx_asr as module
    monkeypatch.setattr(module, 'MLXClient', lambda *args: SimpleNamespace(
        decode=lambda audio: 'text', close=lambda: None, wait_ready=lambda: None))
    monkeypatch.setattr(module, 'QwenAccurateOnline', lambda *args, **kwargs:
        QwenAccurateOnline(*args, **kwargs, token_type=SimpleNamespace,
                          transcript_type=SimpleNamespace))
    asr = module.build_mlx_online('model', 'en', .5, lambda text: None, window_seconds=30)
    assert asr.window_seconds == 30 and asr.pause_context_seconds == 3
    assert asr.update_seconds == .5


def test_capacity_rollover_does_not_close_or_shrink_the_asr_interval():
    asr = online(lambda audio: 'First sentence. Extra.' if len(audio) > 8 * 16000
                 else 'First sentence.', window=8)
    asr.choose_cut = lambda audio, seconds: 8 * 16000
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(12 * 16000), 12)
    asr.process_iter()
    assert store.rows[0]['end'] == 12
    asr.insert_audio_chunk(np.ones(16000), 13)
    asr.process_iter()
    assert not store.rows[0]['closed'] and store.rows[0]['end'] == 13
    assert store.rows[0]['stable_end'] == 0
    assert all(0 <= a <= b <= 13 for a, b in store.times[0])
    snapshot = {}
    store.augment_snapshot(snapshot)
    mapper = CaptionMapper('en', predictor=lambda text: [])
    caption = mapper.update(snapshot)[0]
    assert not caption.final and caption.end <= 13
    asr.finish()
    assert list(store.rows) == [0] and store.rows[0]['closed']
    assert store.rows[0]['end'] == 13


def test_short_vad_pause_uses_existing_store_without_publishing_closed_source():
    asr = online(lambda audio: 'The value is five.' if len(audio) == 16000 else 'The value is six.')
    events = []
    store = install_revision_bridge(asr, events.append)
    captions = CaptionMapper('en', predictor=lambda text: [])
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.start_silence()
    snapshot = {}
    store.augment_snapshot(snapshot)
    # An upstream silence-ready timestamp cannot override the authoritative
    # utterance state: only closed_ends from RevisionStore can finalize it.
    assert snapshot['closed_ends'] == []
    first = captions.update(snapshot)[0]
    assert not first.final and not store.rows[0]['closed']
    asr.end_silence(.75, 1)
    asr.insert_audio_chunk(np.ones(16000), 2.75)
    asr.process_iter()
    store.augment_snapshot(snapshot)
    changed = captions.update(snapshot)[0]
    assert changed.id == first.id and changed.source == 'The value is six.'
    assert not changed.final
    asr.finish()
    store.augment_snapshot(snapshot)
    assert captions.update(snapshot, done=True)[0].final
    assert events[-1]['data']['closed']


def test_silent_pcm_closes_utterance_through_shared_strategy_without_caption_timer():
    asr = online(lambda audio: 'Last sentence.')
    store = install_revision_bridge(asr)
    captions = CaptionMapper('en', predictor=lambda text: [], clock=lambda: 0)
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.start_silence()
    asr.observe_capture_event('silence_started', 1)
    asr.observe_capture_event('audio_advanced', 3.99)
    asr.get_buffer()
    assert not store.rows[0]['closed']
    asr.observe_capture_event('audio_advanced', 4)
    asr.get_buffer()
    snapshot = {}
    store.augment_snapshot(snapshot)
    tail = captions.update(snapshot)[0]
    assert tail.asr_final and not tail.boundary_final and not tail.final
    assert captions.update(snapshot, done=True)[0].final
    # WLK still receives its scheduling tokens once; caption data already came
    # from the full-hypothesis store, which never waits for append-only tokens.
    tokens, _ = asr.finish()
    assert ''.join(t.text for t in tokens) == 'Last sentence.'
    assert asr.finish()[0] == []


def test_capture_resumption_does_not_finalize_an_old_short_pause():
    asr = online(lambda audio: 'A phrase.')
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.start_silence()
    asr.observe_capture_event('silence_started', 1)
    asr.observe_capture_event('speech_started', 2)
    asr.observe_capture_event('audio_advanced', 10)
    asr.get_buffer()
    assert not store.rows[0]['closed'] and len(asr.audio_buffer)


def test_wall_clock_without_new_silent_pcm_never_closes_utterance():
    asr = online(lambda audio: 'A phrase.')
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.start_silence()
    for _ in range(20):
        asr.get_buffer()
    assert not store.rows[0]['closed']


def test_explicit_pause_drains_source_using_existing_completion_state():
    asr = online(lambda audio: 'A phrase.')
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.force_next_endpoint()
    assert asr.start_silence()[0]
    assert store.rows[0]['closed'] and not len(asr.audio_buffer)


def test_explicit_pause_waits_for_already_accepted_pcm_in_queue():
    asr = online(lambda audio: 'A complete phrase.')
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.force_next_endpoint(5)
    # A queued natural VAD endpoint preceding the explicit pause must not
    # consume the force marker before the rest of accepted PCM is decoded.
    assert asr.start_silence()[0] == [] and not store.rows[0]['closed']
    asr.end_silence(.5, 1)
    asr.insert_audio_chunk(np.ones(56000), 5)
    asr.process_iter()
    assert asr.start_silence()[0] and store.rows[0]['closed']


def test_empty_explicit_pause_does_not_close_future_speech():
    asr = online(lambda audio: 'A phrase.')
    store = install_revision_bridge(asr)
    asr.force_next_endpoint(0)
    asr.get_buffer()
    asr.insert_audio_chunk(np.ones(16000), 1)
    assert asr.start_silence()[0] == [] and not store.rows[0]['closed']


def test_shared_sat_policy_rejoins_punctuated_fragments_while_asr_remains_open():
    mapper = CaptionMapper('en', predictor=lambda text: [])
    first = mapper.update({'revision_text': 'I.', 'stable_end': 2,
                           'revision_spans': [], 'closed_ends': []})[0]
    assert not first.final
    continued = 'I. Take the input and extract its features.'
    changed = mapper.update({'revision_text': continued, 'stable_end': len(continued),
                             'revision_spans': [], 'closed_ends': []})[0]
    assert changed.id == first.id and changed.source == continued and not changed.final


def test_shared_submission_retranslates_corrected_source_then_finalizes():
    clock = [0.]
    asr = online(lambda audio: 'The value is five.' if len(audio) == 16000 else 'The value is six.')
    store = install_revision_bridge(asr)
    mapper = CaptionMapper('en', predictor=lambda text: [], lookahead=1, clock=lambda: clock[0])
    planner = ContextPlanner()
    def publish(done=False):
        snapshot = {}
        store.augment_snapshot(snapshot)
        mapper.update(snapshot, done=done)
        return planner.update(mapper.previous.values())
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.start_silence()
    assert publish() == []
    clock[0] = 2
    # A single recognition plus wall time is not ASR agreement. Actual silent
    # PCM may close ASR, after which the independent SaT submission delay runs.
    assert publish() == []
    asr.observe_capture_event('silence_started', 1)
    asr.observe_capture_event('audio_advanced', 4)
    asr.get_buffer()
    assert publish() == []
    clock[0] = 4
    first = publish()
    assert len(first) == 1 and first[0].translation_phase == 'initial'
    # Reopen an ASR interval with a revised full hypothesis, as the common
    # store does when later recognition corrects previously submitted words.
    store.update(0, 0, 2.75, 'The value is six.', len('The value is six.'))
    revised = publish()
    assert len(revised) == 1 and revised[0].translation_phase == 'initial'
    assert revised[0].id == first[0].id and revised[0].source == 'The value is six.'
    assert not planner.accepts(first[0]) and planner.accepts(revised[0])
    assert publish() == []
    final = publish(done=True)
    assert len(final) == 1 and final[0].translation_phase == 'final'
    assert final[0].id == first[0].id and final[0].source == 'The value is six.'
