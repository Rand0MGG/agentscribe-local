"""Source routing lifecycle, using fake devices and deterministic PCM only."""
import wave
from threading import Event

import numpy as np
import pytest
from test_wlk_session import PROGRAM, execute


@pytest.mark.p1
@pytest.mark.parametrize('paused', [False, True])
def test_switch_preserves_recording_clock_and_model_snapshot(monkeypatch, tmp_path, paused):
    captured, released = Event(), Event()
    calls, acks, pauses = [], [], []
    phase = [0]
    program = PROGRAM.replace("if message['type'] == 'stop': break",
                              "if message['type'] == 'stop': break\n    if message['type'] == 'pause': continue")

    def capture(settings, stop, block):
        calls.append(settings)
        if len(calls) == 1:
            block(np.full(1600, .1, dtype=np.float32))
            captured.set()
            assert stop.wait(5)
            assert not block(np.ones(1600, dtype=np.float32))
            released.set()
        else:
            assert released.is_set()
            assert settings.device_id == 'speaker' and settings.loopback
            block(np.full(1600, .2, dtype=np.float32))

    def setup(session):
        session.source_changed.connect(acks.append)
        session.paused.connect(pauses.append)

    def tick(session):
        if phase[0] == 0 and captured.is_set():
            if paused:
                assert session.pause()
            # Coalesce rapid changes; the final choice owns the next segment.
            with session.capture_control.condition:
                assert session.switch_source('unused', False) == 1
                assert session.switch_source('speaker', True) == 2
            assert session.settings.device_id == 'fixture' and not session.settings.loopback
            assert session.capture_settings.backend == session.settings.backend
            phase[0] = 1
        elif phase[0] == 1 and paused and pauses == [True]:
            assert len(calls) == 1  # Paused selection cannot open hardware.
            assert session.resume()
            phase[0] = 2

    captions, failures = execute(monkeypatch, tmp_path, program, capture, setup=setup, tick=tick)
    assert not failures and len(calls) == 2
    assert acks == [0, 2]
    assert pauses == ([True, False] if paused else [])
    assert captions[-1].source == '6400' and captions[-1].end == .2
    with wave.open(str(tmp_path / 'recording.wav')) as recording:
        assert recording.getnframes() == 3200
        pcm = np.frombuffer(recording.readframes(3200), dtype='<i2')
    assert np.all(pcm[:1600] == int(.1 * 32767))
    assert np.all(pcm[1600:] == int(.2 * 32767))


@pytest.mark.p1
def test_failed_source_switch_retains_previous_pcm(monkeypatch, tmp_path):
    captured = Event()
    requested, calls, sessions = [], [], []

    def capture(settings, stop, block):
        calls.append(settings.device_id)
        if len(calls) > 1:
            raise RuntimeError('selected input disconnected')
        block(np.full(1600, .1, dtype=np.float32))
        captured.set()
        assert stop.wait(5)

    def tick(session):
        if captured.is_set() and not requested:
            requested.append(session.switch_source('gone', False))

    program = PROGRAM.replace("if message['type'] == 'stop': break",
                              "if message['type'] == 'stop': break\n    if message['type'] == 'pause': continue")
    _, failures = execute(monkeypatch, tmp_path, program, capture,
                          setup=sessions.append, tick=tick)
    assert calls == ['fixture', 'gone']
    assert failures and 'selected input disconnected' in failures[0]
    assert sessions[0].switch_source('another', False) is None
    with wave.open(str(tmp_path / 'recording.wav')) as recording:
        assert recording.getnframes() == 1600
