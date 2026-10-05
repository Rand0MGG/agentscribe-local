"""Retired offline options must not change the worker's network environment."""
import io
import json
import os
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('inherited', [None, '0', '1'])
def test_legacy_offline_setting_does_not_change_worker_environment(monkeypatch, inherited):
    from linguaflow import wlk_worker

    if inherited is None:
        monkeypatch.delenv('HF_HUB_OFFLINE', raising=False)
    else:
        monkeypatch.setenv('HF_HUB_OFFLINE', inherited)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({'offline': True}) + '\n'))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    observed = []

    async def serve(settings, emit, read):
        observed.append(os.environ.get('HF_HUB_OFFLINE'))

    monkeypatch.setattr(wlk_worker, 'serve', serve)
    monkeypatch.setattr(wlk_worker, 'prepare_runtime', lambda: None)
    monkeypatch.setattr(wlk_worker, 'release_runtime_models', lambda: None)
    wlk_worker.main()
    assert observed == [inherited]
    assert os.environ.get('HF_HUB_OFFLINE') == inherited


@pytest.mark.parametrize('inherited', [None, '0', '1'])
def test_mlx_worker_does_not_force_offline(monkeypatch, inherited):
    from linguaflow import mlx_asr_worker

    if inherited is None:
        monkeypatch.delenv('HF_HUB_OFFLINE', raising=False)
    else:
        monkeypatch.setenv('HF_HUB_OFFLINE', inherited)
    monkeypatch.setenv('TOKENIZERS_PARALLELISM', 'false')
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    monkeypatch.setattr(mlx_asr_worker.threading, 'Thread',
                        lambda **kwargs: SimpleNamespace(start=lambda: None))
    observed = []
    monkeypatch.setattr(mlx_asr_worker, 'serve',
                        lambda read, emit: observed.append(os.environ.get('HF_HUB_OFFLINE')))
    mlx_asr_worker.main()
    assert observed == [inherited]
    assert os.environ.get('HF_HUB_OFFLINE') == inherited
