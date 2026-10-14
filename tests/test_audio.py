import sys
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.audio import capture
from linguaflow.core import Settings


@pytest.mark.parametrize("rate, frames", [(16000, 1600), (48000, 4800)])
@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_stereo_capture_downmixes_resamples_and_stops(monkeypatch, rate, frames, platform):
    monkeypatch.setattr(sys, "platform", platform)
    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def record(self, numframes):
            assert numframes == 4800
            return np.column_stack([np.full(4800, 0.2), np.full(4800, 0.4)])

    def recorder(**kwargs):
        assert kwargs['samplerate'] == 48000
        if platform == 'darwin':
            assert 'blocksize' not in kwargs  # A CoreAudio device can reject 48,000 frames.
        else:
            assert kwargs['blocksize'] == 48000
        return Recorder()

    loopback = platform == 'win32'
    device = SimpleNamespace(id="test", isloopback=loopback, recorder=recorder)
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_microphones=lambda **kw: [device]))
    stop = Event()
    blocks = []

    def on_block(block):
        blocks.append(block)
        stop.set()

    capture(Settings("test", loopback=loopback, input_sample_rate=rate), stop, on_block)
    assert len(blocks) == 1
    assert blocks[0].shape == (frames,)
    assert blocks[0].dtype == np.float32
    assert float(blocks[0][20:-20].mean()) == pytest.approx(0.3, abs=0.001)


def test_disconnected_device_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_microphones=lambda **kw: []))
    with pytest.raises(RuntimeError, match="断开"):
        capture(Settings("gone"), Event(), lambda block: None)


def test_cancelled_capture_never_imports_audio(monkeypatch):
    monkeypatch.setitem(sys.modules, 'soundcard', None)
    stop = Event()
    stop.set()
    capture(Settings('test'), stop, lambda block: pytest.fail('unexpected audio'))


def test_mac_rejects_windows_loopback_before_importing_audio(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setitem(sys.modules, 'soundcard', None)
    with pytest.raises(RuntimeError, match='系统音频 · 电脑声音'):
        capture(Settings('test', loopback=True), Event(), lambda block: None)


@pytest.mark.parametrize('platform, loopback', [('darwin', False), ('win32', True)])
def test_device_discovery_uses_platform_loopback_policy(monkeypatch, platform, loopback):
    import linguaflow.audio as audio
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(audio, 'mac_ver', lambda: ('15.0', (), 'arm64'))

    def devices(**kwargs):
        assert kwargs == {'include_loopback': loopback}
        return [SimpleNamespace(id='device', name='fixture', isloopback=loopback)]

    monkeypatch.setitem(sys.modules, 'soundcard', SimpleNamespace(all_microphones=devices))
    devices_ = audio.list_devices()
    if platform == 'darwin':
        assert devices_[0] == audio.Device(audio.MAC_SYSTEM_AUDIO, '系统音频 · 电脑声音', True)
    else:
        assert len(devices_) == 1
    device = devices_[-1]
    assert device.loopback is loopback and device.id == 'device'
    assert device.name == ('系统音频 · fixture' if loopback else '外部输入 · fixture')


def test_mac_native_system_audio_routes_without_soundcard(monkeypatch):
    import linguaflow.audio as audio
    import linguaflow.audio_macos as mac
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setitem(sys.modules, 'soundcard', None)
    calls = []
    monkeypatch.setattr(mac, 'capture_system_audio', lambda *args: calls.append(args))
    settings, stop, callback = Settings(audio.MAC_SYSTEM_AUDIO, loopback=True), Event(), lambda block: None
    capture(settings, stop, callback)
    assert calls == [(settings, stop, callback)]


def test_old_mac_does_not_advertise_unavailable_native_audio(monkeypatch):
    import linguaflow.audio as audio
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(audio, 'mac_ver', lambda: ('12.7', (), 'arm64'))
    monkeypatch.setitem(sys.modules, 'soundcard', SimpleNamespace(all_microphones=lambda **kwargs: []))
    assert audio.list_devices() == []
