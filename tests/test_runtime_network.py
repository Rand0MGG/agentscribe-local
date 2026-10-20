"""The MLX entrypoint preserves the caller's network environment."""
import io
import os
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('inherited', [None, '1'])
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
