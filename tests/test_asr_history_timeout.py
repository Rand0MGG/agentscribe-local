"""P1: time finalizes only unchanged historical text, never active drafts/PCM."""
from threading import Event, Thread
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow import diagnostic_log as diag
from linguaflow.asr_submission import LocalAgreementSubmission
from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_revisions import install_revision_bridge


@pytest.mark.p1
def test_only_historical_words_expire_ten_seconds_after_their_last_edit():
    clock = [0.]
    state = LocalAgreementSubmission(clock=lambda: clock[0])
    state.update('First old. Current.', start=0, audio_end=1)
    clock[0] = 4
    state.update('Changed old. Current.', start=0, audio_end=2)
    clock[0] = 5
    state.update('Current.', start=len('Changed old. '), audio_end=3)
    assert state.expire_history(9.999) == 0
    assert state.expire_history(10) == 1  # "old." unchanged since t=0.
    assert not state.words[0].locked
    assert state.expire_history(13.999) == 0
    assert state.expire_history(14) == 1  # Only the changed word restarted its clock.
    text, ranges = state.snapshot()
    assert ranges == [(0, len(text))]
    assert state.expire_history(1000) == 0


@pytest.mark.p1
def test_appending_new_tail_does_not_restart_history_but_active_text_never_times_out():
    clock = [0.]
    state = LocalAgreementSubmission(clock=lambda: clock[0])
    state.update('Old draft. Current tail.', start=0, audio_end=1)
    clock[0] = 9
    state.update('Current changed.', start=len('Old draft. '), audio_end=2)
    assert state.expire_history(10) == 2
    assert state.snapshot()[1] == [(0, len('Old draft. Current'))]
    assert state.expire_history(1000) == 0
    assert state.words[-1].text.strip() == 'changed.' and not state.words[-1].locked


@pytest.mark.p1
def test_current_window_never_locks_by_elapsed_time_or_repeated_pcm():
    clock = [0.]
    state = LocalAgreementSubmission(clock=lambda: clock[0])
    state.update('Uncertain active words.', start=0, audio_end=1)
    clock[0] = 1000
    for _ in range(10):
        assert state.expire_history() == 0
        assert state.update('Uncertain active words.', start=0, audio_end=1)[1] == []


@pytest.mark.p1
def test_reentering_current_window_cancels_unexpired_history_deadline():
    clock = [0.]
    state = LocalAgreementSubmission(clock=lambda: clock[0])
    state.update('Old draft. Current.', start=0, audio_end=1)
    clock[0] = 5
    state.update('Current.', start=len('Old draft. '), audio_end=2)
    clock[0] = 9
    state.update('Revised draft. Current.', start=0, audio_end=3, aligned=False)
    assert state.expire_history(100) == 0
    assert not state.words[0].locked and not state.words[1].locked


@pytest.mark.p1
def test_timeout_locked_history_cannot_be_rewritten_when_model_returns_to_it():
    clock = [0.]
    state = LocalAgreementSubmission(clock=lambda: clock[0])
    state.update('Old draft. Current.', start=0, audio_end=1)
    clock[0] = 5
    state.update('Current.', start=len('Old draft. '), audio_end=2)
    assert state.expire_history(10) == 2
    text, ranges, _ = state.update('Changed wording. Current. New tail.', start=0, audio_end=3)
    assert text == 'Old draft. Current. New tail.'
    assert ranges == [(0, len('Old draft. Current.'))]


@pytest.mark.p1
def test_snapshot_tick_finalizes_history_without_inference_and_logs_only_changes(monkeypatch):
    import linguaflow.asr_submission as submission
    clock = [0.]
    monkeypatch.setattr(submission.time, 'monotonic', lambda: clock[0])
    events = []
    monkeypatch.setattr(diag, 'event', lambda name, **data: events.append((name, data)))
    outputs = iter(['Old draft.', 'New tail.'])
    calls = []
    def decode(audio):
        calls.append(len(audio))
        return next(outputs)
    asr = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.process_iter()
    clock[0] = 5
    asr._release(8000, 'test')
    asr.insert_audio_chunk(np.ones(16000), 2)
    asr.process_iter()
    before = asr.audio_buffer.copy()
    clock[0] = 9.999
    store.augment_snapshot({})
    assert store.rows[0]['stable_ranges'] == []
    clock[0] = 10
    asr.decode_sequence += 1  # A new decode started but has not published text.
    view = {}
    store.augment_snapshot(view)
    assert view['stable_ranges'] == [(0, len('Old draft.'))]
    assert not store.rows[0]['closed']
    for _ in range(100):
        store.augment_snapshot({})
    assert len(calls) == 2
    np.testing.assert_array_equal(before, asr.audio_buffer)
    timed = [data for name, data in events if name == 'asr_history_finalized']
    assert len(timed) == 1 and timed[0]['interval'] == 0 and timed[0]['decode_id'] == 2
    assert timed[0]['reason'] == 'history_unchanged_timeout'
    assert timed[0]['finalized_units'] == 2
    asr.finish()
    store.augment_snapshot({})
    assert store.rows[0]['closed'] and store.rows[0]['stable_end'] == len(store.rows[0]['text'])


@pytest.mark.p1
def test_suspended_history_preserves_original_edit_clock_and_stays_acoustically_open(monkeypatch):
    import linguaflow.asr_submission as submission
    clock = [0.]
    monkeypatch.setattr(submission.time, 'monotonic', lambda: clock[0])
    asr = QwenAccurateOnline(lambda _: 'Old draft.', 'en',
                            token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(16000), 1)
    asr.process_iter()
    clock[0] = 5
    asr._idle_start = 0
    asr._resume(2)
    clock[0] = 10
    store.augment_snapshot({})
    assert store.rows[0]['stable_ranges'] == [(0, len('Old draft.'))]
    assert not store.rows[0]['closed']
    asr.finish()
    assert store.rows[0]['closed']


@pytest.mark.p1
def test_history_refresh_never_blocks_event_loop_on_text_transaction():
    asr = QwenAccurateOnline(lambda _: '', 'en', token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    acquired, release, refreshed = Event(), Event(), Event()
    def owner():
        with asr._submission_lock:
            acquired.set()
            assert release.wait(3)
    thread = Thread(target=owner)
    thread.start()
    assert acquired.wait(3)
    worker = Thread(target=lambda: (store.augment_snapshot({}), refreshed.set()))
    worker.start()
    try:
        assert refreshed.wait(.5)
    finally:
        release.set()
        worker.join(3)
        thread.join(3)
    assert not worker.is_alive() and not thread.is_alive()
