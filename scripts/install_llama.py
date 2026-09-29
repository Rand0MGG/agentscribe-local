"""Prepare pinned local llama.cpp binaries and optional HY weights; no inference."""
import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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


def main():
    from linguaflow.llama_assets import (
        HY_GGUF,
        MODEL_FILE,
        MODEL_SHA256,
        RELEASE_URL,
        REVISION,
        digest,
        model_path,
        runtime_archives,
        validate_weights,
    )
    from linguaflow.runtime_paths import llama_server

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='metal' if sys.platform == 'darwin' else 'cpu')
    parser.add_argument('--model', default=HY_GGUF, help='Built-in HY preset or an existing GGUF file')
    args = parser.parse_args()
    archives = runtime_archives(args.device)
    if args.model != HY_GGUF:
        validate_weights(args.model)
    destination = llama_server(args.device).parent
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='llama-install-', dir=destination.parent) as work:
        work = Path(work)
        for index, (name, expected) in enumerate(archives):
            archive = ROOT/'.work/cache'/name
            if not archive.is_file():
                archive = work/name
                print('正在下载 llama.cpp 运行组件：'+name, flush=True)
                with urllib.request.urlopen(RELEASE_URL+name, timeout=60) as response, archive.open('wb') as output:
                    shutil.copyfileobj(response, output)
            if digest(archive) != expected:
                raise ValueError('运行组件校验失败：'+name)
            folder = unpack(archive, work/str(index))
            # Do not rewrite identical binaries that another local session may use.
            for source in folder.rglob('*'):
                if not source.is_file():
                    continue
                target = destination/source.relative_to(folder)
                if target.is_file() and digest(target) == digest(source):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                staged = target.with_name(target.name+'.new')
                shutil.copy2(source, staged)
                staged.replace(target)
    if not llama_server(args.device).is_file():
        raise ValueError('运行组件缺少 llama-server，请检查官方发行包。')
    if args.model == HY_GGUF:
        weights = model_path()
        if not weights.is_file() or digest(weights) != MODEL_SHA256:
            from huggingface_hub import snapshot_download
            print('正在下载 HY-MT2 1.8B Q4_K_M 权重…', flush=True)
            snapshot_download(HY_GGUF, revision=REVISION, local_dir=str(weights.parent),
                              allow_patterns=[MODEL_FILE, 'LICENSE.txt', 'README.md'], max_workers=1,
                              force_download=weights.exists())
            if digest(weights) != MODEL_SHA256:
                raise ValueError('HY 权重校验失败，请重新准备。')
    validate_weights(args.model)
    print('llama.cpp 文件已就绪；开始聆听时验证模型架构和所选设备。', flush=True)


if __name__ == '__main__':
    main()
