"""MLX contracts tested with generated PCM and fake model/process endpoints."""
import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Lock, Thread
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.mlx_asr import MLXClient, choose_cut
from linguaflow.qwen_accurate import QwenAccurateOnline


def client_with_process(process):
    client = MLXClient.__new__(MLXClient)
    client.process = process
    client.request_lock = Lock()
    client.close_lock = Lock()
    client.closed = False
    client.exchange = None
    return client


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
    killed = False
    def kill():
        nonlocal killed
        killed = True
        calls.append('kill')
    def wait(timeout=None):
        calls.append(('wait', timeout))
        if not killed:
            raise subprocess.TimeoutExpired('fixture', timeout)
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(),
        poll=lambda: None, terminate=lambda: calls.append('terminate'),
        kill=kill, wait=wait)
    client = client_with_process(process)
    client.close()
    client.close()
    assert calls == [('wait', 3), 'terminate', ('wait', 2), 'kill', ('wait', 2)]
    assert process.stdin.closed and process.stdout.closed


@pytest.mark.parametrize('read_input', [False, True])
def test_stalled_request_times_out_during_write_or_read_and_reaps_child(read_input):
    code = 'import sys,time\n' + ('sys.stdin.readline()\n' if read_input else '') + 'time.sleep(30)'
    process = subprocess.Popen([sys.executable, '-u', '-c', code], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, encoding='utf-8')
    client = client_with_process(process)
    try:
        # Larger than the OS pipe capacity: a child not reading input must not
        # evade the same deadline that protects a stalled response.
        with pytest.raises(RuntimeError, match='识别请求超时'):
            client.request({'pcm': 'x' * 2_000_000}, timeout=.15)
        assert process.poll() is not None
        assert process.stdin.closed and process.stdout.closed
        assert not client.exchange.is_alive()
    finally:
        client.close()


def test_startup_timeout_closes_child_and_reports_loading_failure(monkeypatch):
    import linguaflow.mlx_asr as module
    process = subprocess.Popen([sys.executable, '-u', '-c', 'import time; time.sleep(30)'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, encoding='utf-8')
    monkeypatch.setattr(module, 'mlx_python', lambda: Path(sys.executable))
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **kw: process)
    monkeypatch.setattr(MLXClient, 'startup_timeout', .15)
    with pytest.raises(RuntimeError, match='模型加载超时'):
        MLXClient('fake', 'English', lambda text: None)
    assert process.poll() is not None
    assert process.stdin.closed and process.stdout.closed


def test_close_interrupts_pending_response_without_waiting_for_request_deadline():
    process = subprocess.Popen([sys.executable, '-u', '-c',
                               'import sys,time; sys.stdin.readline(); time.sleep(30)'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, encoding='utf-8')
    client = client_with_process(process)
    errors = []
    def request():
        try:
            client.request({'pcm': 'test'}, timeout=30)
        except RuntimeError as exc:
            errors.append(str(exc))
    worker = Thread(target=request)
    worker.start()
    # Serialize behind request startup so close observes its active IO thread.
    with client.close_lock:
        exchange = client.exchange
    if exchange is None:
        # The request thread can still be awaiting its first scheduling slice.
        from time import monotonic, sleep
        deadline = monotonic() + 2
        while client.exchange is None and monotonic() < deadline:
            sleep(.001)
    try:
        client.close()
        worker.join(timeout=3)
        assert not worker.is_alive() and errors
        assert process.poll() is not None
    finally:
        client.close()
        worker.join(timeout=3)


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


@pytest.mark.parametrize('seconds', [18, 35, 46])
def test_worker_accepts_configured_long_window_and_rejects_unbounded_pcm(monkeypatch, tmp_path, seconds):
    from linguaflow.mlx_asr_worker import serve
    state = fake_runtime(monkeypatch)
    (tmp_path / 'config.json').write_text(json.dumps(
        {'model_type': 'qwen3_asr', 'quantization': {'bits': 4}}))
    pcm = np.ones(seconds * 16000, dtype='<f4')
    inputs = iter([{'model': str(tmp_path), 'language': 'English'},
                   {'pcm': base64.b64encode(pcm.tobytes()).decode()}, {'type': 'stop'}])
    events = []
    if seconds > 45:
        with pytest.raises(ValueError, match='0–45'):
            serve(lambda: next(inputs), events.append)
        assert not state['calls']
    else:
        serve(lambda: next(inputs), events.append)
        assert events[-1]['type'] == 'result'
        np.testing.assert_array_equal(state['calls'][0][0], pcm)
