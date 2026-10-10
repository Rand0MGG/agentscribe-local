"""Explicit file downloads use the existing preparation worker and local resolver."""
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from linguaflow import llama_assets, llama_install, model_inventory


@pytest.mark.parametrize('reference', [
    'hf://owner/repo/../model.gguf', 'hf://owner/repo/a/../../model.gguf',
    'hf://../repo/model.gguf', 'hf://owner/repo/model.bin',
    'hf://owner/repo/model.gguf?token=secret', 'hf://owner/repo/C:/model.gguf',
    'hf://owner/repo/a\\model.gguf', 'hf://owner/repo//model.gguf',
])
def test_invalid_hub_file_reference_is_rejected(reference):
    with pytest.raises(ValueError):
        llama_assets.hub_gguf(reference)


def test_downloaded_gguf_is_offline_resolvable_listed_and_deletable(monkeypatch, tmp_path):
    monkeypatch.setattr(llama_install, 'hub_progress', nullcontext)
    monkeypatch.setattr(llama_assets, 'model_directory', lambda name: tmp_path / name)
    monkeypatch.setattr(model_inventory, 'model_directory', lambda name: tmp_path / name)
    monkeypatch.setattr(model_inventory, 'hub_root', lambda: tmp_path / 'hub')
    monkeypatch.setattr(model_inventory, 'whisper_cache_root', lambda: tmp_path / 'whisper')
    cached = tmp_path / 'fixture.gguf'
    cached.write_bytes(b'GGUFfixture')
    calls = []
    def download(repo, filename):
        calls.append((repo, filename))
        return str(cached)
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(hf_hub_download=download))
    reference = 'hf://owner/repo/quant/model-Q4_K_M.gguf'
    llama_install.prepare_weights(reference)
    resolved = llama_assets.validate_weights(reference)
    assert resolved.read_bytes() == cached.read_bytes()
    llama_install.prepare_weights(reference)
    assert calls == [('owner/repo', 'quant/model-Q4_K_M.gguf')]
    entry, = model_inventory.inventory()
    assert entry['engine'] == 'llama' and entry['deletable']
    assert entry['selection'] == reference
    model_inventory.delete_model(entry['id'])
    assert not resolved.exists() and cached.exists()


def test_invalid_gguf_never_publishes_ready_file(monkeypatch, tmp_path):
    monkeypatch.setattr(llama_install, 'hub_progress', nullcontext)
    monkeypatch.setattr(llama_assets, 'model_directory', lambda name: tmp_path / name)
    cached = tmp_path / 'invalid.gguf'
    cached.write_bytes(b'html-error')
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(hf_hub_download=lambda *args, **kwargs: str(cached)))
    reference = 'hf://owner/repo/model.gguf'
    with pytest.raises(ValueError, match='无效'):
        llama_install.prepare_weights(reference)
    assert not llama_assets.weights_path(reference).exists()


def test_preparation_repairs_only_confirmed_invalid_cached_header(monkeypatch, tmp_path):
    monkeypatch.setattr(llama_install, 'hub_progress', nullcontext)
    monkeypatch.setattr(llama_assets, 'model_directory', lambda name: tmp_path / name)
    cached = tmp_path / 'cache.gguf'
    cached.write_bytes(b'invalid')
    calls = []
    def download(repo, filename, **kwargs):
        calls.append(kwargs)
        if kwargs.get('force_download'):
            cached.write_bytes(b'GGUFrestored')
        return str(cached)
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(hf_hub_download=download))
    reference = 'hf://owner/repo/model.gguf'
    target = llama_assets.weights_path(reference)
    target.parent.mkdir(parents=True)
    target.write_bytes(b'invalid-old')
    llama_install.prepare_weights(reference)
    assert calls == [{}, {'force_download': True}]
    assert target.read_bytes() == b'GGUFrestored'
