"""Capture evidence stays sparse, correlated, and outside PCM decisions."""
import wave
from dataclasses import replace
from threading import Thread

import numpy as np
import pytest

from linguaflow import diagnostic_log as diag
from linguaflow.capture_diagnostics import CaptureTrace


@pytest.fixture
def events(monkeypatch):
    rows = []
    monkeypatch.setattr(diag, 'event', lambda name, **fields:
                        rows.append(dict(event=name, **{**diag.trace_fields(), **fields})))
    return rows


@pytest.mark.p2
def test_zero_state_changes_are_sparse_and_keep_capture_link_across_threads(events):
    clock = [0.]
    with diag.trace_scope(capture_id='stream-1', source_revision=2):
        trace = CaptureTrace('macos_callback', 48000, clock=lambda: clock[0])
    signal = np.full(4800, .25, np.float32)
    zero = np.zeros(4800, np.float32)
    def callback():
        trace.observe(signal, pts=100.)
        for index in range(1000):
            clock[0] += .1
            trace.observe(zero, pts=100.1 + index*.1)
            trace.poll()  # Zero packets are not a missing callback.
        trace.observe(signal, pts=200.1)
    thread = Thread(target=callback)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    trace.finish()
    assert [r['event'] for r in events] == ['capture_signal_start', 'capture_signal_zero',
                                          'capture_signal_nonzero', 'capture_signal_end']
    assert all(r['capture_id'] == 'stream-1' and r['source_revision'] == 2 for r in events)
    assert events[1]['audio_start'] == .1 and events[1]['zero_seconds'] == 3
    assert events[2]['zero_seconds'] == 100
    assert events[-1]['zero_samples'] == 4800000 and events[-1]['trailing_zero_seconds'] == 0
    assert np.all(signal == .25) and not zero.any()


@pytest.mark.p2
def test_missing_callbacks_report_once_and_resume_without_stopping(events):
    clock = [0.]
    trace = CaptureTrace('macos_callback', 48000, clock=lambda: clock[0])
    for _ in range(10):
        clock[0] += 1
        trace.poll()
    assert [r['event'] for r in events] == ['capture_signal_stalled']
    trace.observe(np.ones(4800, np.float32))
    trace.poll()
    assert events[-1]['event'] == 'capture_signal_resumed' and events[-1]['gap_seconds'] == 10
    clock[0] = 14
    trace.poll()
    trace.finish()
    assert events[-2]['event'] == 'capture_signal_stalled'
    assert events[-1]['since_last_block_seconds'] == 4


@pytest.mark.p2
def test_timestamp_discontinuities_are_counted_without_per_packet_spam(events):
    trace = CaptureTrace('macos_callback', 48000)
    pcm = np.full(4800, .01, np.float32)
    for index in range(100):
        trace.observe(pcm, pts=1 + index*.2)  # .1 second packet, .2 second spacing.
    trace.finish()
    assert sum(r['event'] == 'capture_timestamp_gap' for r in events) == 1
    assert events[-1]['timestamp_gaps'] == 99
    assert events[-1]['received_samples'] == 480000
    assert not any(r['event'] == 'capture_signal_zero' for r in events)


@pytest.mark.p1
def test_native_and_recording_signals_share_id_and_preserve_wav(monkeypatch, tmp_path, events):
    from test_audio_macos import fixture_native
    from test_wlk_session import PROGRAM, execute

    from linguaflow import audio_macos as mac
    pcm = [np.full(4800, .25, np.float32), np.zeros(3*48000, np.float32),
           np.full(4800, .5, np.float32)]
    native_stop, _, _, _, _, _ = fixture_native(monkeypatch, chunks=pcm)
    def capture(settings, segment, on_block):
        count = 0
        def receive(samples):
            nonlocal count
            on_block(samples)
            count += 1
            if count == 32:
                native_stop.set()
        mac.capture_system_audio(settings, native_stop, receive)
    def setup(session):
        session.settings = replace(session.settings, input_sample_rate=48000)
        session.capture_settings = session.settings
    _, failures = execute(monkeypatch, tmp_path, PROGRAM, capture, setup=setup)
    assert not failures
    with wave.open(str(tmp_path/'recording.wav')) as wav:
        assert wav.getframerate() == 48000
        assert wav.readframes(wav.getnframes()) == (np.concatenate(pcm)*32767).astype('<i2').tobytes()
    signals = [r for r in events if r['event'].startswith('capture_signal_')]
    assert len({r['capture_id'] for r in signals}) == 1
    assert all(r['recording_start_seconds'] == 0 for r in signals)
    assert {r['capture_stage'] for r in signals} == {'macos_callback', 'recording_input'}
    for stage in ('macos_callback', 'recording_input'):
        rows = [r for r in signals if r['capture_stage'] == stage]
        assert [r['event'] for r in rows] == ['capture_signal_start','capture_signal_zero',
                                            'capture_signal_nonzero','capture_signal_end']
        assert rows[-1]['received_samples'] == 153600
        assert rows[-1]['zero_samples'] == 144000


@pytest.mark.p1
def test_bad_diagnostic_timestamps_do_not_drop_valid_audio(monkeypatch, events):
    from test_audio_macos import fixture_native

    from linguaflow import audio_macos as mac
    from linguaflow.core import Settings
    stop, _, _, _, _, _ = fixture_native(monkeypatch, chunks=[np.ones(4800)]*3)
    native = mac._native()
    def unavailable(sample):
        raise ValueError('timestamp unavailable')
    native.CM.CMSampleBufferGetPresentationTimeStamp = unavailable
    native.CM.CMTimeGetSeconds = float
    blocks = []
    def receive(samples):
        blocks.append(samples)
        if len(blocks) == 3:
            stop.set()
    mac.capture_system_audio(Settings('fixture', input_sample_rate=48000), stop, receive)
    assert len(blocks) == 3 and all(np.all(b == 1) for b in blocks)
    assert events[-1]['metadata_errors'] == 3
    assert not events[-1]['failed']
