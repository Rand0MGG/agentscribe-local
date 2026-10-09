"""Application resources and durable user/runtime paths; no Qt/model imports."""
import json
import os
import shutil
import sys
from pathlib import Path

from .runtime_base import python_abi


def packaged():
    return bool(getattr(sys, 'frozen', False) or '__compiled__' in globals()
                or os.environ.get('AGENTSCRIBE_PACKAGED') == '1')


def resource_root():
    """Read-only source/bundle resources, never the user's current directory."""
    inherited = os.environ.get('AGENTSCRIBE_RESOURCES') if packaged() else None
    return Path(inherited) if inherited else Path(__file__).resolve().parents[1]


def user_data_root():
    """Installation/update removal must never include this directory."""
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / 'AgentScribe'


def recordings_root():
    return user_data_root() / '录音'


def runtime_root():
    return user_data_root() / 'runtime' if packaged() else resource_root() / '.runtime'


def cache_root():
    return user_data_root() / 'cache' if packaged() else resource_root() / '.work' / 'cache'


def model_directory(name):
    """Reuse old explicitly installed weights without moving/deleting them."""
    legacy = resource_root() / 'models' / name
    return legacy if legacy.is_dir() else user_data_root() / 'models' / name


def whisper_cache_root():
    """Retain Whisper's existing cache, including an explicit XDG override."""
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'whisper'


def environment_python(directory):
    return Path(directory) / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def runtime_environment(kind):
    """Select a verified environment at its original, non-relocated path."""
    base = runtime_root() / 'python' / kind
    fallback = (resource_root() / ('.venv-wlk' if kind == 'wlk' else '.venv-mlx')
                if not packaged() else base / 'not-installed')
    return active_directory(base, fallback, python=True)


def active_directory(base, fallback, *, python=False):
    """Resolve only a validated local slot name, never a path from metadata."""
    pointer = base / 'active.json'
    if pointer.exists():
        try:
            value = json.loads(pointer.read_text(encoding='utf-8'))
            slot = value['slot']
            if not isinstance(slot, str) or len(slot) != 32 or any(c not in '0123456789abcdef' for c in slot):
                raise ValueError('invalid slot')
            if python:
                return compatible_environment(base, value)
            environment = base / slot
            if not environment.is_dir():
                raise ValueError('missing component')
            return environment
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError('运行环境记录损坏，请在设置中重新安装 / 修复；旧环境仍保留。') from exc
    return fallback


def compatible_environment(base, value):
    """Select a previously published compatible slot after app upgrades/rollback.

    Follow only the explicit bounded previous chain; never adopt an unfinished
    directory or mutate the active pointer while resolving a session interpreter.
    """
    from .hardware import TORCH_VERSION, platform_target
    filename = 'requirements-runtime.txt' if base.name == 'wlk' else 'requirements-mlx.txt'
    required = (resource_root() / filename).read_text(encoding='utf-8') if 'requirements' in value else None
    seen = set()
    for _ in range(32):
        slot = value['slot']
        if (not isinstance(slot, str) or len(slot) != 32 or any(c not in '0123456789abcdef' for c in slot)
                or slot in seen):
            raise ValueError('invalid previous slot')
        seen.add(slot)
        environment = base / slot
        matches = ('requirements' not in value or (
            value['requirements'] == required and value.get('platform') == platform_target()
            and (base.name != 'wlk' or value.get('torch_version') == TORCH_VERSION)))
        if 'python_abi' in value:
            matches = matches and value['python_abi'] == python_abi()
        base_slot = value.get('base_slot')
        if base_slot is not None:
            if (not isinstance(base_slot, str) or len(base_slot) != 64
                    or any(c not in '0123456789abcdef' for c in base_slot)):
                raise ValueError('invalid base Python')
            matches = matches and (runtime_root() / 'base-python' / base_slot / 'base.json').is_file()
        if matches and environment_python(environment).is_file():
            return environment
        previous = value.get('previous')
        if previous is None:
            break
        if not isinstance(previous, str) or len(previous) != 32 or any(c not in '0123456789abcdef' for c in previous):
            raise ValueError('invalid previous slot')
        record = base / previous / 'environment.json'
        value = json.loads(record.read_text(encoding='utf-8'))
        if value.get('slot') != previous:
            raise ValueError('mismatched environment record')
    raise RuntimeError('运行组件与当前软件版本或平台不匹配或已损坏，请重新安装 / 修复环境；旧文件保留。')


def runtime_python():
    return environment_python(runtime_environment('wlk'))


def mlx_python():
    return environment_python(runtime_environment('mlx'))


def knowledge_python():
    """Frozen executables are bootloaders, never pass Python -m to them."""
    if not packaged():
        return Path(sys.executable)
    # The bundle contains a portable full Python distribution, not a relocated
    # venv (whose launchers and pyvenv.cfg retain absolute machine paths).
    python = resource_root() / 'python' / ('python.exe' if sys.platform == 'win32' else 'bin/python3')
    if not python.is_file():
        raise RuntimeError('安装内容缺少桌面 Python 组件，请重新安装完整版本。')
    return python


def python_environment():
    """Make shared modules importable in each isolated source/bundled worker."""
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONPATH': os.pathsep.join(
        filter(None, (str(resource_root()), os.environ.get('PYTHONPATH', ''))))}
    if packaged():
        environment.update(AGENTSCRIBE_PACKAGED='1', AGENTSCRIBE_RESOURCES=str(resource_root()))
    return environment


def installation_command(module, *args):
    return [str(knowledge_python()), '-u', '-m', module, *map(str, args)]


DOCUMENT_RENDERER_VERSION = '0.1.3'


def document_renderer():
    root = active_directory(runtime_root() / 'components' / 'document-renderer', runtime_root() / 'document-renderer')
    owned_node = runtime_root() / 'node' / ('node.exe' if sys.platform == 'win32' else 'bin/node')
    node = owned_node if owned_node.is_file() else shutil.which('node') if not packaged() else None
    entry = root / 'node_modules' / '@deepseek-ai' / 'libreoffice-kit' / 'lib' / 'index.js'
    if node is None or not entry.is_file():
        raise RuntimeError('课件渲染组件未准备完整。源码版请安装 Node.js 22.19 或更新版本，并运行 scripts/install_documents.py。')
    return Path(node), entry


def llama_server(device='cpu'):
    name = 'llama-b11254-' + ('windows-x64-' + device if sys.platform == 'win32' else 'macos-arm64')
    legacy = runtime_root() / 'llama-b11254'
    if sys.platform == 'win32':
        legacy /= 'windows-x64-' + device
    root = active_directory(runtime_root() / 'components' / name, legacy)
    return root / ('llama-server.exe' if sys.platform == 'win32' else 'llama-server')
