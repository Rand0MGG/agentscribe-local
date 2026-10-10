"""Prepare pinned local llama.cpp binaries and optional HY weights; no inference."""
import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from uuid import uuid4

from .download_progress import copy_download, hub_progress
from .hardware import check_installation
from .installation import preparation_lock, publish, run_command
from .runtime_paths import cache_root, llama_server, runtime_root


def unpack(archive, destination):
    if archive.name.endswith('.zip'):
        with zipfile.ZipFile(archive) as source:
            for name in source.namelist():
                if not (destination/name).resolve().is_relative_to(destination.resolve()):
                    raise ValueError('运行组件包含无效路径')
            source.extractall(destination)
    else:
        with tarfile.open(archive) as source:
            source.extractall(destination, filter='data')
    entries = list(destination.iterdir())
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else destination


def ensure_runtime(device):
    """Check the selected binary/DLLs off the UI thread, repairing without weights."""
    try:
        binary = llama_server(device)
        if not binary.is_file():
            raise RuntimeError('缺少翻译运行组件')
        run_command([str(binary), '--version'], timeout=30)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        install(device, None)


def install(device, model):
    from linguaflow.llama_assets import (
        HY_GGUF,
        RELEASE_URL,
        digest,
        runtime_archives,
        validate_weights,
    )

    target = check_installation()
    archives = runtime_archives(device)
    if model is not None and model != HY_GGUF and not model.startswith('hf://'):
        validate_weights(model)
    name = 'llama-b11254-' + (target + '-' + device if target == 'windows-x64' else target)
    base = runtime_root() / 'components' / name
    with preparation_lock(base), tempfile.TemporaryDirectory(prefix='llama-install-', dir=base) as work:
        slot = uuid4().hex
        destination = base / slot
        work = Path(work)
        for index, (name, expected) in enumerate(archives):
            archive = cache_root() / name
            if not archive.is_file():
                archive = work/name
                print('正在下载 llama.cpp 运行组件：'+name, flush=True)
                with urllib.request.urlopen(RELEASE_URL+name, timeout=60) as response, archive.open('wb') as output:
                    copy_download(response, output, 'llama.cpp 运行组件')
            if digest(archive) != expected:
                raise ValueError('运行组件校验失败：'+name)
            folder = unpack(archive, work/str(index))
            # Every repair gets a new directory; running sessions retain theirs.
            for source in folder.rglob('*'):
                if not source.is_file():
                    continue
                target = destination/source.relative_to(folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        binary = destination / ('llama-server.exe' if sys.platform == 'win32' else 'llama-server')
        if not binary.is_file():
            raise ValueError('运行组件缺少 llama-server，请检查官方发行包。')
        run_command([str(binary), '--version'], timeout=30)
        publish(base / 'active.json', {'slot': slot})
    if model is not None:
        prepare_weights(model)
    print('llama.cpp 文件已就绪；开始聆听时验证模型架构和所选设备。', flush=True)


def prepare_weights(model):
    from .llama_assets import (
        HY_GGUF,
        MODEL_FILE,
        MODEL_SHA256,
        REVISION,
        digest,
        hub_gguf,
        model_path,
        validate_weights,
        weights_path,
    )
    if model == HY_GGUF:
        weights = model_path()
        if not weights.is_file() or digest(weights) != MODEL_SHA256:
            from huggingface_hub import hf_hub_download
            print('正在下载 HY-MT2 1.8B Q4_K_M 权重…', flush=True)
            with hub_progress():
                cached = Path(hf_hub_download(HY_GGUF, MODEL_FILE, revision=REVISION))
            if digest(cached) != MODEL_SHA256:
                # Only confirmed corruption justifies replacing the cached file.
                with hub_progress():
                    cached = Path(hf_hub_download(HY_GGUF, MODEL_FILE, revision=REVISION, force_download=True))
            if digest(cached) != MODEL_SHA256:
                raise ValueError('HY 权重校验失败，请重新准备。')
            weights.parent.mkdir(parents=True, exist_ok=True)
            for name in ('LICENSE.txt', 'README.md'):
                document = hf_hub_download(HY_GGUF, name, revision=REVISION)
                shutil.copy2(document, weights.parent / name)
            staged = weights.with_name(weights.name + '.' + uuid4().hex + '.tmp')
            try:
                shutil.copy2(cached, staged)
                staged.replace(weights)
            finally:
                staged.unlink(missing_ok=True)
    elif model.startswith('hf://'):
        repo, filename = hub_gguf(model)
        weights = weights_path(model)
        try:
            validate_weights(model)
            ready = True
        except (ValueError, OSError):
            ready = False
        if not ready:
            from huggingface_hub import hf_hub_download
            print('正在下载 GGUF 权重：' + filename, flush=True)
            with hub_progress():
                cached = Path(hf_hub_download(repo, filename))
            try:
                validate_weights(str(cached))
            except ValueError:
                # A confirmed invalid cached header can be replaced once, without unbounded retries.
                with hub_progress():
                    cached = Path(hf_hub_download(repo, filename, force_download=True))
                validate_weights(str(cached))
            weights.parent.mkdir(parents=True, exist_ok=True)
            staged = weights.with_name(weights.name + '.' + uuid4().hex + '.tmp')
            try:
                shutil.copy2(cached, staged)
                staged.replace(weights)
            finally:
                staged.unlink(missing_ok=True)
    validate_weights(model)


def main():
    from .llama_assets import HY_GGUF
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='metal' if sys.platform == 'darwin' else 'cpu')
    parser.add_argument('--model', default=HY_GGUF, help='Built-in HY preset or an existing GGUF file')
    args = parser.parse_args()
    install(args.device, args.model)


if __name__ == '__main__':
    main()
