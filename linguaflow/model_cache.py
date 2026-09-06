"""Resolve exactly one weight format, then load offline to avoid auto-conversion."""

import json
from pathlib import Path


def has_weights(path):
    path = Path(path)
    for name in ("model.safetensors", "pytorch_model.bin"):
        if (path / name).is_file():
            return True
    for name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
        index = path / name
        if index.is_file():
            shards = json.loads(index.read_text(encoding="utf-8"))["weight_map"].values()
            if all((path / shard).is_file() for shard in shards):
                return True
    return False


def resolve_translation(model, offline, report):
    from huggingface_hub import HfApi, snapshot_download

    if Path(model).is_dir():
        return model
    try:
        cached = snapshot_download(model, local_files_only=True)
        if has_weights(cached) and (Path(cached) / "tokenizer_config.json").exists():
            report("翻译模型：使用已下载缓存，不下载第二份权重")
            return cached
    except OSError:
        pass
    if offline:
        raise RuntimeError("离线缓存不完整，请取消严格离线下载一次，或选择完整模型目录。")
    files = HfApi().list_repo_files(model)
    safe = any(f.endswith(".safetensors") for f in files)
    patterns = ["*.json", "*.model", "*.txt", "*.safetensors" if safe else "*.bin"]
    report("正在下载翻译模型（单份权重），下载进度见终端；下载完成后自动加载")
    return snapshot_download(model, allow_patterns=patterns)
