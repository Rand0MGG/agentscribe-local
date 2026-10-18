"""Prepare pinned local llama.cpp binaries and optional HY weights; no inference."""
import argparse
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from uuid import uuid4

from .download_progress import copy_download, hub_progress, report
from .hardware import check_installation
from .installation import preparation_lock, publish, run_command
from .runtime_cleanup import clean_component, previous_component, seal_slot
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
    report('检查 llama.cpp 运行组件（已有文件不会重新下载）', unit='stage')
    try:
        binary = llama_server(device)
        if not binary.is_file():
            raise RuntimeError('缺少翻译运行组件')
        run_command([str(binary), '--version'], timeout=30)
        report('llama.cpp 运行组件已就绪，复用现有文件', unit='stage')
    except (RuntimeError, OSError, subprocess.SubprocessError):
        install(device, None)


def cached_archive(name, expected):
    """Retain verified archives and resume interrupted bytes under one cache lock."""
    from .llama_assets import RELEASE_URL, digest
    cache = cache_root()
    with preparation_lock(cache / 'llama-download'):
        archive = cache / name
        if archive.is_file() and digest(archive) == expected:
            report('复用已校验组件：' + name, unit='stage')
            return archive
        partial = archive.with_suffix(archive.suffix + '.part')
        if partial.is_file() and digest(partial) == expected:
            partial.replace(archive)
            return archive
        offset = partial.stat().st_size if partial.is_file() else 0
        request = urllib.request.Request(RELEASE_URL + name,
                                         headers={'Range': f'bytes={offset}-'} if offset else {})
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as exc:
            # A complete but corrupt partial cannot be resumed. Keep an actionable
            # failure for this attempt; the next explicit retry starts cleanly.
            if exc.code == 416:
                partial.unlink(missing_ok=True)
                raise ValueError('组件缓存未通过校验，已清除损坏片段，请重试：' + name) from exc
            raise
        with response:
            status = getattr(response, 'status', 200)
            if status == 206:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                if not match or int(match[1]) != offset:
                    raise ValueError('下载服务器返回了不匹配的续传范围，请重试：' + name)
            elif status == 200:
                offset = 0  # Server ignored Range: replace, never append a full archive.
            else:
                raise ValueError(f'组件下载返回 HTTP {status}：{name}')
            with partial.open('ab' if offset else 'wb') as output:
                copy_download(response, output, name, initial=offset)
        if digest(partial) != expected:
            partial.unlink(missing_ok=True)
            raise ValueError('运行组件校验失败，请重试：' + name)
        partial.replace(archive)
        return archive


def install(device, model):
    from linguaflow.llama_assets import (
        HY_GGUF,
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
        previous = previous_component(base / 'active.json')
        slot = uuid4().hex
        destination = base / slot
        destination.mkdir(parents=True, exist_ok=False)
        work = Path(work)
        for index, (name, expected) in enumerate(archives):
            archive = cached_archive(name, expected)
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
        seal_slot(destination, 'llama')
        publish(base / 'active.json', {'slot': slot, 'previous': previous})
        clean_component(base, 'llama')
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
