import json
import subprocess
import sys
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.audio import capture
from linguaflow.core import Settings


@pytest.mark.p1
def test_device_discovery_import_does_not_load_capture_libraries():
    source = '''
import sys
class NoCaptureImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'scipy', 'soundcard'}:
            raise RuntimeError('Discovery imported capture libraries: ' + fullname)
sys.meta_path.insert(0, NoCaptureImports())
from linguaflow.audio import Device, discover_devices
assert Device('fixture', 'source', False).id == 'fixture'
assert callable(discover_devices)
'''
    result = subprocess.run([sys.executable, '-c', source], capture_output=True,
                            text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.p1
@pytest.mark.parametrize('outcome', ['success', 'failure', 'timeout', 'invalid'])
def test_device_discovery_reaps_its_owned_process_on_every_result(monkeypatch, outcome):
    from linguaflow import process_platform
    from linguaflow.audio import Device, discover_devices
    calls = []
    job = object()
    def communicate(timeout):
        assert timeout == 15
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired('synthetic-device-discovery', timeout)
        output = json.dumps([dict(id='fixture', name='隔离来源', loopback=False)]).encode('utf-8')
        return (b'invalid' if outcome == 'invalid' else output), b'fixture failure'
    process = SimpleNamespace(communicate=communicate, returncode=1 if outcome == 'failure' else 0)
    def start(python, module, **options):
        assert module == 'linguaflow.audio'
        assert options['stdin'] == subprocess.DEVNULL
        return process, job
    monkeypatch.setattr(process_platform, 'start_worker', start)
    monkeypatch.setattr(process_platform, 'stop_worker', lambda p, j, threads, **kw: calls.append(('stop', p, j, kw)))
    monkeypatch.setattr(process_platform, 'close_process_pipes', lambda p: calls.append(('close', p)))
    if outcome == 'success':
        assert discover_devices() == [Device('fixture', '隔离来源', False)]
    else:
        with pytest.raises(json.JSONDecodeError if outcome == 'invalid' else RuntimeError):
            discover_devices()
    assert calls == [('stop', process, job, {'force': True}), ('close', process)]


@pytest.mark.p1
@pytest.mark.parametrize("rate, frames", [(16000, 1600), (48000, 4800)])
@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_stereo_capture_downmixes_resamples_and_stops(monkeypatch, rate, frames, platform):
    monkeypatch.setattr(sys, "platform", platform)
    if rate == 48000:
        import builtins
        original_import = builtins.__import__
        def without_resampling(name, *args, **kwargs):
            if name.split('.')[0] == 'scipy':
                pytest.fail('48kHz capture must not load unused SciPy/BLAS before the first PCM block')
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, '__import__', without_resampling)
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


@pytest.mark.p1
def test_disconnected_device_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_microphones=lambda **kw: []))
    with pytest.raises(RuntimeError, match="断开"):
        capture(Settings("gone"), Event(), lambda block: None)


@pytest.mark.p0
def test_cancelled_capture_never_imports_audio(monkeypatch):
    monkeypatch.setitem(sys.modules, 'soundcard', None)
    stop = Event()
    stop.set()
    capture(Settings('test'), stop, lambda block: pytest.fail('unexpected audio'))


@pytest.mark.p1
def test_mac_rejects_windows_loopback_before_importing_audio(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setitem(sys.modules, 'soundcard', None)
    with pytest.raises(RuntimeError, match='系统音频 · 电脑声音'):
        capture(Settings('test', loopback=True), Event(), lambda block: None)


@pytest.mark.p1
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


@pytest.mark.p1
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


@pytest.mark.p2
def test_old_mac_does_not_advertise_unavailable_native_audio(monkeypatch):
    import linguaflow.audio as audio
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(audio, 'mac_ver', lambda: ('12.7', (), 'arm64'))
    monkeypatch.setitem(sys.modules, 'soundcard', SimpleNamespace(all_microphones=lambda **kwargs: []))
    assert audio.list_devices() == []
