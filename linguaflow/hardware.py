"""Installation eligibility for the pinned runtime, without importing PyTorch."""
import csv
import io
import platform
import subprocess
import sys

from .process_platform import spawn_options

TORCH_VERSION = '2.11.0'
CUDA_WHEEL = 'cu128'
MIN_DRIVER = (570, 65)
MIN_CAPABILITY = (7, 5)


def platform_target():
    machine = platform.machine().lower()
    if sys.platform == 'win32' and machine in ('amd64', 'x86_64'):
        return 'windows-x64'
    if sys.platform == 'darwin' and machine == 'arm64':
        return 'macos-arm64'
    raise ValueError('仅支持 Windows x64 和原生 Apple Silicon Mac；Intel Mac、Rosetta 和其他架构不允许安装。')


def check_installation():
    """Reject hardware before writes/downloads; the installer also tests GPU IO."""
    target = platform_target()
    if target == 'macos-arm64':
        return target
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,compute_cap,driver_version',
                                 '--format=csv,noheader'], check=True, capture_output=True,
                                text=True, timeout=15, **spawn_options())
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) != 3:
                continue
            capability = tuple(map(int, row[1].strip().split('.')))
            driver = tuple(map(int, row[2].strip().split('.')))
            if capability >= MIN_CAPABILITY and driver >= MIN_DRIVER:
                return target
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError('无法确认兼容 NVIDIA 显卡。请安装官方驱动后重试；不会安装 CPU 替代环境。') from exc
    raise ValueError('没有兼容显卡：需要 NVIDIA Turing 或更新架构（计算能力 ≥ 7.5），'
                     '驱动 ≥ 570.65。请升级驱动或使用支持的设备；不会回退 CPU。')


def main():
    print('安装前硬件检查通过：' + check_installation())


if __name__ == '__main__':
    main()
