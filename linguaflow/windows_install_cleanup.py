"""Remove obsolete, unchanged Windows program files using existing build manifests.

Inno calls this after copying the complete new payload and before launching it.
There is no directory-wide deletion, user-data migration or macOS install hook.
"""
import argparse
import json
import sys
from pathlib import Path, PurePosixPath

from .update_recovery import checksum

PREVIOUS_MANIFEST = '.agentscribe-previous-build.json'


def manifest_files(path):
    """Return a case-insensitive, validated inventory or raise before any deletion."""
    manifest = json.loads(path.read_text(encoding='utf-8'))
    files = manifest.get('payload_files')
    if (manifest.get('target') != 'windows-x64' or manifest.get('source_modified') is not False
            or not isinstance(files, dict) or not {'AgentScribe.exe', 'python/python.exe'} <= files.keys()):
        raise ValueError('安装构建清单无效；未清理旧程序文件。')
    result = {}
    for name, digest in files.items():
        relative = PurePosixPath(name)
        if (relative.is_absolute() or relative.as_posix() != name
                or any(part in ('', '.', '..') or part.endswith((' ', '.'))
                       or any(char in part for char in '\\:*?"<>|\0') for part in relative.parts)
                or name.casefold() in result or not isinstance(digest, str)
                or len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest)):
            raise ValueError('安装构建清单包含无效路径或摘要；未清理旧程序文件。')
        result[name.casefold()] = (name, digest)
    return result


def checked_path(root, name):
    path = root / name
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('安装目录包含映射；未清理旧程序文件。')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('程序文件位于安装目录之外；未清理旧程序文件。')
    return path


def program_file(name):
    """Only private program namespaces are eligible; recordings/models stay untouched."""
    relative = PurePosixPath(name)
    first = relative.parts[0].casefold()
    if first in {'python', 'node', 'licenses'}:
        return True
    if first == 'linguaflow':
        return relative.suffix.casefold() in {'.py', '.pyi', '.mjs'}
    return len(relative.parts) == 1 and (relative.suffix.casefold() == '.dll' or first in {
        'agentscribe.exe', 'requirements-runtime.txt', 'requirements-mlx.txt',
        'third_party_notices.md', 'desktop.lock', 'update-config.json'})


def cleanup(root, previous):
    """Validate the new payload, then remove only old manifested program files.

    Missing old metadata means a first/legacy installation: nothing is guessed.
    Changed files or IO failures raise; the previous manifest remains for retry.
    """
    root = root.absolute()
    if previous.absolute() != root / PREVIOUS_MANIFEST:
        raise ValueError('旧程序清单必须位于安装目录中；未清理任何文件。')
    checked_path(root, PREVIOUS_MANIFEST)
    current = manifest_files(checked_path(root, 'build-manifest.json'))
    for name, digest in current.values():
        path = checked_path(root, name)
        if not path.is_file() or checksum(path) != digest:
            raise ValueError('新版程序文件校验失败；未清理旧程序文件。')
    if not previous.exists():
        return []
    old = manifest_files(previous)
    obsolete = [value for key, value in old.items() if key not in current and program_file(value[0])]
    # Check all candidates before the first removal. Never delete edited old code.
    for name, digest in obsolete:
        path = checked_path(root, name)
        if path.exists() and (not path.is_file() or checksum(path) != digest):
            raise ValueError('旧程序文件已变化；未完成清理，请保留恢复材料。')
    removed = []
    for name, digest in obsolete:
        path = checked_path(root, name)
        if path.exists():
            if checksum(path) != digest:
                raise ValueError('旧程序文件在清理时变化；保留恢复材料后重试。')
            path.unlink()
            removed.append(name)
    previous.unlink()
    return removed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('此入口仅用于 Windows 安装器。')
    try:
        cleanup(Path(__file__).resolve().parents[1], args.previous)
    except (OSError, ValueError, TypeError) as error:
        print('Windows 安装清理失败：' + str(error), file=sys.stderr)
        sys.exit(1)
