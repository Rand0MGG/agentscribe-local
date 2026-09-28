"""Local runtime locations shared by desktop tools; no Qt/model imports."""
import sys
from pathlib import Path


def runtime_python():
    root = Path(__file__).resolve().parents[1]
    return root / '.venv-wlk' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def mlx_python():
    return Path(__file__).resolve().parents[1] / '.venv-mlx' / 'bin/python'
