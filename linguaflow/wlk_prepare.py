"""Prepare Whisper with bounded memory and publish only a verified checkpoint."""
import argparse
import hashlib
import urllib.request
from pathlib import Path

from .download_progress import copy_download
from .installation import preparation_lock
from .model_cache import resolve_whisper_cached
from .runtime_paths import whisper_cache_root


def prepare(model):
    if Path(model).exists():
        return resolve_whisper_cached(model)
    from whisperlivekit.whisper import _MODELS
    if model not in _MODELS:
        raise ValueError('请选择内置 Whisper 模型名称或已有的 PyTorch 模型文件 / 目录。')
    url = _MODELS[model]
    expected, filename = url.rsplit('/', 2)[-2:]
    root = whisper_cache_root()
    target = root / filename
    def digest(path):
        with path.open('rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest()
    with preparation_lock(root):
        if target.is_file() and digest(target) == expected:
            return str(target.resolve())
        # Cancellation/failure preserves both the old target and partial file.
        # Stream the checksum rather than reading several GB into CPU memory.
        partial = target.with_suffix('.pt.download')
        print('正在下载 Whisper：' + model, flush=True)
        checksum = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as output:
            copy_download(response, output, 'Whisper：' + model, checksum=checksum)
        if checksum.hexdigest() != expected:
            raise ValueError('Whisper 权重校验失败，已有模型保留，请重新下载 / 检查。')
        partial.replace(target)
    return str(target.resolve())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('whisper',))
    parser.add_argument('model')
    args = parser.parse_args()
    print('Whisper 文件已就绪：' + prepare(args.model), flush=True)


if __name__ == "__main__":
    main()
