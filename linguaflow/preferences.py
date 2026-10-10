"""Preference keys, defaults and codecs, independent of Qt and window layout."""
import json
from dataclasses import dataclass

from .translation_config import CONTEXT_COUNTS, context_count


@dataclass(frozen=True)
class Preference:
    key: str
    kind: str
    default: object = None


PREFERENCES = (
    Preference('asr', 'editable'), Preference('translation', 'editable'),
    Preference('source', 'text'), Preference('target', 'text'), Preference('compute', 'text'),
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
    for pref in PREFERENCES:
        store.setValue(pref.key, values[pref.key])
    if values.get('audio_device') is not None:
        store.setValue('audio_device', json.dumps(values['audio_device']))


def read_audio_device(store):
    try:
        value = json.loads(store.value('audio_device', 'null'))
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], bool):
            return tuple(value)
    except (ValueError, TypeError):
        pass
    return None
