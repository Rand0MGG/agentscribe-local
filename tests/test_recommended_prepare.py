import subprocess

import pytest

from linguaflow import recommended_prepare


@pytest.mark.parametrize('cached', [False, True])
def test_recommended_preparation_reuses_assets_and_orders_missing_dependencies(monkeypatch, tmp_path, cached):
    calls = []
    asset = tmp_path / 'asset'
    if cached:
        asset.write_bytes(b'cached')
    monkeypatch.setattr('linguaflow.hardware.check_installation', lambda: 'macos-arm64')
    for name in ('runtime_python', 'mlx_python', 'model_path'):
        monkeypatch.setattr(recommended_prepare, name, lambda: asset)
    monkeypatch.setattr(recommended_prepare, 'llama_server', lambda _: asset)
    monkeypatch.setattr(recommended_prepare, 'digest', lambda _: recommended_prepare.MODEL_SHA256)
    monkeypatch.setattr(recommended_prepare, 'resolve_qwen_cached', lambda _: str(asset))
    def validate(_):
        if not cached:
            raise ValueError('missing')
    monkeypatch.setattr(recommended_prepare, 'validate_mlx_model', validate)
    monkeypatch.setattr('linguaflow.runtime_install.install', lambda kind: calls.append(kind))
    monkeypatch.setattr('linguaflow.model_prepare.prepare', lambda kind, model: calls.append((kind, model)))
    monkeypatch.setattr('linguaflow.llama_install.install', lambda device, model: calls.append((device, model)))
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: calls.append('semantic'))
    recommended_prepare.main()
    expected = ['semantic'] if cached else ['wlk', 'mlx', ('qwen', recommended_prepare.MLX_MODEL),
                                           'semantic', ('metal', recommended_prepare.HY_GGUF)]
    assert calls == expected


def test_recommended_preparation_rejects_unsupported_platform_before_installing(monkeypatch):
    monkeypatch.setattr('linguaflow.hardware.check_installation', lambda: 'windows-x64')
    with pytest.raises(ValueError, match='Apple Silicon'):
        recommended_prepare.main()
