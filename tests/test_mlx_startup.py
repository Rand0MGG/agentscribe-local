import asyncio
import io
import json
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

import linguaflow.mlx_asr as mlx


def controlled_process(monkeypatch, reply):
    entered, release, exited = Event(), Event(), Event()
    class Output(io.StringIO):
        def readline(self):
            entered.set()
            assert release.wait(3), 'test did not release model initialization'
            return '' if exited.is_set() else json.dumps(reply) + '\n'
    def stop():
        exited.set()
        release.set()
    process = SimpleNamespace(stdin=io.StringIO(), stdout=Output(),
                              poll=lambda: 0 if exited.is_set() else None,
                              terminate=stop, kill=stop, wait=lambda **_: stop())
    monkeypatch.setattr(mlx, 'mlx_python', lambda: Path(sys.executable))
    monkeypatch.setattr(mlx.subprocess, 'Popen', lambda *args, **kwargs: process)
    return process, entered, release


def test_background_loading_returns_before_model_is_ready(monkeypatch):
    process, entered, release = controlled_process(monkeypatch,
        {'type': 'ready', 'device': 'Device(gpu, 0)', 'load_seconds': 1.})
    statuses = []
    client = mlx.MLXClient('model', 'English', statuses.append, background=True)
    try:
        assert entered.wait(2)
        assert not client.loaded.is_set() and not statuses
        assert json.loads(process.stdin.getvalue()) == {'model': 'model', 'language': 'English'}
        release.set()
        client.wait_ready()
        assert client.loaded.is_set() and len(statuses) == 1
    finally:
        client.close()
    assert not client.loading.is_alive() and process.stdin.closed and process.stdout.closed


def test_cancel_background_load_interrupts_child_and_releases_threads(monkeypatch):
    process, entered, _ = controlled_process(monkeypatch, {})
    client = mlx.MLXClient('model', 'English', lambda _: None, background=True)
    assert entered.wait(2)
    client.close()
    client.close()
    assert client.loaded.is_set() and not client.loading.is_alive() and not client.exchange.is_alive()
    assert process.poll() is not None and process.stdin.closed and process.stdout.closed
    with pytest.raises(RuntimeError):
        client.wait_ready()


def test_background_model_failure_reaches_readiness_check(monkeypatch):
    process, entered, release = controlled_process(monkeypatch, {'type': 'error', 'text': 'bad weights'})
    client = mlx.MLXClient('model', 'English', lambda _: None, background=True)
    assert entered.wait(2)
    release.set()
    with pytest.raises(RuntimeError, match='bad weights'):
        client.wait_ready()
    assert client.closed and process.poll() is not None


def test_adapter_reuses_loaded_client_and_closes_on_construction_failure(monkeypatch):
    calls = []
    client = SimpleNamespace(wait_ready=lambda: calls.append('ready'), decode=lambda _: 'text',
                             close=lambda: calls.append('close'))
    monkeypatch.setattr(mlx, 'MLXClient', lambda *args, **kwargs: pytest.fail('must not load twice'))
    def adapter(*args, **kwargs):
        assert calls == ['ready']
        raise RuntimeError('adapter failed')
    monkeypatch.setattr(mlx, 'QwenAccurateOnline', adapter)
    with pytest.raises(RuntimeError, match='adapter failed'):
        mlx.build_mlx_online('model', 'en', .5, lambda _: None, client=client)
    assert calls == ['ready', 'close']


@pytest.mark.parametrize(('platform', 'device', 'semantic'), [('win32', 'mlx', 'cpu'),
                         ('darwin', 'cpu', 'cpu'), ('darwin', 'mlx', 'cuda')])
def test_other_routes_do_not_import_or_start_preload(monkeypatch, platform, device, semantic):
    monkeypatch.setattr(mlx.sys, 'platform', platform)
    monkeypatch.setitem(sys.modules, 'onnxruntime', None)
    assert mlx.begin_mlx_loading(dict(asr_device=device, semantic_device=semantic), lambda _: None) is None


@pytest.mark.parametrize('cached', [False, True])
def test_only_prepared_cpu_cache_enables_overlap(monkeypatch, cached):
    import linguaflow.model_cache as models
    import linguaflow.semantic_cache as cache
    import linguaflow.semantic_model as semantic
    monkeypatch.setattr(mlx.sys, 'platform', 'darwin')
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(__version__='1.30.0'))
    monkeypatch.setattr(semantic, 'paths', lambda: ('sat', 'tokenizer'))
    monkeypatch.setattr(cache, 'cached_cpu_model', lambda *args: 'cache' if cached else None)
    monkeypatch.setattr(models, 'resolve_qwen_cached', lambda _: 'qwen')
    calls = []
    def create(model, language, report, background=False):
        calls.append((model, language, background))
        return 'client'
    monkeypatch.setattr(mlx, 'MLXClient', create)
    result = mlx.begin_mlx_loading(dict(asr_device='mlx', source='en'), lambda _: None)
    assert result == ('client' if cached else None)
    assert calls == ([('qwen', 'English', True)] if cached else [])


def test_missing_semantic_runtime_reports_preparation_without_spawning_mlx(monkeypatch):
    monkeypatch.setattr(mlx.sys, 'platform', 'darwin')
    monkeypatch.setitem(sys.modules, 'onnxruntime', None)
    monkeypatch.setattr(mlx, 'MLXClient', lambda *args, **kwargs: pytest.fail('must not spawn'))
    with pytest.raises(RuntimeError, match='SaT 分句模型加载失败.*准备 / 检查'):
        mlx.begin_mlx_loading(dict(asr_device='mlx'), lambda _: None)


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel'])
def test_worker_owns_preload_during_all_initialization_outcomes(monkeypatch, outcome):
    import linguaflow.wlk_worker as worker
    calls = []
    client = SimpleNamespace(close=lambda: calls.append('close'))
    monkeypatch.setattr(mlx, 'begin_mlx_loading', lambda *args: client)
    async def pipeline(settings, emit, read, loaded):
        assert loaded is client
        calls.append('setup')
        if outcome == 'error':
            raise RuntimeError('SaT initialization failed')
        if outcome == 'cancel':
            raise asyncio.CancelledError
    monkeypatch.setattr(worker, '_serve', pipeline)
    if outcome == 'success':
        asyncio.run(worker.serve({'backend': 'qwen3-mlx'}, lambda _: None, None))
    else:
        with pytest.raises(RuntimeError if outcome == 'error' else asyncio.CancelledError):
            asyncio.run(worker.serve({'backend': 'qwen3-mlx'}, lambda _: None, None))
    assert calls == ['setup', 'close']
