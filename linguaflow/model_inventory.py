"""Inspect/delete model files in an isolated process, without loading model libraries."""
import argparse
import json
import os
import shutil
from pathlib import Path

from .model_cache import has_weights
from .runtime_paths import model_directory, whisper_cache_root


def hub_root():
    home = Path(os.environ.get('HF_HOME') or Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'huggingface')
    return Path(os.environ.get('HF_HUB_CACHE') or os.environ.get('HUGGINGFACE_HUB_CACHE') or home / 'hub')


def model_kind(path, name):
    try:
        config = json.loads((path / 'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    hint = (name + ' ' + str(config.get('model_type', ''))).casefold()
    quant = config.get('quantization', config.get('quantization_config', {}))
    quant = quant if isinstance(quant, dict) else {}
    if 'forcedaligner' in hint or 'forced_aligner' in hint:
        return 'alignment', None
    if 'whisper' in hint:
        return 'asr', 'wlk-whisper'
    if any(word in hint for word in ('qwen3-asr', 'qwen3_asr', 'whisper')):
        return 'asr', 'qwen3-mlx' if quant.get('bits') == 4 else 'qwen3-streaming'
    if any(word in hint for word in ('hy-mt', 'nllb', 'm2m_100')) or path.suffix.casefold() == '.gguf':
        return 'translation', 'llama' if path.suffix.casefold() == '.gguf' else 'pytorch'
    return None, None


def file_size(path):
    if path.is_file():
        return path.stat().st_size
    # Count physical cache blobs once, not snapshot links to the same weights.
    return sum(file.stat().st_size for file in path.rglob('*') if file.is_file() and not file.is_symlink())


def inventory(selected=()):
    entries, seen = [], set()
    def add(path, owned, name=None, delete_path=None, kind=None, engine=None):
        if not path.exists() or str(path.resolve()) in seen:
            return
        name = name or path.name
        detected_kind, detected_engine = model_kind(path, name)
        # A saved UI selection is only a fallback for unknown formats.
        kind, engine = detected_kind or kind, detected_engine or engine
        if detected_kind == "alignment":
            kind, engine = detected_kind, None
        if not kind:
            return
        if path.is_dir() and not has_weights(path):
            return
        if path.is_file() and (path.suffix.lower() not in ('.gguf', '.pt', '.bin', '.safetensors') or not path.stat().st_size):
            return
        target = delete_path or path
        seen.add(str(path.resolve()))
        entries.append(dict(id=str(target), path=str(path), name=name, kind=kind, engine=engine,
                            size=file_size(target), deletable=owned and not target.is_symlink()
                            and not any(parent.is_symlink() for parent in target.parents)))
    for name in ('Qwen3-ASR-1.7B-4bit', 'Hy-MT2-1.8B', 'Hy-MT2-1.8B-GGUF'):
        root = model_directory(name)
        if root.name.endswith('GGUF'):
            for file in root.glob('*.gguf'):
                add(file, True)
        else:
            add(root, True)
    for repo in hub_root().glob('models--*'):
        name = repo.name.removeprefix('models--').replace('--', '/')
        snapshots = sorted((repo / 'snapshots').glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)
        for snapshot in snapshots:
            if has_weights(snapshot):
                add(snapshot, True, name, repo)
                break
    for file in whisper_cache_root().glob('*.pt'):
        add(file, True, 'Whisper · ' + file.stem, kind='asr', engine='wlk-whisper')
    for value in selected:
        if not isinstance(value, dict):
            continue
        path = Path(value.get('path', '')).expanduser()
        if path.is_absolute():
            # Explicit custom locations remain selectable but are not owned caches.
            add(path, False, kind=value.get('kind'), engine=value.get('engine'))
    return entries


def delete_model(identifier, selected=()):
    entry = next((item for item in inventory(selected) if item['id'] == identifier and item['deletable']), None)
    if entry is None:
        raise ValueError('模型已变化或不是应用管理的缓存，请刷新列表。')
    path = Path(entry['id'])
    if path.is_symlink():
        raise ValueError('不能删除指向其他目录的模型链接。')
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selected', default='[]')
    parser.add_argument('--delete')
    args = parser.parse_args()
    try:
        selected = json.loads(args.selected)
        if not isinstance(selected, list):
            raise ValueError('模型参数无效。')
        if args.delete:
            delete_model(args.delete, selected)
        result = dict(models=inventory(selected))
    except (OSError, ValueError, TypeError) as exc:
        result = dict(error=str(exc))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
