"""Shared, transactional environment preparation; legacy scripts delegate here."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import zipfile
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .hardware import CUDA_WHEEL, TORCH_VERSION, check_installation
from .process_platform import spawn_options, stop_tree
from .runtime_paths import (
    cache_root,
    environment_python,
    installation_command,
    knowledge_python,
    python_environment,
    resource_root,
    runtime_root,
)


def run_command(command, *, env=None, cwd=None, timeout=1800):
    """Bounded command with descendant ownership, including CLI interruption."""
    supervisor = installation_command('linguaflow.managed_process', *command)
    with subprocess.Popen(supervisor, stdin=subprocess.PIPE, env=env or python_environment(),
                          cwd=cwd or resource_root(), **spawn_options()) as process:
        try:
            code = process.wait(timeout=timeout)
            if code:
                raise subprocess.CalledProcessError(code, command)
        finally:
            process.stdin.close()
            if process.poll() is None:
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    stop_tree(process, force=True)
                    process.wait(timeout=5)


def prepare_sources(requirements, directory):
    """Keep only upstream build inputs, excluding long-path experiment outputs.

    Both pinned projects declare static versions and explicit package roots.
    Repacking these files avoids needing Git or Windows registry changes; no
    upstream source is edited. The full original archive stays in the cache.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for line in requirements.read_text(encoding='utf-8').splitlines():
        name, separator, url = line.partition(' @ ')
        package = {'whisperlivekit': 'whisperlivekit', 'qwen3-asr-causal[streaming]': 'src'}.get(name)
        if not separator or package is None:
            lines.append(line)
            continue
        parsed = urlsplit(url)
        revision = parsed.path.rsplit('/', 1)[-1].removesuffix('.zip')
        expected = parse_qs(parsed.fragment).get('sha256', [''])[0]
        if (len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision)
                or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
            raise ValueError('固定源码依赖缺少提交或 SHA256 校验值。')
        def digest(path):
            with path.open('rb') as handle:
                return hashlib.file_digest(handle, 'sha256').hexdigest()
        archive = directory / (revision + '.zip')
        if not archive.is_file() or digest(archive) != expected:
            temporary = archive.with_suffix('.download')
            try:
                with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as output:
                    total = 0
                    for block in iter(lambda: response.read(1024**2), b''):
                        total += len(block)
                        if total > 64 * 1024**2:
                            raise ValueError('固定源码归档超过 64 MiB，未准备运行环境。')
                        output.write(block)
                if digest(temporary) != expected:
                    raise ValueError('上游依赖 SHA256 校验失败，未安装；请检查下载来源。')
                temporary.replace(archive)
            finally:
                temporary.unlink(missing_ok=True)
        prepared = directory / (name.split('[')[0] + '-' + revision + '.zip')
        temporary = prepared.with_suffix('.tmp')
        try:
            with zipfile.ZipFile(archive) as source, zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
                included = set()
                for entry in source.infolist():
                    parts = entry.filename.split('/')
                    if (len(parts) < 2 or '..' in parts or entry.is_dir()
                            or parts[1] not in (package, 'pyproject.toml', 'README.md', 'LICENSE')):
                        continue
                    if entry.file_size > 32 * 1024**2:
                        raise ValueError('上游依赖文件异常，未准备运行环境。')
                    target.writestr(entry, source.read(entry))
                    included.add(parts[1])
                if not {package, 'pyproject.toml', 'README.md', 'LICENSE'} <= included:
                    raise ValueError('固定源码依赖缺少构建文件或许可证，未安装。')
            temporary.replace(prepared)
        finally:
            temporary.unlink(missing_ok=True)
        lines.append(name + ' @ ' + prepared.resolve().as_uri() + '#sha256=' + digest(prepared))
    local = directory / 'requirements.txt'
    local.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return local


@contextmanager
def preparation_lock(directory):
    """OS releases the lock even if a cancelled preparation is forcibly killed."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'prepare.lock').open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('已有准备任务正在运行，请等待完成或取消后重试。') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def publish(pointer, value):
    """Only a successfully verified environment becomes visible to sessions."""
    temporary = pointer.with_name(pointer.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(pointer)
    finally:
        temporary.unlink(missing_ok=True)


def verify(kind):
    """Check dependency imports and a real GPU kernel, without loading weights."""
    run_command([sys.executable, '-m', 'linguaflow.runtime_check', kind], timeout=180)


def install(kind):
    target = check_installation()
    if kind == 'mlx' and target != 'macos-arm64':
        raise ValueError('MLX 仅支持原生 Apple Silicon Mac。')
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        raise ValueError('运行环境准备需要 Python 3.11–3.13。')
    root = resource_root()
    requirements = root / ('requirements-runtime.txt' if kind == 'wlk' else 'requirements-mlx.txt')
    if not requirements.is_file():
        raise ValueError('安装内容缺少固定版本依赖清单，请重新安装完整版本。')
    base = runtime_root() / 'python' / kind
    with preparation_lock(base):
        slot = uuid4().hex
        destination = base / slot
        python = environment_python(destination)
        environment = python_environment()
        temporary = cache_root() / 'pip-tmp'
        temporary.mkdir(parents=True, exist_ok=True)
        temp_path = str(temporary.resolve())
        environment.update(TMP=temp_path, TEMP=temp_path)

        def run(command):
            run_command(command, env=environment, cwd=root)

        print('准备新环境；失败或取消不会替换现有环境。', flush=True)
        run([str(knowledge_python()), '-m', 'venv', str(destination)])
        if kind == 'wlk':
            suffix = '+' + CUDA_WHEEL if target == 'windows-x64' else ''
            command = [str(python), '-m', 'pip', 'install', f'torch=={TORCH_VERSION}{suffix}',
                       f'torchaudio=={TORCH_VERSION}{suffix}']
            if target == 'windows-x64':
                command += ['--index-url', 'https://download.pytorch.org/whl/' + CUDA_WHEEL]
            run(command)
        dependency_file = prepare_sources(requirements, cache_root() / 'runtime-sources') if kind == 'wlk' else requirements
        run([str(python), '-m', 'pip', 'install', '-r', str(dependency_file)])
        run([str(python), '-m', 'pip', 'check'])
        run([str(python), '-m', 'linguaflow.runtime_install', kind, '--verify'])
        if not python.is_file():
            raise RuntimeError('新环境缺少 Python 解释器，未切换现有环境。')
        pointer = base / 'active.json'
        previous = None
        if pointer.exists():
            try:
                previous = json.loads(pointer.read_text(encoding='utf-8')).get('slot')
            except (OSError, ValueError, AttributeError):
                pass  # Repair also works when the old pointer is damaged.
        publish(pointer, {'slot': slot, 'previous': previous, 'platform': target,
                          'torch_version': TORCH_VERSION if kind == 'wlk' else None,
                          'requirements': requirements.read_text(encoding='utf-8')})
    print('运行环境已就绪：' + str(python) + '\n请先下载 / 检查模型，再开始聆听。', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('wlk', 'mlx'))
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        verify(args.kind)
    else:
        install(args.kind)


if __name__ == '__main__':
    main()
