"""Shared model catalog and backend/device choices, without Qt or inference libraries."""
import sys

from .llama_assets import HY_GGUF
from .llama_assets import devices as llama_devices
from .translation_models import HY_MODEL

QWEN_MODELS = ('Qwen/Qwen3-ASR-0.6B', 'Qwen/Qwen3-ASR-1.7B')
MLX_MODEL = 'mlx-community/Qwen3-ASR-1.7B-4bit'
MLX_8BIT_MODEL = 'mlx-community/Qwen3-ASR-1.7B-8bit'


def recommended_selection(system=None):
    """Platform defaults only; orchestration always receives an explicit selection."""
    apple = (system or sys.platform) == 'darwin'
    return dict(backend='qwen3-mlx' if apple else 'qwen3-streaming',
                asr_model=MLX_MODEL if apple else QWEN_MODELS[1],
                translation_engine='llama', translation_model=HY_GGUF,
                translation_device='metal' if apple else 'cuda')


def model_catalog(engine):
    """Curated identifiers shared by editors and download orchestration."""
    if engine == 'wlk-whisper':
        return [(name, name) for name in ('tiny', 'base', 'small', 'medium', 'large-v3')]
    if engine == 'qwen3-streaming':
        return [(name.rsplit('/', 1)[-1] + ' · 原始权重', name) for name in QWEN_MODELS]
    if engine == 'qwen3-mlx':
        return [('Qwen3-ASR 1.7B · 4-bit / MLX', MLX_MODEL),
                ('Qwen3-ASR 1.7B · 8-bit / MLX（待实机验收）', MLX_8BIT_MODEL)]
    if engine == 'llama':
        return [('HY-MT2 1.8B · Q4_K_M / 4-bit', HY_GGUF)] + [
            (f'HY-MT2 1.8B · {quant}', f'hf://{HY_GGUF}/Hy-MT2-1.8B-{quant}.gguf')
            for quant in ('Q6_K', 'Q8_0')]
    if engine == 'pytorch':
        return [(name.rsplit('/', 1)[-1], name) for name in
                (HY_MODEL, 'facebook/nllb-200-distilled-600M', 'facebook/nllb-200-distilled-1.3B')]
    raise ValueError('不支持的模型引擎')


def download_catalog(system=None):
    """Simple download choices; Windows never advertises an unsupported MLX model."""
    recommendation = recommended_selection(system)
    apple = recommendation['backend'] == 'qwen3-mlx'
    entries = [('Qwen3-ASR 1.7B' + (' · 4-bit' if apple else ''),
                '语音识别 · 内存占用更少' if apple else '语音识别 · Windows 当前兼容版本',
                'asr', recommendation['backend'], recommendation['asr_model'])]
    if apple:
        entries.append(('Qwen3-ASR 1.7B · 8-bit', '语音识别 · 保留更多精度 · 待实机验收',
                        'asr', 'qwen3-mlx', MLX_8BIT_MODEL))
    entries.append(('HY-MT2 1.8B · 4-bit', '翻译 · Q4_K_M · llama.cpp',
                    'translation', recommendation['translation_engine'], recommendation['translation_model']))
    return entries


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
    return QWEN_MODELS + (MLX_MODEL, MLX_8BIT_MODEL) if (system or sys.platform) == 'darwin' else QWEN_MODELS


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
    return device, QWEN_MODELS[0] if model in (MLX_MODEL, MLX_8BIT_MODEL) else model
