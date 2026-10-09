"""Shared backend/device choices and model selection, without Qt or model imports."""
import sys

from .llama_assets import devices as llama_devices

QWEN_MODELS = ('Qwen/Qwen3-ASR-0.6B', 'Qwen/Qwen3-ASR-1.7B')
MLX_MODEL = 'mlx-community/Qwen3-ASR-1.7B-4bit'


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
