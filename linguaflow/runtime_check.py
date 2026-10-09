"""Inference-environment verification worker; never imported by the desktop."""
import argparse
import sys

from .hardware import CUDA_WHEEL, TORCH_VERSION


def verify(kind):
    if kind == 'mlx':
        import mlx.core as mx
        import mlx_audio.stt  # noqa: F401
        if not mx.metal.is_available():
            raise RuntimeError('Apple GPU / Metal 不可用。')
        value = mx.ones((2, 2), stream=mx.gpu)
        mx.eval(value @ value)
    else:
        import torch
        import whisperlivekit  # noqa: F401
        import wtpsplit  # noqa: F401
        if sys.platform == 'win32':
            if torch.__version__ != TORCH_VERSION + '+' + CUDA_WHEEL or not torch.cuda.is_available():
                raise RuntimeError('CUDA PyTorch 版本不匹配或兼容显卡不可用，请检查驱动。')
            # Check the application's default device, not a different GPU in a
            # mixed-card machine. Never switch devices to pass installation.
            value = torch.ones((2, 2), device='cuda')
            (value @ value).cpu()
            torch.cuda.synchronize()
        else:
            if not torch.backends.mps.is_available():
                raise RuntimeError('Apple GPU / MPS 不可用。')
            value = torch.ones((2, 2), device='mps')
            (value @ value).cpu()
    print('依赖和 GPU 运算检查通过（未加载识别模型）。', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('wlk', 'mlx'))
    verify(parser.parse_args().kind)


if __name__ == '__main__':
    main()
