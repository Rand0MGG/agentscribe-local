"""Preference keys, defaults and codecs, independent of Qt and window layout."""
import json
import math
from contextlib import nullcontext
from dataclasses import dataclass

from .core import LANGUAGES
from .model_options import (
    ASR_DEVICE_LABELS,
    asr_backends,
    asr_device_code,
    backend_devices,
    translation_devices,
)
from .translation_config import CONTEXT_COUNTS, context_count


@dataclass(frozen=True)
class Preference:
    key: str
    kind: str
    default: object = None


PREFERENCES = (
    Preference('asr', 'editable'), Preference('translation', 'editable'),
    Preference('source', 'text', 'English'), Preference('target', 'text'), Preference('compute', 'text'),
    Preference('translate', 'bool', True),
    Preference('backend', 'data', 'wlk-whisper'),
    Preference('qwen_model', 'editable', 'Qwen/Qwen3-ASR-0.6B'),
    Preference('llama_model', 'editable', 'tencent/Hy-MT2-1.8B-GGUF'),
    Preference('translation_engine', 'data', 'pytorch'),
    Preference('translation_device', 'data'),
    *(Preference(key, 'data', default) for key, (default, _maximum) in CONTEXT_COUNTS.items()),
    Preference('update_seconds', 'float', 1.), Preference('endpoint_seconds', 'float', .5),
    Preference('draft_seconds', 'float', .5),
    Preference('appearance', 'data', 'light'),
    Preference('reduce_motion', 'bool', False),
    Preference('beta_features', 'bool', False),
)


def read_preferences(store):
    values = {}
    for pref in PREFERENCES:
        if pref.key == 'beta_features':
            # An opt-in must not become enabled by a corrupt/non-empty string.
            value = store.value(pref.key, pref.default)
            values[pref.key] = (value is True or type(value) is int and value == 1
                               or isinstance(value, str) and value.strip().casefold() in ('true', '1'))
            continue
        converter = {'bool': bool, 'float': float}.get(pref.kind)
        try:
            values[pref.key] = store.value(pref.key, pref.default, **({'type': converter} if converter else {}))
        except (ValueError, TypeError):
            values[pref.key] = pref.default
    for key, (default, maximum) in CONTEXT_COUNTS.items():
        values[key] = context_count(values[key], default, maximum)
    if store.value('translation_engine') is None and values['translation_device'] == 'metal':
        values['translation_engine'] = 'llama'
    values['backend'] = {'whisper-live': 'wlk-whisper', 'qwen-stream': 'qwen3-streaming'}.get(
        values['backend'], values['backend'])
    return values


def write_preferences(store, values):
    changes = {pref.key: values[pref.key] for pref in PREFERENCES}
    if values.get('audio_device') is not None:
        changes['audio_device'] = json.dumps(values['audio_device'])
    if hasattr(store, 'commit_values'):
        if not store.commit_values(changes):
            raise OSError('设置写入失败，请检查配置目录权限。')
        return
    with store.batch() if hasattr(store, 'batch') else nullcontext():
        for key, value in changes.items():
            store.setValue(key, value)



def read_audio_device(store):
    try:
        value = json.loads(store.value('audio_device', 'null'))
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], bool):
            return tuple(value)
    except (ValueError, TypeError):
        pass
    return None


def validated_preferences(current, values):
    if not isinstance(values, dict) or set(values) - {p.key for p in PREFERENCES}:
        raise ValueError('无效的设置项。')
    candidate = {**current, **values}
    for pref in PREFERENCES:
        value = candidate[pref.key]
        if pref.kind == 'bool' and type(value) is not bool:
            raise ValueError('开关设置必须是布尔值。')
        if pref.kind == 'float' and (type(value) not in (float, int) or not math.isfinite(value)
                                    or not (.25 if pref.key == 'draft_seconds' else .5) <= value <= 3):
            raise ValueError('字幕时间参数超出范围。')
        if pref.kind in ('text', 'editable') and (not isinstance(value, str) or len(value) > 4096):
            raise ValueError('无效的文字设置。')
    if candidate['backend'] not in asr_backends() or candidate['appearance'] not in ('light', 'dark'):
        raise ValueError('不支持的引擎或外观。')
    if candidate['translation_engine'] not in ('llama', 'pytorch'):
        raise ValueError('不支持的翻译引擎。')
    if candidate['backend'] == 'qwen3-streaming' and candidate['qwen_model'].startswith('mlx-community/'):
        raise ValueError('MLX 权重需要 Apple Silicon Mac 的 MLX 引擎，当前引擎不能使用。')
    if candidate['translation_engine'] == 'llama' and candidate['llama_model'].startswith('hf://'):
        from .llama_assets import hub_gguf
        hub_gguf(candidate['llama_model'])
    if candidate['translation_device'] not in translation_devices(candidate['translation_engine']):
        raise ValueError('翻译设备不适用于当前平台和引擎。')
    if candidate['source'] not in ['自动检测', *(row[0] for row in LANGUAGES)] or candidate['target'] not in [row[0] for row in LANGUAGES]:
        raise ValueError('不支持的语言。')
    if candidate['backend'] != 'wlk-whisper' and candidate['source'] == '自动检测':
        candidate['source'] = 'English'
    if candidate['source'] == candidate['target']:
        candidate['translate'] = False
    compute = asr_device_code(candidate['compute'])
    devices = backend_devices(candidate['backend'])
    if 'compute' not in values and candidate['backend'] != current['backend'] and compute not in devices:
        compute = devices[0]
    if compute not in devices:
        raise ValueError('识别设备不适用于当前平台和引擎。')
    candidate['compute'] = ASR_DEVICE_LABELS[compute]
    candidate.update({key: default for key, (default, _maximum) in CONTEXT_COUNTS.items()})
    return candidate
