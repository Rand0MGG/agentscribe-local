"""Reuse local weights and resolve one format before loading to avoid auto-conversion."""

import json
from pathlib import Path

from .runtime_paths import model_directory, whisper_cache_root


def has_weights(path):
    path = Path(path)
    for name in ("model.safetensors", "pytorch_model.bin"):
        if (path / name).is_file() and (path / name).stat().st_size > 0:
            return True
    for name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
        index = path / name
        if index.is_file():
            try:
                mapping = json.loads(index.read_text(encoding="utf-8"))["weight_map"]
                if not isinstance(mapping, dict) or not mapping:
                    continue
                shards = set(mapping.values())
                if all(isinstance(shard, str) and (path / shard).resolve().is_relative_to(path.resolve())
                       and (path / shard).is_file() and (path / shard).stat().st_size > 0 for shard in shards):
                    return True
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return False


def resolve_whisper_cached(model):
    """Pass only local files to AlignAtt; never let model loading download."""
    path = Path(model)
    if not path.exists() and '/' not in model and '\\' not in model:
        name = {'large': 'large-v3', 'turbo': 'large-v3-turbo'}.get(model, model)
        path = whisper_cache_root() / (name + '.pt')
    if path.is_file() and path.suffix.lower() in ('.pt', '.bin', '.safetensors') and path.stat().st_size:
        return str(path.resolve())
    if path.is_dir():
        if (has_weights(path) and (path / 'config.json').is_file()
                or any(file.is_file() and file.stat().st_size for file in path.glob('*.pt'))):
            return str(path.resolve())
    raise ValueError('Whisper 模型文件未准备完整，请到设置 → 识别模型下载 / 检查；开始聆听不会下载模型。')


def resolve_qwen_cached(model):
    """Listening never hides a multi-gigabyte Qwen download behind startup."""
    from huggingface_hub import snapshot_download
    if model == 'mlx-community/Qwen3-ASR-1.7B-4bit':
        bundled = model_directory('Qwen3-ASR-1.7B-4bit')
        if has_weights(bundled):
            model = str(bundled)
    try:
        path = Path(model) if Path(model).is_dir() else Path(snapshot_download(model, local_files_only=True))
        if has_weights(path) and all((path / name).is_file() for name in
                                     ("config.json", "tokenizer_config.json")):
            return str(path.resolve())
    except (OSError, ValueError):
        pass
    raise ValueError(f"Qwen 模型未下载完整：{model}。请打开模型管理 → 识别模型 → 下载 / 检查 Qwen 模型，完成后再聆听。")


def reject_alignment_model(path):
    """Reject auxiliary alignment weights before importing/loading ASR backends."""
    hint = str(path).casefold()
    try:
        config = json.loads((Path(path) / 'config.json').read_text(encoding='utf-8'))
        hint += ' ' + str(config.get('model_type', ''))
        hint += ' ' + str(config.get('thinker_config', {}).get('model_type', ''))
    except (OSError, ValueError, AttributeError):
        pass
    if 'forcedaligner' in hint or 'forced_aligner' in hint:
        raise ValueError('时间对齐模型不能用于语音识别，请选择 Qwen3-ASR 模型。')


def validate_mlx_model(path):
    """Reject incompatible weights before starting a GPU worker."""
    reject_alignment_model(path)
    try:
        config = json.loads((Path(path) / 'config.json').read_text(encoding='utf-8'))
        quant = config.get('quantization', config.get('quantization_config', {}))
        valid = config.get('model_type') == 'qwen3_asr' and quant.get('bits') in (4, 8)
    except (OSError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError('Apple GPU 识别需要 Qwen3-ASR 的 MLX 4-bit 或 8-bit 权重；请选择对应模型。')


def resolve_translation(model, report, *, allow_download=False):
    from huggingface_hub import HfApi, snapshot_download

    if Path(model).is_dir():
        if translation_complete(model):
            return model
        raise ValueError('翻译模型目录不完整，请重新下载 / 检查模型。')
    # Reuse the optional project-local HY package installed by the CLI as well
    # as Hub caches. Selecting the built-in model must not download it twice.
    from .translation_models import HY_MODEL, is_hy_model
    bundled = model_directory('Hy-MT2-1.8B')
    if (model == HY_MODEL and has_weights(bundled) and is_hy_model(str(bundled))
            and all((bundled / name).is_file() for name in
                    ('tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja'))):
        report('翻译模型：使用已下载的 HY-MT2 权重')
        return str(bundled)
    try:
        cached = snapshot_download(model, local_files_only=True)
        if translation_complete(cached, hy=is_hy_model(model)):
            report("翻译模型：使用已下载缓存，不下载第二份权重")
            return cached
    except (OSError, ValueError):
        pass
    if not allow_download:
        raise ValueError('翻译模型未下载完整，请到设置 → 翻译模型下载 / 检查；开始聆听不会下载模型。')
    files = HfApi().list_repo_files(model)
    safe = any(f.endswith(".safetensors") for f in files)
    patterns = ["*.json", "*.model", "*.txt", "*.jinja", "*.safetensors" if safe else "*.bin"]
    report("正在下载翻译模型（单份权重）；完成后开始聆听时才加载")
    from .download_progress import hub_progress
    with hub_progress() as bar:
        path = snapshot_download(model, allow_patterns=patterns, max_workers=1, tqdm_class=bar)
    if not translation_complete(path, hy=is_hy_model(model)):
        raise ValueError('翻译模型下载不完整，请重新检查；已有文件保留供继续下载。')
    return path


def translation_complete(path, *, hy=False):
    path = Path(path)
    return (has_weights(path) and all((path / name).is_file() for name in
                                    ('config.json', 'tokenizer_config.json'))
            and (not hy or (path / 'chat_template.jinja').is_file()))
