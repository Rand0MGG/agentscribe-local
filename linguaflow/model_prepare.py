"""Download/check models in an owned, cancellable process, outside listening."""
import argparse
from pathlib import Path

from .model_cache import resolve_qwen_cached, resolve_translation, validate_mlx_model
from .runtime_paths import model_directory


def prepare(kind, model):
    if kind == 'translation':
        path = resolve_translation(model, print, allow_download=True)
    else:
        if Path(model).is_dir():
            path = resolve_qwen_cached(model)
        else:
            from huggingface_hub import snapshot_download
            options = {}
            if model == 'mlx-community/Qwen3-ASR-1.7B-4bit':
                from .mlx_asr import MLX_REVISION
                options = {'revision': MLX_REVISION, 'local_dir': str(model_directory('Qwen3-ASR-1.7B-4bit'))}
            path = snapshot_download(model, allow_patterns=['*.json', '*.safetensors', '*.txt', '*.model', '*.jinja'],
                                     max_workers=1, **options)
            path = resolve_qwen_cached(path)
        if model == 'mlx-community/Qwen3-ASR-1.7B-4bit':
            validate_mlx_model(path)
    print('模型文件已检查完整：' + str(path), flush=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('qwen', 'translation'))
    parser.add_argument('model')
    args = parser.parse_args()
    prepare(args.kind, args.model)


if __name__ == '__main__':
    main()
