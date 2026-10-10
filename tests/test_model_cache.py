import json
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from linguaflow.model_cache import has_weights, resolve_translation


def test_cached_weights_reused_without_network(tmp_path, monkeypatch):
    (tmp_path / "pytorch_model.bin").write_bytes(b'weights')
    (tmp_path / "config.json").write_text('{}')
    (tmp_path / "tokenizer_config.json").write_text("{}")

    def snapshot(repo, **kwargs):
        assert kwargs == {"local_files_only": True}
        return str(tmp_path)

    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot, HfApi=lambda: None)
    )
    assert resolve_translation("facebook/test", lambda s: None) == str(tmp_path)


def test_sharded_model_requires_all_shards(tmp_path):
    (tmp_path / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"a": "one.safetensors", "b": "two.safetensors"}})
    )
    (tmp_path / "one.safetensors").write_bytes(b'shard1')
    assert not has_weights(tmp_path)
    (tmp_path / "two.safetensors").write_bytes(b'shard2')
    assert has_weights(tmp_path)


def test_model_manager_can_still_prepare_translation(tmp_path, monkeypatch):
    from linguaflow.management import ModelManager

    monkeypatch.setitem(sys.modules, 'huggingface_hub',
                        SimpleNamespace(snapshot_download=None, HfApi=None))
    completed = []
    commands = []
    manager = SimpleNamespace(
        preparation_selection=lambda: dict(backend='wlk-whisper', asr_model='tiny',
                                           translation_engine='pytorch', translation_model='old',
                                           translation_device='cpu'),
        prepare=lambda action, **kwargs: completed.append(action()),
        run_preparation=lambda command: commands.append(command) or 'verified in child')
    manager.prepare_selected = lambda selection, **kwargs: ModelManager.prepare_selected(manager, selection, **kwargs)
    ModelManager.prepare_translation(manager, str(tmp_path))
    assert completed == ['verified in child']
    assert 'linguaflow.recommended_prepare' in commands[0]
    selection = json.loads(commands[0][commands[0].index('--selection')+1])
    assert selection['translation_model'] == str(tmp_path)
    assert commands[0][-2:] == ['--only', 'translation']


def test_download_selects_one_weight_format(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr('linguaflow.download_progress.hub_progress', lambda: nullcontext())

    def snapshot(repo, **kwargs):
        calls.append(kwargs)
        if kwargs.get("local_files_only"):
            raise OSError("no cache")
        (tmp_path / 'model.safetensors').write_bytes(b'weights')
        (tmp_path / 'config.json').write_text('{}')
        (tmp_path / 'tokenizer_config.json').write_text('{}')
        return str(tmp_path)

    api = SimpleNamespace(list_repo_files=lambda repo: ["model.safetensors", "pytorch_model.bin"])
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot, HfApi=lambda: api)
    )
    assert resolve_translation("test/model", lambda s: None, allow_download=True) == str(tmp_path)
    assert "*.safetensors" in calls[-1]["allow_patterns"]
    assert "*.bin" not in calls[-1]["allow_patterns"]


def test_incomplete_qwen_is_rejected_before_listening(tmp_path):
    from linguaflow.model_cache import resolve_qwen_cached
    (tmp_path / "model-00001-of-00002.safetensors").write_bytes(b"partial")
    with pytest.raises(ValueError, match="模型未下载完整"):
        resolve_qwen_cached(str(tmp_path))


@pytest.mark.parametrize('index', ['{bad json', '{"weight_map":{}}',
                                '{"weight_map":{"a":"../outside.safetensors"}}'])
def test_invalid_shard_index_never_claims_readiness(tmp_path, index):
    (tmp_path / 'model.safetensors.index.json').write_text(index)
    (tmp_path.parent / 'outside.safetensors').write_bytes(b'weights')
    assert not has_weights(tmp_path)


def test_zero_byte_weight_and_hidden_listening_download_are_rejected(tmp_path, monkeypatch):
    (tmp_path / 'model.safetensors').touch()
    assert not has_weights(tmp_path)
    def snapshot(model, **kwargs):
        assert kwargs == {'local_files_only': True}
        raise OSError('not cached')
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(snapshot_download=snapshot, HfApi=lambda: None))
    with pytest.raises(ValueError, match='开始聆听不会下载模型'):
        resolve_translation('example/model', lambda _: None)


def test_whisper_uses_existing_xdg_cache_without_importing_runtime(tmp_path, monkeypatch):
    from linguaflow.model_cache import resolve_whisper_cached
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    checkpoint = tmp_path / 'whisper' / 'large-v3.pt'
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b'cached checkpoint')
    monkeypatch.setitem(sys.modules, 'whisperlivekit.whisper', None)
    assert resolve_whisper_cached('large') == str(checkpoint.resolve())
    checkpoint.write_bytes(b'')
    with pytest.raises(ValueError, match='开始聆听不会下载模型'):
        resolve_whisper_cached('large')


def test_whisper_does_not_resolve_remote_names_or_incomplete_directories(tmp_path):
    from linguaflow.model_cache import resolve_whisper_cached
    with pytest.raises(ValueError, match='开始聆听不会下载模型'):
        resolve_whisper_cached('example/missing-whisper')
    (tmp_path / 'model.safetensors.index.json').write_text('{"weight_map":{"a":"missing.safetensors"}}')
    with pytest.raises(ValueError, match='开始聆听不会下载模型'):
        resolve_whisper_cached(str(tmp_path))


def test_whisper_preparation_keeps_old_checkpoint_on_failed_download(tmp_path, monkeypatch):
    import hashlib
    import io

    from linguaflow import wlk_prepare
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    target = tmp_path / 'whisper' / 'tiny.pt'
    target.parent.mkdir()
    target.write_bytes(b'old invalid checkpoint')
    good = b'new checkpoint'
    url = 'https://example.invalid/' + hashlib.sha256(good).hexdigest() + '/tiny.pt'
    monkeypatch.setitem(sys.modules, 'whisperlivekit.whisper', SimpleNamespace(_MODELS={'tiny': url}))
    monkeypatch.setattr(wlk_prepare.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'partial'))
    with pytest.raises(ValueError, match='校验失败'):
        wlk_prepare.prepare('tiny')
    assert target.read_bytes() == b'old invalid checkpoint'
    monkeypatch.setattr(wlk_prepare.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(good))
    assert wlk_prepare.prepare('tiny') == str(target.resolve())
    assert target.read_bytes() == good
    monkeypatch.setattr(wlk_prepare.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('downloaded valid cache'))
    assert wlk_prepare.prepare('tiny') == str(target.resolve())


@pytest.mark.parametrize('config', [
    {'model_type': 'qwen3_forced_aligner', 'quantization': {'bits': 4}},
    {'model_type': 'qwen3_asr', 'quantization': {'bits': 4},
     'thinker_config': {'model_type': 'qwen3_forced_aligner'}},
])
def test_mlx_rejects_alignment_weights_before_loading(tmp_path, config):
    from linguaflow.model_cache import validate_mlx_model
    (tmp_path / 'config.json').write_text(json.dumps(config))
    with pytest.raises(ValueError, match='Qwen3-ASR'):
        validate_mlx_model(tmp_path)
    from linguaflow.qwen_accurate import build_official_online
    with pytest.raises(ValueError, match='Qwen3-ASR'):
        build_official_online(str(tmp_path), 'cpu', 'en', .5, 30)
