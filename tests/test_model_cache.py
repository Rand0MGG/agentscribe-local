import json
import sys
from types import SimpleNamespace

import pytest

from linguaflow.model_cache import has_weights, resolve_translation


def test_cached_weights_reused_without_network(tmp_path, monkeypatch):
    (tmp_path / "pytorch_model.bin").touch()
    (tmp_path / "tokenizer_config.json").write_text("{}")

    def snapshot(repo, **kwargs):
        assert kwargs == {"local_files_only": True}
        return str(tmp_path)

    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot, HfApi=lambda: None)
    )
    assert resolve_translation("facebook/test", False, lambda s: None) == str(tmp_path)


def test_sharded_model_requires_all_shards(tmp_path):
    (tmp_path / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"a": "one.safetensors", "b": "two.safetensors"}})
    )
    (tmp_path / "one.safetensors").touch()
    assert not has_weights(tmp_path)
    (tmp_path / "two.safetensors").touch()
    assert has_weights(tmp_path)


def test_download_selects_one_weight_format(monkeypatch):
    calls = []

    def snapshot(repo, **kwargs):
        calls.append(kwargs)
        if kwargs.get("local_files_only"):
            raise OSError("no cache")
        return "downloaded"

    api = SimpleNamespace(list_repo_files=lambda repo: ["model.safetensors", "pytorch_model.bin"])
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot, HfApi=lambda: api)
    )
    assert resolve_translation("test/model", False, lambda s: None) == "downloaded"
    assert "*.safetensors" in calls[-1]["allow_patterns"]
    assert "*.bin" not in calls[-1]["allow_patterns"]


def test_incomplete_qwen_is_rejected_before_listening(tmp_path):
    from linguaflow.model_cache import resolve_qwen_cached
    (tmp_path / "model-00001-of-00002.safetensors").write_bytes(b"partial")
    with pytest.raises(ValueError, match="模型未下载完整"):
        resolve_qwen_cached(str(tmp_path))
