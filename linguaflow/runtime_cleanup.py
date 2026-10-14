"""Bounded retention of verified app-owned runtime slots; never scan user data."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from .installation import publish

MARKER = '.agentscribe-slot.json'


def process_commands():
    """Unavailable process inventory forbids removal on either platform."""
    command = (['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                "$ErrorActionPreference='Stop'; [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                "Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine"]
               if sys.platform == 'win32' else ['ps', '-axo', 'command='])
    return subprocess.check_output(command, text=True, encoding='utf-8', timeout=15).casefold()


def slot_name(value):
    return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)


def mapped(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            return True
        try:
            # Python 3.11 lacks Path.is_junction(); reject all Windows reparse
            # ancestors, including junctions and unknown directory mappings.
            if getattr(part.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return True
        except FileNotFoundError:
            continue
        except OSError:
            return True
    return False


def tree_digest(directory):
    """Hash files/empty directories without following mappings or Python caches.

    Only our two metadata files and generated __pycache__ bytecode are mutable.
    Extra files, modified dependencies and external directory mappings forbid
    deletion. File symlinks are hashed as links, never read through their target.
    """
    result = hashlib.sha256()
    if mapped(directory) or not directory.is_dir():
        raise ValueError('运行目录包含映射或不存在。')
    def failed(error):
        raise error
    for root, dirs, files in os.walk(directory, followlinks=False, onerror=failed):
        root = Path(root)
        for name in sorted(dirs + files):
            path = root / name
            relative = path.relative_to(directory)
            if relative.as_posix() in {MARKER, 'environment.json'}:
                if path.is_symlink() or not path.is_file():
                    raise ValueError('运行目录元数据包含映射。')
                continue
            if hasattr(path, 'is_junction') and path.is_junction():
                raise ValueError('运行目录包含目录映射。')
            if path.is_symlink():
                if name in dirs and not path.resolve().is_relative_to(directory.resolve()):
                    raise ValueError('运行目录包含外部目录链接。')
                value = ['link', os.readlink(path)]
            elif name in dirs:
                if getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError('运行目录包含目录映射。')
                if name == '__pycache__':
                    continue
                value = ['directory']
            elif path.is_file():
                if path.suffix == '.pyc' and '__pycache__' in relative.parts:
                    continue
                with path.open('rb') as handle:
                    value = ['file', hashlib.file_digest(handle, 'sha256').hexdigest()]
            else:
                raise ValueError('运行目录包含特殊文件。')
            result.update(json.dumps([relative.as_posix(), value], ensure_ascii=True).encode())
        dirs.sort()
    return result.hexdigest()


def seal_slot(directory, kind):
    """Record ownership only for a freshly installed and verified unique slot."""
    publish(directory / MARKER, {'schema': 1, 'slot': directory.name, 'kind': kind,
                                'tree_sha256': tree_digest(directory)})


def removable(directory, kind, commands):
    """Legacy, changed, custom, mapped or live directories are always retained."""
    commands = commands.casefold()
    if (not commands.strip() or not slot_name(directory.name) or mapped(directory)
            or str(directory).casefold() in commands):
        return False
    try:
        if kind.startswith('python-'):
            environment = json.loads((directory / 'environment.json').read_text(encoding='utf-8'))
            if not isinstance(environment, dict) or environment.get('slot') != directory.name:
                return False
        record = json.loads((directory / MARKER).read_text(encoding='utf-8'))
        return (record.get('schema') == 1 and record.get('slot') == directory.name
                and record.get('kind') == kind and record.get('tree_sha256') == tree_digest(directory))
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        return False


def clean_component(base, kind):
    """Caller holds preparation lock; keep active and the most recent rollback."""
    if mapped(base):
        return 0
    try:
        pointer = base / 'active.json'
        if mapped(pointer):
            return 0
        value = json.loads(pointer.read_text(encoding='utf-8'))
        active, previous = value['slot'], value.get('previous')
        if not slot_name(active) or (previous is not None and not slot_name(previous)):
            return 0
        if not (base / active).is_dir() or mapped(base / active):
            return 0
        if previous is not None and (not (base / previous).is_dir() or mapped(base / previous)):
            return 0
        commands = process_commands()
        if not commands.strip():
            return 0
        removed = 0
        for directory in base.iterdir():
            if directory.name not in {active, previous} and removable(directory, kind, commands):
                # Recheck immediately before deleting; failure never rolls back the active pointer.
                if removable(directory, kind, process_commands()):
                    shutil.rmtree(directory)
                    removed += 1
        return removed
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return 0


def previous_component(pointer):
    try:
        slot = json.loads(pointer.read_text(encoding='utf-8'))['slot']
        return slot if slot_name(slot) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def retained_requirements(kind):
    """Protect environments for every retained previous/failed installation.

    These app-owned sibling names are produced by UpdateRecovery. Missing or
    mapped backup resources disable history pruning rather than guessing.
    """
    from .runtime_paths import packaged, resource_root
    resources = resource_root()
    mac = resources.parent.name == 'Contents'
    installed = resources.parent.parent if mac else resources
    requirements = 'requirements-runtime.txt' if kind == 'wlk' else 'requirements-mlx.txt'
    result = set()
    try:
        current = resources / requirements
        if mapped(current):
            return None
        result.add(current.read_text(encoding='utf-8'))
        if not packaged():
            return result
        if mapped(installed):
            return None
        for pattern in ('.AgentScribe-previous-*', '.AgentScribe-failed-*'):
            for backup in installed.parent.glob(pattern):
                if not slot_name(backup.name.rsplit('-', 1)[-1]) or mapped(backup):
                    return None
                root = backup / 'Contents/Resources' if mac else backup
                file = root / requirements
                if mapped(file):
                    return None
                result.add(file.read_text(encoding='utf-8'))
        return result
    except (OSError, ValueError):
        return None
