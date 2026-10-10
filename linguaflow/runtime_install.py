"""Shared, transactional environment preparation; legacy scripts delegate here."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .hardware import CUDA_WHEEL, TORCH_VERSION, check_installation
from .installation import preparation_lock, publish, run_command
from .runtime_base import prepare_base, python_abi
from .runtime_paths import (
    cache_root,
    environment_python,
    knowledge_python,
    packaged,
    python_environment,
    resource_root,
    runtime_environment,
    runtime_root,
)


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
        pointer = base / 'active.json'
        previous_metadata = None
        if pointer.exists():
            try:
                previous_metadata = json.loads(pointer.read_text(encoding='utf-8'))
                if not isinstance(previous_metadata, dict):
                    previous_metadata = None
            except (OSError, ValueError):
                pass  # Damaged pointers can be repaired without deleting old slots.
        previous = (previous_metadata or {}).get('slot')
        if (not isinstance(previous, str) or len(previous) != 32
                or any(c not in '0123456789abcdef' for c in previous)):
            previous = None
        base_python, base_slot = knowledge_python(), None
        if packaged():
            with preparation_lock(runtime_root() / 'base-python'):
                print('准备独立基础 Python；程序升级不会移除它。', flush=True)
                base_python, base_slot = prepare_base(root / 'python', runtime_root() / 'base-python', base_python,
                                                     preferred_slot=(previous_metadata or {}).get('base_slot'))
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
        run([str(base_python), '-m', 'venv', str(destination)])
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
        metadata = {'schema': 2, 'slot': slot, 'previous': previous, 'platform': target,
                    'torch_version': TORCH_VERSION if kind == 'wlk' else None,
                    'requirements': requirements.read_text(encoding='utf-8'),
                    'python_abi': python_abi(), 'base_slot': base_slot}
        publish(destination / 'environment.json', metadata)
        if (isinstance(previous, str) and len(previous) == 32
                and all(c in '0123456789abcdef' for c in previous)):
            old_record = base / previous / 'environment.json'
            if old_record.parent.is_dir() and not old_record.exists():
                publish(old_record, previous_metadata)
        publish(pointer, metadata)
    print('运行环境已就绪：' + str(python) + '\n请先下载 / 检查模型，再开始聆听。', flush=True)


def process_commands():
    """Read process ownership conservatively; unavailable inventory forbids cleanup."""
    if sys.platform == 'win32':
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                   'Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine']
    else:
        command = ['ps', '-axo', 'command=']
    return subprocess.check_output(command, text=True, timeout=15).casefold()


def clean_environments(kind):
    """Remove only unreferenced managed slots; preserve rollback chain and live processes.

    Unknown/corrupt pointer records and failed process inspection fail closed.
    Legacy venvs, models, recordings and shared base Python never enter this scan.
    The caller must hold the environment's preparation lock.
    """
    base = runtime_root() / 'python' / kind
    if any(path.is_symlink() for path in (base, *base.parents)):
        return 0
    def slot_name(value):
        return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)
    protected = set()
    try:
        pointer = base / 'active.json'
        if not pointer.is_file():
            return 0
        value = json.loads(pointer.read_text(encoding='utf-8'))
        while True:
            if not isinstance(value, dict) or len(protected) >= 256:
                return 0
            slot = value['slot']
            if not slot_name(slot) or slot in protected:
                return 0
            protected.add(slot)
            previous = value.get('previous')
            if previous is None:
                break
            if not slot_name(previous):
                return 0
            record = base / previous / 'environment.json'
            # An interrupted old publication may have no record; protect it anyway.
            if not record.is_file():
                protected.add(previous)
                break
            value = json.loads(record.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or value.get('slot') != previous:
                return 0
        commands = process_commands()
        if not commands.strip():
            return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('暂未清理旧环境：无法确认环境引用或进程状态。', flush=True)
        return 0
    removed = 0
    for directory in base.iterdir():
        if (not slot_name(directory.name) or directory.name in protected or directory.is_symlink()
                or not directory.is_dir() or str(directory).casefold() in commands):
            continue
        shutil.rmtree(directory)
        removed += 1
    return removed


def ensure_runtime(kind):
    """Reuse healthy environments; repairs publish only after their normal verification."""
    try:
        python = environment_python(runtime_environment(kind))
        if not python.is_file():
            raise RuntimeError('缺少解释器')
        run_command([str(python), '-m', 'linguaflow.runtime_check', kind], timeout=180)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        print('环境缺失或检查未通过，正在重新准备：' + kind, flush=True)
        install(kind)


def maintain(selection=None, *, only=None):
    """One background operation validates all required runtimes and repairs failures."""
    check_installation()
    from .model_options import recommended_selection, required_runtimes, translation_devices
    selection = recommended_selection() if selection is None else selection
    if only not in (None, 'asr', 'translation'):
        raise ValueError('未知模型准备范围。')
    kinds = (() if only == 'translation' else required_runtimes(selection['backend']))
    engine, device = selection['translation_engine'], selection['translation_device']
    if only != 'asr' and device not in translation_devices(engine):
        raise ValueError('翻译设备不适用于当前引擎和平台。')
    if only == 'translation' and engine != 'llama':
        kinds = ('wlk',)
    for kind in kinds:
        print('检查运行环境：' + kind, flush=True)
        ensure_runtime(kind)
        with preparation_lock(runtime_root() / 'python' / kind):
            removed = clean_environments(kind)
        print(f'{kind} 检查通过，清理 {removed} 个未使用的环境。', flush=True)
    if only != 'asr' and engine == 'llama':
        from .llama_install import ensure_runtime as ensure_llama
        ensure_llama(device)
    print('所需运行环境检查完成；模型与录音已保留。', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('wlk', 'mlx', 'all'))
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--maintain', action='store_true')
    parser.add_argument('--selection', type=json.loads)
    args = parser.parse_args()
    if args.kind == 'all':
        if not args.maintain or args.verify:
            parser.error('all requires --maintain')
        maintain(args.selection)
    elif args.maintain:
        parser.error('--maintain requires all')
    elif args.verify:
        verify(args.kind)
    else:
        install(args.kind)


if __name__ == '__main__':
    main()
