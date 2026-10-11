"""ScreenCaptureKit lifecycle and PCM regressions without native device access."""
from contextlib import nullcontext
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow import audio_macos as mac
from linguaflow.core import Settings


class Factory:
    def __init__(self, value):
        self.value = value

    def alloc(self):
        return self.value


def fixture_native(monkeypatch, *, chunks=(), content_error=None, start_error=None,
                   stop_error=None, cancel_start=False, fail_output=False):
    stop, removed, config = Event(), [], {}
    output = SimpleNamespace()
    output.init = lambda: output
    stream = SimpleNamespace()
    stream.initWithFilter_configuration_delegate_ = lambda *args: stream
    stream.started_callback = None
    stream.stops = 0

    def add(receiver, kind, queue, error):
        assert receiver is output and queue == 'serial-queue' and error is None
        return (not fail_output or kind == 0), None

    def start(callback):
        stream.started_callback = callback
        if cancel_start:
            stop.set()
            return
        callback(start_error)
        for chunk in chunks:
            if isinstance(chunk, Exception):
                output.failed(chunk)
            else:
                output.receive(np.asarray(chunk, dtype=np.float32))

    def finish(callback):
        stream.stops += 1
        callback(stop_error)

    stream.addStreamOutput_type_sampleHandlerQueue_error_ = add
    stream.startCaptureWithCompletionHandler_ = start
    stream.stopCaptureWithCompletionHandler_ = finish
    stream.removeStreamOutput_type_error_ = lambda receiver, kind, error: (removed.append(kind) or True, None)
    setters = {name: (lambda value, key=name: config.update({key: value})) for name in (
        'setCapturesAudio_', 'setExcludesCurrentProcessAudio_', 'setSampleRate_', 'setChannelCount_',
        'setWidth_', 'setHeight_', 'setMinimumFrameInterval_', 'setQueueDepth_')}
    configuration = SimpleNamespace(**setters)
    configuration.init = lambda: configuration
    content_filter = SimpleNamespace(initWithDisplay_excludingApplications_exceptingWindows_=lambda *args: 'filter')
    calls = []

    def content(desktop, onscreen, callback):
        calls.append((desktop, onscreen))
        callback(SimpleNamespace(displays=lambda: ['display']), content_error)

    native = SimpleNamespace(
        CM=SimpleNamespace(CMTimeMake=lambda *args: args),
        SC=SimpleNamespace(
            SCShareableContent=SimpleNamespace(
                getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_=content),
            SCContentFilter=Factory(content_filter), SCStreamConfiguration=Factory(configuration),
            SCStream=Factory(stream), SCStreamOutputTypeScreen=0, SCStreamOutputTypeAudio=1),
        dispatch=SimpleNamespace(dispatch_queue_create=lambda *args: 'serial-queue'),
        Output=Factory(output), pool=nullcontext)
    monkeypatch.setattr(mac, '_native', lambda: native)
    monkeypatch.setattr(mac, '_audio_samples', lambda cm, sample: sample.copy())
    return stop, stream, removed, config, output, calls


@pytest.mark.parametrize('rate, frames', [(16000, 1600), (48000, 4800)])
def test_native_audio_aggregates_irregular_chunks_and_closes(monkeypatch, rate, frames):
    stop, stream, removed, config, output, _ = fixture_native(
        monkeypatch, chunks=[np.full(1200, .25), np.full(3600, .25), np.full(4800, .5)])
    blocks = []

    def receive(block):
        blocks.append(block.copy())
        if len(blocks) == 2:
            stop.set()

    mac.capture_system_audio(Settings('macos:system-audio', input_sample_rate=rate), stop, receive)
    assert len(blocks) == 2 and all(b.shape == (frames,) and b.dtype == np.float32 for b in blocks)
    assert float(blocks[0][20:-20].mean()) == pytest.approx(.25, abs=.001)
    assert float(blocks[1][20:-20].mean()) == pytest.approx(.5, abs=.001)
    assert config['setCapturesAudio_'] and config['setExcludesCurrentProcessAudio_']
    assert config['setSampleRate_'] == 48000 and config['setChannelCount_'] == 1
    assert config['setWidth_'] == config['setHeight_'] == 2
    assert stream.stops == 1 and removed == [0, 1]
    output.receive(np.ones(4800))  # Late frames cannot reach the previous session.
    assert len(blocks) == 2


def test_cancelled_start_stops_a_late_native_stream(monkeypatch):
    stop, stream, removed, _, output, _ = fixture_native(monkeypatch, cancel_start=True)
    blocks = []
    mac.capture_system_audio(Settings('macos:system-audio'), stop, blocks.append)
    assert stream.stops == 0
    output.receive(np.ones(4800))
    stream.started_callback(None)
    assert stream.stops == 1 and removed == [0, 1] and not blocks


@pytest.mark.parametrize('paused', [False, True])
def test_system_audio_source_switch_uses_shared_session_and_saves_pcm(monkeypatch, tmp_path, paused):
    import sys
    import wave

    from test_wlk_session import PROGRAM, execute

    from linguaflow.audio import MAC_SYSTEM_AUDIO, capture

    monkeypatch.setattr(sys, 'platform', 'darwin')
    _, stream, removed, _, _, _ = fixture_native(monkeypatch, chunks=[np.full(4800, .25)])
    received = Event()
    phase, pause_events = [], []

    def capture_source(settings, stop, block):
        if settings.device_id == MAC_SYSTEM_AUDIO:
            def pcm(samples):
                block(samples)
                received.set()
            capture(settings, stop, pcm)
        else:
            assert stream.stops == 1 and removed == [0, 1]
            block(np.full(1600, .5, dtype=np.float32))

    def setup(session):
        session.capture_settings = replace(session.capture_settings, device_id=MAC_SYSTEM_AUDIO, loopback=True)
        session.paused.connect(pause_events.append)

    def tick(session):
        if received.is_set() and not phase:
            if paused:
                assert session.pause()
            assert session.switch_source('microphone', False) == 1
            assert session.settings.device_id == 'fixture'  # Model snapshot stays frozen.
            phase.append(True)
        elif paused and pause_events == [True]:
            assert session.resume()

    program = PROGRAM.replace("if message['type'] == 'stop': break",
                              "if message['type'] == 'stop': break\n    if message['type'] == 'pause': continue")
    _, failures = execute(monkeypatch, tmp_path, program, capture_source, setup=setup, tick=tick)
    assert not failures and stream.stops == 1
    assert pause_events == ([True, False] if paused else [])
    with wave.open(str(tmp_path / 'recording.wav')) as recording:
        assert recording.getnframes() == 3200
        pcm = np.frombuffer(recording.readframes(3200), dtype='<i2')
    assert float(pcm[:1600][20:-20].mean()) == pytest.approx(.25 * 32767, abs=1.)
    assert np.all(pcm[1600:] == int(.5 * 32767))


@pytest.mark.parametrize('failure', ['permission', 'start', 'output', 'callback', 'overflow', 'stop'])
def test_failures_are_reported_and_owned_outputs_are_released(monkeypatch, failure):
    chunks = [RuntimeError('callback failed')] if failure == 'callback' else [np.ones(4800)]
    if failure == 'overflow':
        chunks = [np.ones(4800)] * 101
    stop, stream, removed, _, _, _ = fixture_native(
        monkeypatch, chunks=chunks, content_error='denied' if failure == 'permission' else None,
        start_error='denied' if failure == 'start' else None,
        stop_error='failed' if failure == 'stop' else None, fail_output=failure == 'output')
    messages = {'permission': '允许 AgentScribe', 'start': '允许 AgentScribe',
                'output': '捕获输出', 'callback': 'callback failed', 'overflow': '跟不上', 'stop': '未能正常停止'}
    with pytest.raises(RuntimeError, match=messages[failure]):
        mac.capture_system_audio(Settings('macos:system-audio'), stop, lambda block: stop.set())
    assert removed == ([] if failure == 'permission' else [0] if failure == 'output' else [0, 1])
    assert stream.stops == (0 if failure in ('permission', 'output') else 1)


def test_cancelled_capture_does_not_load_native_bridge(monkeypatch):
    monkeypatch.setattr(mac, '_native', lambda: pytest.fail('native bridge must remain unloaded'))
    stop = Event()
    stop.set()
    mac.capture_system_audio(Settings('macos:system-audio'), stop, lambda block: pytest.fail('late PCM'))


def test_cancelled_permission_discovery_does_not_create_a_stream(monkeypatch):
    stop, stream, removed, _, _, _ = fixture_native(monkeypatch)
    native = mac._native()
    native.SC.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_ = (
        lambda *args: stop.set())
    mac.capture_system_audio(Settings('macos:system-audio'), stop, lambda block: pytest.fail('late PCM'))
    assert stream.started_callback is None and not removed


def test_permission_wait_has_a_deadline(monkeypatch):
    ticks = iter([0., 31.])
    monkeypatch.setattr(mac.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(RuntimeError, match='超时'):
        mac._wait(Event(), Event(), '获取权限')


def decoder_fixture(samples):
    description = [48000, int.from_bytes(b'lpcm', 'big'), 1, 4, 1, 4, 1, 32, 0]
    data = samples.astype('<f4').tobytes()
    return SimpleNamespace(
        CMSampleBufferDataIsReady=lambda sample: True,
        CMSampleBufferGetNumSamples=lambda sample: len(samples),
        CMSampleBufferGetFormatDescription=lambda sample: description,
        CMAudioFormatDescriptionGetStreamBasicDescription=lambda fmt: tuple(fmt),
        CMSampleBufferGetDataBuffer=lambda sample: 'buffer',
        CMBlockBufferGetDataLength=lambda buffer: len(data),
        CMBlockBufferCopyDataBytes=lambda buffer, offset, length, dest: (0, data)), description


def test_pcm_decode_copies_samples_before_native_buffer_release():
    cm, _ = decoder_fixture(np.array([.25, -.5, 0.]))
    samples = mac._audio_samples(cm, 'sample')
    assert np.array_equal(samples, [.25, -.5, 0.]) and samples.flags.owndata
    cm.CMSampleBufferDataIsReady = lambda sample: False
    assert mac._audio_samples(cm, 'sample') is None


@pytest.mark.parametrize('index, value', [(0, 44100), (6, 2), (7, 16), (2, 0), (2, 3), (1, 0), (5, 8)])
def test_unexpected_pcm_format_is_rejected(index, value):
    cm, fmt = decoder_fixture(np.zeros(3))
    fmt[index] = value
    with pytest.raises(RuntimeError, match='PCM 格式'):
        mac._audio_samples(cm, 'sample')


def test_truncated_and_nonfinite_pcm_are_rejected():
    cm, _ = decoder_fixture(np.zeros(3))
    cm.CMBlockBufferGetDataLength = lambda buffer: 8
    with pytest.raises(RuntimeError, match='不完整'):
        mac._audio_samples(cm, 'sample')
    cm, _ = decoder_fixture(np.array([np.nan]))
    with pytest.raises(RuntimeError, match='无效采样'):
        mac._audio_samples(cm, 'sample')
