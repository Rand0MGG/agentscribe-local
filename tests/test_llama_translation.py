import io
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from linguaflow import llama_assets
from linguaflow.backends import create_translator
from linguaflow.core import Settings
from linguaflow.llama_translation import LlamaTranslator
from linguaflow.translation_context import TranslationContext
from linguaflow.translation_models import HY_MODEL


def test_metal_factory_does_not_import_torch_or_fall_back(monkeypatch):
    import linguaflow.llama_translation as module
    seen = []
    def unavailable(settings, report):
        seen.append(settings.translation_device)
        raise ValueError('Metal unavailable')
    monkeypatch.setattr(module, 'LlamaTranslator', unavailable)
    with pytest.raises(ValueError, match='Metal unavailable'):
        create_translator(Settings('test', translation_model=HY_MODEL, translation_device='metal'))
    assert seen == ['metal']


def test_missing_or_wrong_assets_are_rejected_without_download(tmp_path, monkeypatch):
    monkeypatch.setattr(llama_assets, 'runtime_archives', lambda _: [])
    monkeypatch.setattr(llama_assets, 'llama_server', lambda _: tmp_path/'llama-server')
    monkeypatch.setattr(llama_assets, 'model_path', lambda: tmp_path/'model.gguf')
    with pytest.raises(ValueError, match='下载 / 检查'):
        llama_assets.resolve_assets(Settings('test', translation_model=HY_MODEL))
    (tmp_path/'llama-server').touch()
    (tmp_path/'model.gguf').write_bytes(b'incomplete')
    with pytest.raises(ValueError, match='权重无效'):
        llama_assets.resolve_assets(Settings('test', translation_model=HY_MODEL))
    (tmp_path/'model.gguf').write_bytes(b'GGUFfixture')
    assert llama_assets.resolve_assets(Settings('test', translation_model=HY_MODEL))[1] == tmp_path/'model.gguf'
    with pytest.raises(ValueError, match='请选择'):
        llama_assets.resolve_assets(Settings('test'))


@pytest.mark.parametrize('finish, content, valid', [('stop', '  译文  ', True), ('length', '半句', False), ('stop', '', False)])
def test_translation_preserves_context_and_rejects_incomplete_output(finish, content, valid):
    translator = LlamaTranslator.__new__(LlamaTranslator)
    translator.closed = False
    translator.process = SimpleNamespace(poll=lambda: None)
    translator.target, translator.source = 'zho_Hans', 'eng_Latn'
    def request(path, payload):
        if path == '/apply-template':
            return {'prompt': payload['messages'][0]['content']}
        if path == '/tokenize':
            return {'tokens': [1] * 100}
        assert path == '/v1/chat/completions'
        assert 'We watched birds.' in payload['messages'][0]['content']
        assert payload['messages'][0]['content'].endswith('[Source Text]\nThe crane moved.')
        return {'choices': [{'finish_reason': finish, 'message': {'content': content}}]}
    translator.request = request
    if valid:
        assert translator.translate('The crane moved.', 'en', TranslationContext(('We watched birds.',))) == '译文'
    else:
        with pytest.raises(ValueError, match='未完整'):
            translator.translate('The crane moved.', 'en', TranslationContext(('We watched birds.',)))


def test_startup_requires_actual_full_gpu_offload_and_closes_failed_helper(monkeypatch):
    import linguaflow.llama_translation as module
    monkeypatch.setattr(module, 'resolve_assets', lambda _: (Path('fake'), Path('fake.gguf')))
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, _): pass
        def getsockname(self): return ('127.0.0.1', 1234)
    monkeypatch.setattr(module.socket, 'socket', lambda: Socket())
    calls = []
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO('CPU only\n'),
                              poll=lambda: None, wait=lambda **_: calls.append('wait'))
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: process)
    monkeypatch.setattr(LlamaTranslator, 'request', lambda *a, **kw: {'status': 'ok'})
    monkeypatch.setattr(LlamaTranslator, 'startup_timeout', .02)
    with pytest.raises(RuntimeError, match='未在'):
        LlamaTranslator(Settings('test', translation_model=HY_MODEL, translation_device='metal'))
    assert calls == ['wait'] and process.stdin.closed and process.stdout.closed


@pytest.mark.parametrize('device', ['cpu', 'metal', 'cuda', 'vulkan'])
def test_server_disables_historical_prompt_cache_for_long_sessions(monkeypatch, device):
    import linguaflow.llama_translation as module
    monkeypatch.setattr(module, 'resolve_assets', lambda _: (Path('fake'), Path('fake.gguf')))
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, _): pass
        def getsockname(self): return ('127.0.0.1', 1234)
    monkeypatch.setattr(module.socket, 'socket', lambda: Socket())
    device_id = {'metal': 'MTL0', 'cuda': 'CUDA0', 'vulkan': 'Vulkan0', 'cpu': 'none'}[device]
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(
        f'using device {device_id}\noffloaded 33/33 layers to GPU\n'),
        poll=lambda: None, wait=lambda **_: None)
    commands = []
    def start(command, **kwargs):
        commands.append(command)
        return process
    monkeypatch.setattr(module.subprocess, 'Popen', start)
    monkeypatch.setattr(LlamaTranslator, 'request', lambda *a, **kw: {'status': 'ok'})
    translator = LlamaTranslator(Settings('test', translation_model=HY_MODEL, translation_device=device))
    try:
        command = commands[0]
        # b11254 otherwise keeps up to 8192 MiB of previous prompt KV states.
        assert '--cache-ram' in command
        assert command[command.index('--cache-ram') + 1] == '0'
        assert '--no-cache-idle-slots' in command
        assert command[command.index('-c') + 1] == '4096'
    finally:
        translator.close()


@pytest.mark.skipif(sys.platform == 'win32', reason='Metal supervisor is used on macOS')
@pytest.mark.parametrize('end', ['eof', 'terminate', 'child_exit'])
def test_supervisor_stops_only_owned_child_when_parent_pipe_closes(end):
    delay = '.1' if end == 'child_exit' else '30'
    command = [sys.executable, '-u', '-m', 'linguaflow.managed_process', sys.executable, '-u', '-c',
               f'import os,time; print(os.getpid(), flush=True); time.sleep({delay})']
    supervisor = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
    child = None
    try:
        import select
        assert select.select([supervisor.stdout], [], [], 5)[0]
        child = int(supervisor.stdout.readline())
        if end == 'eof':
            supervisor.stdin.close()
        elif end == 'terminate':
            supervisor.terminate()
        code = supervisor.wait(timeout=6)
        stderr = supervisor.stderr.read()
        assert code == 0, (code, stderr)
        assert 'Fatal Python error' not in stderr
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(.02)
        else:
            pytest.fail('Native child survived its owner')
    finally:
        if supervisor.poll() is None:
            supervisor.terminate()
            supervisor.wait(timeout=6)
        supervisor.stdin.close()
        supervisor.stdout.close()
        supervisor.stderr.close()


@pytest.mark.parametrize('engine,device,expected', [(None, 'metal', 'llama'), (None, 'cpu', 'pytorch'),
                                                   ('llama', 'cpu', 'llama'), ('pytorch', 'cuda', 'pytorch')])
def test_engine_selection_is_independent_of_device(engine, device, expected):
    from linguaflow.translation_models import translation_engine
    assert translation_engine(Settings('test', translation_engine=engine, translation_device=device)) == expected


def test_custom_gguf_and_shared_generation_settings(tmp_path, monkeypatch):
    from linguaflow.translation_models import HY_GENERATION, llama_generation
    weights = tmp_path/'custom-f16.gguf'
    weights.write_bytes(b'GGUFfixture')
    binary = tmp_path/'llama-server'
    binary.touch()
    monkeypatch.setattr(llama_assets, 'runtime_archives', lambda _: [])
    monkeypatch.setattr(llama_assets, 'llama_server', lambda _: binary)
    settings = Settings('test', translation_engine='llama', llama_model=str(weights))
    assert llama_assets.resolve_assets(settings) == (binary, weights)
    payload = llama_generation()
    assert payload['max_tokens'] == HY_GENERATION['max_new_tokens']
    assert payload['repeat_penalty'] == HY_GENERATION['repetition_penalty']
    assert {key:payload[key] for key in ('temperature', 'top_p', 'top_k')} == {
        key:HY_GENERATION[key] for key in ('temperature', 'top_p', 'top_k')}


@pytest.mark.parametrize('device,log,accepted', [
    ('metal', 'using device MTL0 (Apple M2)\noffloaded 33/33 layers to GPU\n', True),
    ('cuda', 'using device CUDA0 (NVIDIA)\noffloaded 33/33 layers to GPU\n', True),
    ('vulkan', 'using device Vulkan0 (GPU)\noffloaded 33/33 layers to GPU\n', True),
    ('cuda', 'using device CUDA0 (NVIDIA)\noffloaded 20/33 layers to GPU\n', False),
    ('metal', 'using device CUDA0 (NVIDIA)\noffloaded 33/33 layers to GPU\n', False),
])
def test_gpu_confirmation_requires_selected_device_and_all_layers(device, log, accepted):
    translator = LlamaTranslator.__new__(LlamaTranslator)
    translator.device_id = {'metal':'MTL0', 'cuda':'CUDA0', 'vulkan':'Vulkan0'}[device]
    translator.device_confirmed, translator.gpu_layers = False, None
    translator.recent = []
    translator.process = SimpleNamespace(stdout=io.StringIO(log))
    translator.read_logs()
    assert bool(translator.device_confirmed and translator.gpu_layers) is accepted
