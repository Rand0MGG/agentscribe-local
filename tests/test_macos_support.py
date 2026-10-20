"""Platform regressions use fake devices and never open native audio."""
import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_windows_web_session_guard_does_not_load_macos_frameworks(monkeypatch):
    import ctypes

    from linguaflow.process_platform import window_session_available
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(ctypes, 'CDLL', lambda *args: pytest.fail('Windows must not load Quartz'))
    assert window_session_available()


@pytest.mark.parametrize('session', [None, 12345])
def test_quartz_probe_does_not_register_an_application_and_releases_session(monkeypatch, session):
    import ctypes

    from linguaflow.process_platform import window_session_available
    released = []
    class Function:
        def __init__(self, fn):
            self.fn = fn
        def __call__(self, *args):
            return self.fn(*args)
    graphics = SimpleNamespace(CGSessionCopyCurrentDictionary=Function(lambda: session))
    foundation = SimpleNamespace(CFRelease=Function(released.append))
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(ctypes, 'CDLL', lambda path: graphics if 'CoreGraphics' in path else foundation)
    assert window_session_available() is bool(session)
    assert released == ([session] if session else [])


@pytest.mark.parametrize('target, suffix, index', [
    ('macos-arm64', '', None), ('windows-x64', '+cu128', 'cu128'),
])
def test_runtime_install_plan_is_platform_specific(monkeypatch, tmp_path, target, suffix, index):
    from linguaflow import runtime_install
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'install_runtime.py'
    spec = importlib.util.spec_from_file_location('install_runtime', path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(runtime_install, 'check_installation', lambda: target)
    monkeypatch.setattr(runtime_install, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(runtime_install, 'cache_root', lambda: tmp_path / 'cache')
    monkeypatch.setattr(runtime_install, 'prepare_sources', lambda requirements, _: requirements)
    monkeypatch.setattr(sys, 'argv', [str(path)])
    calls = []
    def run(command, **kw):
        calls.append(command)
        if 'venv' in command:
            from linguaflow.runtime_paths import environment_python
            python = environment_python(command[-1])
            python.parent.mkdir(parents=True)
            python.write_bytes(b'fixture interpreter')
    monkeypatch.setattr(runtime_install, 'run_command', run)
    installer.main()
    torch = calls[1]
    assert f'torch==2.11.0{suffix}' in torch and f'torchaudio==2.11.0{suffix}' in torch
    if index:
        assert torch[-2:] == ['--index-url', 'https://download.pytorch.org/whl/' + index]
    else:
        assert '--index-url' not in torch


def test_mac_intel_or_rosetta_rejected_before_environment_creation(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'install_runtime.py'
    spec = importlib.util.spec_from_file_location('install_runtime', path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(sys, 'argv', [str(path)])
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('must not create an environment'))
    with pytest.raises(ValueError, match='Apple Silicon'):
        installer.main()


def test_mac_settings_restore_without_audio_initialization(tmp_path):
    code = '''
import os, sys, json
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
app = QApplication([])
sys.platform = 'darwin'
prefs = QSettings(os.environ['AGENTSCRIBE_LIBRARY'] + '/prefs.ini', QSettings.Format.IniFormat)
prefs.setValue('compute', 'NVIDIA GPU · 半精度')
prefs.setValue('translation_device', 'cuda')
prefs.setValue('semantic_device', 'cuda')
prefs.setValue('audio_processing', json.dumps({'deepfilter': True, 'df_device': 'cuda', 'df_mix': .4}))
w = Window(discover=False, prefs=prefs)
assert w.compute.currentData() == 'cpu'
assert w.model_manager.translation_device.currentData() == 'cpu'
# Simulated CoreAudio inputs must retain their IDs and non-loopback flag in
# both selectors, including after a refresh, reorder or device disconnection.
import linguaflow.app as desktop
from linguaflow.audio import MAC_SYSTEM_AUDIO, Device
from linguaflow.recording_state import RecordingState
devices = [Device('coreaudio:mic', '输入 · MacBook 麦克风', False),
           Device('coreaudio:blackhole', '输入 · BlackHole 2ch', False),
           Device(MAC_SYSTEM_AUDIO, '系统音频 · 电脑声音', True)]
desktop.list_devices = lambda: devices
w.refresh_devices()
w.quick_device.setCurrentIndex(2)
assert w.quick_device.currentText() == '系统音频 · 电脑声音'
snapshot = w.settings_binding.session_settings(w.device.currentData())
assert snapshot.device_id == MAC_SYSTEM_AUDIO and snapshot.loopback
w.quick_device.setCurrentIndex(1)
assert w.device.currentData() == ('coreaudio:blackhole', False)
snapshot = w.settings_binding.session_settings(w.device.currentData())
assert snapshot.device_id == 'coreaudio:blackhole' and not snapshot.loopback
devices.reverse()
w.refresh_devices()
assert w.quick_device.currentIndex() == w.device.currentIndex() == 1
assert w.quick_device.currentData() == ('coreaudio:blackhole', False)
for state in (RecordingState.STARTING, RecordingState.LISTENING, RecordingState.PAUSING,
              RecordingState.PAUSED, RecordingState.RESUMING, RecordingState.STOPPING):
    w.set_recording_state(state)
    enabled = state in (RecordingState.LISTENING, RecordingState.PAUSED)
    assert w.quick_device.isEnabled() == w.device.isEnabled() == enabled
    assert w.refresh_source.isEnabled() == enabled
w.set_recording_state(RecordingState.IDLE)
devices.pop(1)
warnings = []
w.show_warning = lambda title, message: warnings.append((title, message))
w.refresh_devices()
assert w.device.currentIndex() == w.quick_device.currentIndex() == -1
assert w.quick_device.currentData() is None
assert warnings and warnings[-1][0] == '音频来源不可用'
assert 'soundcard' not in sys.modules and 'PySide6.QtMultimedia' not in sys.modules
assert 'ScreenCaptureKit' not in sys.modules
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
