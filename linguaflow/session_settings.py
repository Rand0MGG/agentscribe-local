"""Build the same immutable recording settings from either frontend's values."""
from .audio_processing.config import automatic_audio_config
from .core import LANGUAGES, Settings


def session_settings(values, device):
    from .llama_assets import normalize_model_reference
    language = next((row for row in LANGUAGES if row[0] == values['source']), (None, None, None))
    target = next((row[2] for row in LANGUAGES if row[0] == values['target']), 'zho_Hans')
    compute = {'CPU（通用）': 'cpu', 'NVIDIA GPU · 半精度': 'cuda',
               'Apple GPU · Metal / MLX': 'mlx'}.get(values['compute'], values['compute'])
    shared = {key: values[key] for key in (
        'translate', 'backend', 'qwen_model', 'llama_model', 'translation_engine', 'translation_device',
        'translation_before', 'translation_after', 'translation_initial_before',
        'update_seconds', 'draft_seconds', 'endpoint_seconds')}
    if shared['translation_engine'] == 'llama':
        shared['llama_model'] = normalize_model_reference(shared['llama_model'])
    return Settings(device_id=device[0], loopback=device[1], asr_model=values['asr'].strip(),
                    asr_device=compute, translation_model=values['translation'].strip(),
                    source=language[1], source_nllb=language[2], target=target, input_sample_rate=48000,
                    audio_processing=automatic_audio_config(), **shared)
