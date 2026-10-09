"""Local runtime locations shared by desktop tools; no Qt/model imports."""
import shutil
import sys
from pathlib import Path


def runtime_python():
    root = Path(__file__).resolve().parents[1]
    return root / '.venv-wlk' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def mlx_python():
    return Path(__file__).resolve().parents[1] / '.venv-mlx' / 'bin/python'


def knowledge_python():
    """Optional text SDKs run outside Qt, using the compatible desktop environment."""
    return Path(sys.executable)


DOCUMENT_RENDERER_VERSION = '0.1.3'


def document_renderer():
    """Return the project-owned DSH renderer entry and a compatible Node executable."""
    root = Path(__file__).resolve().parents[1] / '.runtime' / 'document-renderer'
    node = shutil.which('node')
    entry = root / 'node_modules' / '@deepseek-ai' / 'libreoffice-kit' / 'lib' / 'index.js'
    if node is None or not entry.is_file():
        raise RuntimeError('请先安装 Node.js 22.19 或更新版本，并运行 scripts/install_documents.py 准备课件渲染组件。')
    return Path(node), entry


def llama_server(device='cpu'):
    root = Path(__file__).resolve().parents[1] / '.runtime' / 'llama-b11254'
    if sys.platform == 'win32':
        return root / ('windows-x64-' + device) / 'llama-server.exe'
    return root / 'llama-server'
