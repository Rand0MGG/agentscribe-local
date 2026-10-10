"""Shared backend/device choices and model selection, without Qt or model imports."""
import sys

from .llama_assets import devices as llama_devices

QWEN_MODELS = ('Qwen/Qwen3-ASR-0.6B', 'Qwen/Qwen3-ASR-1.7B')
MLX_MODEL = 'mlx-community/Qwen3-ASR-1.7B-4bit'


def recommended_selection(system=None):
    """Platform defaults only; orchestration always receives an explicit selection."""
    from .llama_assets import HY_GGUF
    from .translation_models import HY_MODEL
    apple = (system or sys.platform) == 'darwin'
    return dict(backend='qwen3-mlx' if apple else 'wlk-whisper',
                asr_model=MLX_MODEL if apple else 'tiny',
                translation_engine='llama' if apple else 'pytorch',
                translation_model=HY_GGUF if apple else HY_MODEL,
                translation_device='metal' if apple else 'cuda')


def required_runtimes(backend):
    if backend not in asr_backends():
        raise ValueError('识别引擎不适用于当前平台。')
    return ('wlk', 'mlx') if backend == 'qwen3-mlx' else ('wlk',)


def asr_backends(system=None):
    """Available recognition adapters; installation/runtime checks remain separate."""
    shared = ('wlk-whisper', 'qwen3-streaming')
    return shared + ('qwen3-mlx',) if (system or sys.platform) == 'darwin' else shared


def asr_devices(system=None):
    """Preserve current platform choices without probing hardware."""
    return ('cpu', 'mlx') if (system or sys.platform) == 'darwin' else ('cpu', 'cuda')


def qwen_models(system=None):
    return QWEN_MODELS + (MLX_MODEL,) if (system or sys.platform) == 'darwin' else QWEN_MODELS


def translation_devices(engine, system=None):
    if engine == 'llama':
        return llama_devices(system)
    if engine != 'pytorch':
        raise ValueError('不支持的翻译引擎')
    return ('cpu',) if (system or sys.platform) == 'darwin' else ('cpu', 'cuda')


def normalize_asr_selection(backend, device, model):
    """Keep the established backend switch rules, preserving local model paths."""
    if backend == 'qwen3-mlx':
        return 'mlx', MLX_MODEL if model.startswith('Qwen/') else model
    if device == 'mlx':
        device = 'cpu'
    return device, QWEN_MODELS[0] if model == MLX_MODEL else model
