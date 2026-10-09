"""Retain a portable base Python outside replaceable application resources."""
import hashlib
import json
import os
import shutil
import sys
import sysconfig
from pathlib import Path
from uuid import uuid4


def python_abi():
    """ABI identity, independent of application versions and Python patch releases."""
    return {'implementation': sys.implementation.name, 'version': list(sys.version_info[:2]),
            'soabi': sysconfig.get_config_var('SOABI')}


def python_files(root):
    """Exclude desktop packages; venv bootstraps pip from stdlib ensurepip wheels."""
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part in {'site-packages', '__pycache__'} for part in relative.parts) or path.suffix == '.pyc':
            continue
        if relative.parts[0] == 'Scripts' or (relative.parts[0] == 'bin'
                                               and path.name not in {'python', 'python3', 'python3.12'}):
            continue  # Desktop pip wrappers may retain the replaceable construction path.
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('便携 Python 包含指向程序外部的链接，请重新安装完整版本。')
            if path.is_file():
                yield relative, {'link': os.readlink(path)}
        elif path.is_file():
            with path.open('rb') as handle:
                yield relative, {'sha256': hashlib.file_digest(handle, 'sha256').hexdigest()}


def prepare_base(source, directory, executable, *, preferred_slot=None):
    """Copy and validate once in its final slot. Caller holds the preparation lock.

    No environment or existing base is relocated/deleted/overwritten. Interrupted
    or corrupted slots are retained and a fresh slot is prepared instead.
    """
    source, directory = Path(source).resolve(), Path(directory).resolve()
    relative_python = Path(executable).resolve().relative_to(source)
    files = {str(path).replace('\\', '/'): value for path, value in python_files(source)}
    if not files or str(relative_python).replace('\\', '/') not in files:
        raise ValueError('安装内容缺少完整便携 Python，未修改推理环境。')
    identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    candidates = [identity]
    if (isinstance(preferred_slot, str) and len(preferred_slot) == 64
            and all(c in '0123456789abcdef' for c in preferred_slot)):
        candidates.insert(0, preferred_slot)
    for slot in candidates:
        candidate = directory / slot
        try:
            if candidate.is_symlink():
                continue
            metadata = json.loads((candidate / 'base.json').read_text(encoding='utf-8'))
            if not isinstance(metadata, dict) or metadata.get('files') != files or metadata.get('abi') != python_abi():
                continue
            validate_files(candidate, files)
            return candidate / relative_python, slot
        except (OSError, ValueError, RuntimeError):
            continue  # Retain corrupt/unfinished bases; never repair an in-use interpreter in place.
    destination = directory / identity
    if destination.exists() or destination.is_symlink():
        identity = hashlib.sha256((identity + uuid4().hex).encode()).hexdigest()
        destination = directory / identity
    destination.mkdir(parents=True, exist_ok=False)
    for name, value in files.items():
        target = destination / name
        if not target.resolve().is_relative_to(destination):
            raise ValueError('独立 Python 缓存路径异常，未准备环境。')
        target.parent.mkdir(parents=True, exist_ok=True)
        if 'link' in value:
            target.symlink_to(value['link'])
        else:
            shutil.copy2(source / name, target)
    validate_files(destination, files)
    temporary = destination / 'base.json.tmp'
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump({'files': files, 'abi': python_abi()}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination / 'base.json')
    return destination / relative_python, identity


def validate_files(directory, files):
    """Verify both content and link containment before reusing a base."""
    for name, value in files.items():
        target = directory / name
        if not target.resolve().is_relative_to(directory):
            raise ValueError('独立 Python 文件不能指向运行目录之外。')
        if 'link' in value:
            if not target.is_symlink() or os.readlink(target) != value['link']:
                raise RuntimeError('独立 Python 链接损坏，旧环境保留。')
        else:
            if target.is_symlink():
                raise ValueError('独立 Python 文件不能替换为链接。')
            with target.open('rb') as handle:
                if hashlib.file_digest(handle, 'sha256').hexdigest() != value['sha256']:
                    raise RuntimeError('独立 Python 文件校验失败，旧环境保留。')
