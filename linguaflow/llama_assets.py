"""Pinned llama.cpp assets and platform choices; no model or Qt imports."""
import hashlib
import platform
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .runtime_paths import llama_server, model_directory
from .translation_models import HY_MODEL

HY_GGUF = 'tencent/Hy-MT2-1.8B-GGUF'
REVISION = 'a0c709d9fac510f2c807aa3af52872340dc37a4a'
MODEL_FILE = 'Hy-MT2-1.8B-Q4_K_M.gguf'
MODEL_SHA256 = 'dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699'
RELEASE_URL = 'https://github.com/ggml-org/llama.cpp/releases/download/b11254/'
ARCHIVES = {
    'mac': ('llama-b11254-bin-macos-arm64.tar.gz', '072306c7b14de03f3665279f82d83223fc95a9ec0ca670ef77d64bca4ca978b0'),
    'cpu': ('llama-b11254-bin-win-cpu-x64.zip', '358497e4e11d304e7bfea106186acad041b297be0096ef7e954294644a85e0aa'),
    'cuda': ('llama-b11254-bin-win-cuda-12.4-x64.zip', '93c56a2fd7592c10e03911415b8cd2e6d4c2560d2a2aa0ae220b810b8b039bbe'),
    'cudart': ('cudart-llama-bin-win-cuda-12.4-x64.zip', '8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6'),
    'vulkan': ('llama-b11254-bin-win-vulkan-x64.zip', 'cb041a8d405eea043c8fd2f4167348a429af30db820381905bc3587d34c54dde'),
}


def devices(system=None):
    return ('cpu', 'metal') if (system or sys.platform) == 'darwin' else ('cpu', 'cuda', 'vulkan')


def runtime_archives(device):
    machine = platform.machine().lower()
    if sys.platform == 'darwin' and machine == 'arm64' and device in ('cpu', 'metal'):
        return [ARCHIVES['mac']]
    if sys.platform == 'win32' and machine in ('amd64', 'x86_64') and device in devices():
        keys = ['cpu'] + (['cuda', 'cudart'] if device == 'cuda' else ['vulkan'] if device == 'vulkan' else [])
        return [ARCHIVES[key] for key in keys]
    raise ValueError('llama.cpp 安装支持 Apple Silicon Mac 和 Windows x64；请选择对应的计算设备。')


def model_path():
    return model_directory('Hy-MT2-1.8B-GGUF') / MODEL_FILE


def selected_model(settings):
    if getattr(settings, 'llama_model', ''):
        return settings.llama_model.strip()
    if settings.translation_model.strip() == HY_MODEL:
        return HY_GGUF
    raise ValueError('请选择 llama.cpp 的 GGUF 模型。')


def normalize_model_reference(model):
    """Validate Hub references without converting them into local filesystem paths."""
    model = model.strip()
    if model.startswith('hf://'):
        hub_gguf(model)
        return model
    return model if model == HY_GGUF else str(Path(model).expanduser().resolve())


def weights_path(model):
    if model.startswith('hf://'):
        repo, filename = hub_gguf(model)
        return model_directory('gguf-downloads').joinpath(*repo.split('/'), filename)
    return model_path() if model == HY_GGUF else Path(model).expanduser()


def hub_gguf(model):
    """Explicit Hub repository/file reference; never interpreted as a local path."""
    url = urlsplit(model)
    parts = url.path.strip('/').split('/')
    if (url.scheme != 'hf' or url.query or url.fragment or len(parts) < 2
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', url.netloc)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', parts[0])
            or url.netloc in ('.', '..') or parts[0] in ('.', '..')):
        raise ValueError('GGUF 下载地址格式：hf://作者/仓库/文件.gguf')
    filename = '/'.join(parts[1:])
    if (any(part in ('', '.', '..') for part in parts[1:]) or '\\' in filename
            or not filename.lower().endswith('.gguf') or ':' in filename):
        raise ValueError('GGUF 文件必须是仓库内的相对路径，且以 .gguf 结尾。')
    return url.netloc + '/' + parts[0], str(PurePosixPath(filename))


def validate_weights(model):
    path = weights_path(model)
    if not path.is_file() or path.suffix.lower() != '.gguf':
        raise ValueError('请选择已下载的 .gguf 文件，或准备内置 HY 1.8B 模型。')
    with path.open('rb') as handle:
        if handle.read(4) != b'GGUF':
            raise ValueError('GGUF 权重无效，请重新准备模型。')
    return path.resolve()


def resolve_assets(settings):
    runtime_archives(settings.translation_device)
    binary = llama_server(settings.translation_device)
    if not binary.is_file():
        raise ValueError('请到设置 → 翻译模型，点击“下载 / 检查翻译模型”准备 llama.cpp。')
    return binary, validate_weights(selected_model(settings))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()
