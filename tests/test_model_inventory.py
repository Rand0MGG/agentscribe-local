import json

import pytest

from linguaflow import model_inventory as inventory


def fixture_models(monkeypatch, tmp_path):
    managed, hub, whisper = (tmp_path / name for name in ('models', 'hub', 'whisper'))
    monkeypatch.setattr(inventory, 'model_directory', lambda name: managed / name)
    monkeypatch.setattr(inventory, 'hub_root', lambda: hub)
    monkeypatch.setattr(inventory, 'whisper_cache_root', lambda: whisper)
    return managed, hub, whisper


def weights(path, model_type='qwen3_asr'):
    path.mkdir(parents=True)
    (path / 'model.safetensors').write_bytes(b'fixture')
    (path / 'config.json').write_text(json.dumps(dict(model_type=model_type, quantization={'bits': 4})))


def test_inventory_reuses_managed_hub_and_whisper_without_model_imports(monkeypatch, tmp_path):
    managed, hub, whisper = fixture_models(monkeypatch, tmp_path)
    qwen = managed / 'Qwen3-ASR-1.7B-4bit'
    weights(qwen)
    gguf = managed / 'Hy-MT2-1.8B-GGUF' / 'Hy-MT2-1.8B-Q4_K_M.gguf'
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b'gguf fixture')
    snapshot = hub / 'models--facebook--nllb-200' / 'snapshots' / 'abc'
    weights(snapshot, 'm2m_100')
    whisper.mkdir()
    (whisper / 'tiny.pt').write_bytes(b'whisper fixture')
    items = inventory.inventory([dict(path=str(qwen), kind='asr')])
    assert len(items) == 4
    assert {item['engine'] for item in items} == {'qwen3-mlx', 'llama', 'pytorch', 'wlk-whisper'}
    assert all(item['size'] > 0 and item['deletable'] for item in items)
    inventory.delete_model(str(gguf))
    assert not gguf.exists() and qwen.exists()
    repo = snapshot.parents[1]
    inventory.delete_model(str(repo))
    assert not repo.exists() and whisper.exists()


def test_delete_rejects_custom_paths_unknown_ids_and_links(monkeypatch, tmp_path):
    managed, _, _ = fixture_models(monkeypatch, tmp_path)
    custom = tmp_path / 'my models'
    weights(custom)
    selected = [dict(path=str(custom), kind='asr', engine='qwen3-mlx')]
    assert inventory.inventory(selected)[0]['deletable'] is False
    for identifier in (str(custom), str(tmp_path), str(custom / '..')):
        with pytest.raises(ValueError):
            inventory.delete_model(identifier, selected)
    managed.mkdir()
    link = managed / 'Qwen3-ASR-1.7B-4bit'
    link.symlink_to(custom, target_is_directory=True)
    with pytest.raises(ValueError):
        inventory.delete_model(str(link), selected)
    assert (custom / 'model.safetensors').exists()


def test_forced_aligner_is_auxiliary_not_selectable_as_asr(monkeypatch, tmp_path):
    _, hub, _ = fixture_models(monkeypatch, tmp_path)
    snapshot = hub / 'models--Qwen--Qwen3-ForcedAligner-0.6B' / 'snapshots' / 'abc'
    weights(snapshot)
    entry, = inventory.inventory()
    assert entry['kind'] == 'alignment' and entry['engine'] is None
    assert entry['deletable']


def test_custom_qwen_format_wins_over_saved_whisper_backend(monkeypatch, tmp_path):
    fixture_models(monkeypatch, tmp_path)
    custom = tmp_path / 'custom'
    weights(custom)
    item, = inventory.inventory([dict(path=str(custom), kind='asr', engine='wlk-whisper')])
    assert item['engine'] == 'qwen3-mlx'
