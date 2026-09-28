"""MLX contracts tested with generated PCM and fake model/process endpoints."""
import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.mlx_asr import MLXClient, choose_cut
from linguaflow.qwen_accurate import QwenAccurateOnline


def test_bounded_windows_preserve_every_sample_and_flush_once():
    decoded = []
    def decode(audio):
        decoded.append(audio.copy())
        return str(len(audio))
    online = QwenAccurateOnline(decode, choose_cut, 'en', window_seconds=12,
                               token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    audio = np.ones(40 * 16000, np.float32)
    online.insert_audio_chunk(audio, 40.)
    tokens, _ = online.finish()
    assert sum(len(part) for part in decoded) == len(audio)
    assert all(0 < len(part) <= 17 * 16000 for part in decoded)
    assert tokens[0].start == 0 and tokens[-1].end == 40
    assert online.finish()[0] == []


def test_cut_uses_quiet_region_near_boundary():
    audio = np.ones(17 * 16000, np.float32)
    audio[12*16000:12*16000+1600] = 0
    assert choose_cut(audio, 12) == 12*16000


def test_client_model_failure_closes_process_and_pipes(monkeypatch):
    import linguaflow.mlx_asr as module
    calls = []
    process = SimpleNamespace(stdin=io.StringIO(),
        stdout=io.StringIO(json.dumps({'type': 'error', 'text': 'wrong weights'})+'\n'),
        poll=lambda: None, terminate=lambda: calls.append('terminate'),
        wait=lambda **kw: calls.append('wait'))
    monkeypatch.setattr(module, 'mlx_python', lambda: Path(sys.executable))
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **kw: process)
    with pytest.raises(RuntimeError, match='wrong weights'):
        MLXClient('fake', 'English', lambda text: None)
    assert calls == ['wait']
    assert process.stdin.closed and process.stdout.closed


def test_client_close_escalates_only_when_helper_ignores_stop():
    calls = []
    def wait(timeout=None):
        calls.append(('wait', timeout))
        if timeout is not None:
            raise subprocess.TimeoutExpired('fixture', timeout)
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(),
        poll=lambda: None, terminate=lambda: calls.append('terminate'),
        kill=lambda: calls.append('kill'), wait=wait)
    client = MLXClient.__new__(MLXClient)
    client.process = process
    client.close()
    assert calls == [('wait', 3), 'terminate', ('wait', 2), 'kill', ('wait', None)]
    assert process.stdin.closed and process.stdout.closed


def fake_runtime(monkeypatch, available=True):
    state = {'device': 'cpu', 'calls': []}
    mx = SimpleNamespace(metal=SimpleNamespace(is_available=lambda: available), gpu='gpu',
        set_default_device=lambda device: state.update(device=device),
        default_device=lambda: state['device'], set_cache_limit=lambda _: None,
        set_memory_limit=lambda _: None, get_active_memory=lambda: 123,
        get_peak_memory=lambda: 456, synchronize=lambda: None, clear_cache=lambda: None)
    def generate(audio, **kwargs):
        state['calls'].append((audio, kwargs))
        return SimpleNamespace(text=' hello ')
    monkeypatch.setitem(sys.modules, 'mlx', SimpleNamespace(core=mx))
    monkeypatch.setitem(sys.modules, 'mlx.core', mx)
    monkeypatch.setitem(sys.modules, 'mlx_audio.stt.utils', SimpleNamespace(
        load_model=lambda _: SimpleNamespace(generate=generate)))
    return state


def test_worker_rejects_cpu_without_loading_model(monkeypatch):
    from linguaflow.mlx_asr_worker import serve
    fake_runtime(monkeypatch, available=False)
    with pytest.raises(RuntimeError, match='不会回退 CPU'):
        serve(lambda: pytest.fail('must not read model settings'), lambda _: None)


@pytest.mark.parametrize('bits', [4, 8])
def test_worker_pcm_contract_and_quantization_validation(monkeypatch, tmp_path, bits):
    from linguaflow.mlx_asr_worker import serve
    state = fake_runtime(monkeypatch)
    (tmp_path/'config.json').write_text(json.dumps(
        {'model_type': 'qwen3_asr', 'quantization': {'bits': bits}}))
    pcm = np.linspace(-.1, .1, 16000, dtype='<f4')
    inputs = iter([{'model': str(tmp_path), 'language': 'English'},
                   {'pcm': base64.b64encode(pcm.tobytes()).decode()}, {'type': 'stop'}])
    events = []
    if bits != 4:
        with pytest.raises(ValueError, match='4-bit'):
            serve(lambda: next(inputs), events.append)
        assert not state['calls']
    else:
        serve(lambda: next(inputs), events.append)
        assert [e['type'] for e in events] == ['ready', 'result']
        assert events[-1]['text'] == 'hello' and events[-1]['device'] == 'gpu'
        np.testing.assert_array_equal(state['calls'][0][0], pcm)
        assert state['calls'][0][1]['language'] == 'English'


def test_mac_profile_roundtrip_and_backend_switch_do_not_open_audio(tmp_path):
    code = '''
import os,sys
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
app = QApplication([])
prefs = QSettings(os.environ['AGENTSCRIBE_LIBRARY'] + '/prefs.ini', QSettings.Format.IniFormat)
w = Window(discover=False, prefs=prefs)
w.use_mac_profile()
settings = w.settings_binding.session_settings(('file', False), {})
assert settings.backend == 'qwen3-mlx' and settings.asr_device == 'mlx'
assert settings.qwen_model.endswith('1.7B-4bit')
assert settings.semantic_device == 'cpu' and not settings.translate
w.save()
w.model_manager.backend.setCurrentIndex(0)
assert w.compute.currentData() == 'cpu' and w.compute.isEnabled()
w.restore()
assert w.compute.currentData() == 'mlx' and not w.compute.isEnabled()
assert w.model_manager.qwen_model.currentText().endswith('1.7B-4bit')
assert 'soundcard' not in sys.modules and 'PySide6.QtMultimedia' not in sys.modules
w.close()
'''
    if sys.platform != 'darwin':
        pytest.skip('Mac UI profile')
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
        timeout=20, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                        'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
