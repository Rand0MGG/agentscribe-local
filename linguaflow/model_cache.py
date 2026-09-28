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


def resolve_qwen_cached(model):
    """Listening never hides a multi-gigabyte Qwen download behind startup."""
    from huggingface_hub import snapshot_download
    if model == 'mlx-community/Qwen3-ASR-1.7B-4bit':
        bundled = Path(__file__).resolve().parents[1] / 'models' / 'Qwen3-ASR-1.7B-4bit'
        if has_weights(bundled):
            model = str(bundled)
    try:
        path = Path(model) if Path(model).is_dir() else Path(snapshot_download(model, local_files_only=True))
        if has_weights(path) and all((path / name).is_file() for name in
                                     ("config.json", "tokenizer_config.json")):
            return str(path.resolve())
    except OSError:
        pass
    raise ValueError(f"Qwen 模型未下载完整：{model}。请打开模型管理 → 识别模型 → 下载 / 检查 Qwen 模型，完成后再聆听。")


def validate_mlx_model(path):
    """Reject incompatible weights before starting a GPU worker."""
    try:
        config = json.loads((Path(path) / 'config.json').read_text(encoding='utf-8'))
        quant = config.get('quantization', config.get('quantization_config', {}))
        valid = config.get('model_type') == 'qwen3_asr' and quant.get('bits') == 4
    except (OSError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError('Apple GPU 识别需要 Qwen3-ASR 的 MLX 4-bit 权重；请选择对应模型。')


def resolve_translation(model, offline, report):
    from huggingface_hub import HfApi, snapshot_download

    if Path(model).is_dir():
        return model
    # Reuse the optional project-local HY package installed by the CLI as well
    # as Hub caches. Selecting the built-in model must not download it twice.
    from .translation_models import HY_MODEL, is_hy_model
    bundled = Path(__file__).resolve().parents[1] / 'models' / 'Hy-MT2-1.8B'
    if (model == HY_MODEL and has_weights(bundled) and is_hy_model(str(bundled))
            and all((bundled / name).is_file() for name in
                    ('tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja'))):
        report('翻译模型：使用项目内已下载的 HY-MT2 权重')
        return str(bundled)
    try:
        cached = snapshot_download(model, local_files_only=True)
        if (has_weights(cached) and (Path(cached) / "tokenizer_config.json").exists()
                and (not is_hy_model(model) or (Path(cached) / 'chat_template.jinja').exists())):
            report("翻译模型：使用已下载缓存，不下载第二份权重")
            return cached
    except OSError:
        pass
    if offline:
        raise RuntimeError("离线缓存不完整，请取消严格离线下载一次，或选择完整模型目录。")
    files = HfApi().list_repo_files(model)
    safe = any(f.endswith(".safetensors") for f in files)
    patterns = ["*.json", "*.model", "*.txt", "*.jinja", "*.safetensors" if safe else "*.bin"]
    report("正在下载翻译模型（单份权重），下载进度见终端；下载完成后自动加载")
    return snapshot_download(model, allow_patterns=patterns, max_workers=1)
