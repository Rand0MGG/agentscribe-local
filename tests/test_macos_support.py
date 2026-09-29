"""Platform regressions use fake devices and never open native audio."""
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from linguaflow.preferences import read_preferences


@pytest.mark.parametrize('platform, expected', [('darwin', 'cpu'), ('win32', 'cuda')])
def test_windows_audio_preferences_are_portable(monkeypatch, platform, expected):
    data = {'deepfilter': True, 'df_device': 'cuda', 'df_mix': .4, 'output_db': 3}

    class Store:
        def value(self, key, default=None, **kwargs):
            return json.dumps(data) if key == 'audio_processing' else default

    monkeypatch.setattr(sys, 'platform', platform)
    config = read_preferences(Store())['audio_processing']
    assert config['df_device'] == expected
    assert config['deepfilter'] and config['df_mix'] == .4 and config['output_db'] == 3
    assert data['df_device'] == 'cuda'


def test_mac_cuda_installer_rejects_before_subprocess_or_session_changes(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'install_audio.py'
    spec = importlib.util.spec_from_file_location('install_audio', path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(sys, 'argv', [str(path), '--device', 'cuda'])
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('installer must not run'))
    monkeypatch.setattr(os, 'setsid', lambda: pytest.fail('must not change process session'), raising=False)
    with pytest.raises(SystemExit, match='macOS'):
        installer.main()


@pytest.mark.parametrize('system, machine, cpu, suffix, index', [
    ('darwin', 'arm64', False, '', None),
    ('darwin', 'arm64', True, '', None),
    ('win32', 'AMD64', False, '+cu128', 'cu128'),
    ('win32', 'AMD64', True, '+cpu', 'cpu'),
])
def test_runtime_install_plan_is_platform_specific(monkeypatch, system, machine, cpu, suffix, index):
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'install_runtime.py'
    spec = importlib.util.spec_from_file_location('install_runtime', path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(sys, 'platform', system)
    monkeypatch.setattr(platform, 'machine', lambda: machine)
    monkeypatch.setattr(sys, 'argv', [str(path), *(['--cpu'] if cpu else [])])
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda command, **kw: calls.append(command))
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
    with pytest.raises(SystemExit, match='Apple Silicon'):
        installer.main()


def test_mac_settings_restore_without_audio_initialization(tmp_path):
    code = '''
import os, sys, json
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.audio_processing.lab import AudioLab
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
assert w.model_manager.semantic_device.currentData() == 'cpu'
assert w.audio_config['df_device'] == 'cpu' and w.audio_config['deepfilter']
# Simulated CoreAudio inputs must retain their IDs and non-loopback flag in
# both selectors, including after a refresh, reorder or device disconnection.
import linguaflow.app as desktop
from linguaflow.audio import Device
from linguaflow.recording_state import RecordingState
devices = [Device('coreaudio:mic', '输入 · MacBook 麦克风', False),
           Device('coreaudio:blackhole', '输入 · BlackHole 2ch', False)]
desktop.list_devices = lambda: devices
w.refresh_devices()
w.quick_device.setCurrentIndex(1)
assert w.device.currentData() == ('coreaudio:blackhole', False)
snapshot = w.settings_binding.session_settings(w.device.currentData(), w.audio_config)
assert snapshot.device_id == 'coreaudio:blackhole' and not snapshot.loopback
devices.reverse()
w.refresh_devices()
assert w.quick_device.currentIndex() == w.device.currentIndex() == 0
assert w.quick_device.currentData() == ('coreaudio:blackhole', False)
for state in (RecordingState.STARTING, RecordingState.LISTENING, RecordingState.STOPPING):
    w.set_recording_state(state)
    assert not w.quick_device.isEnabled() and not w.device.isEnabled()
    assert not w.refresh_source.isEnabled()
w.set_recording_state(RecordingState.IDLE)
devices.pop(0)
w.refresh_devices()
assert w.device.currentIndex() == w.quick_device.currentIndex() == -1
assert w.quick_device.currentData() is None
lab = AudioLab({'deepfilter': True, 'df_device': 'cuda', 'df_mix': .4}, parent=w)
assert lab.df_device.findData('cuda') == -1
assert lab.config()['df_device'] == 'cpu' and lab.config()['df_mix'] == .4
assert lab.player is None and lab.audio_output is None
assert 'soundcard' not in sys.modules and 'PySide6.QtMultimedia' not in sys.modules
# Exercise lazy playback with QObject fakes, without importing native multimedia.
from types import SimpleNamespace
from PySide6.QtCore import QObject, Signal
class Player(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    errorOccurred = Signal()
    def setAudioOutput(self, output): self.output = output
    def setSource(self, source): self.source = source
    def play(self): self.playing = True
    def stop(self): self.playing = False
    def setPosition(self, position): self.position = position
class Output(QObject):
    def setVolume(self, volume): self.volume = volume
sys.modules['PySide6.QtMultimedia'] = SimpleNamespace(QAudioOutput=Output, QMediaPlayer=Player)
lab.volume.setValue(35)
lab.play('fixture.wav')
player = lab.player
assert player.playing and lab.audio_output.volume == .35
assert player.source.toLocalFile() == 'fixture.wav'
lab.volume.setValue(65)
assert lab.audio_output.volume == .65
player.durationChanged.emit(2000)
player.positionChanged.emit(500)
assert lab.seek.maximum() == 2000 and lab.seek.value() == 500
lab.seek.sliderMoved.emit(750)
assert player.position == 750
lab.controls['df_mix'].setValue(.5)
assert not player.playing
lab.play('fixture-2.wav')
assert lab.player is player and player.playing
lab.reject()
assert not player.playing and player.source.isEmpty()
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
