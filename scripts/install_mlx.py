"""Install Apple GPU ASR separately from the shared WLK runtime."""
import platform
import subprocess
import sys
from pathlib import Path


def main():
    if sys.platform != 'darwin' or platform.machine().lower() != 'arm64':
        raise SystemExit('MLX 识别需要 Apple Silicon Mac 和原生 arm64 Python。')
    root = Path(__file__).resolve().parents[1]
    environment = root / '.venv-mlx'
    subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
    python = environment / 'bin/python'
    subprocess.run([str(python), '-m', 'pip', 'install', '-r',
                    str(root / 'requirements-mlx.txt')], check=True)
    subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
    print('Apple GPU / MLX 识别环境已安装。请在识别模型页准备 4-bit 权重。')


if __name__ == '__main__':
    main()
