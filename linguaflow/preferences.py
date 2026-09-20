"""Preference keys, defaults and codecs, independent of Qt and window layout."""
import json
from dataclasses import dataclass

from .audio_processing.config import AudioConfig


@dataclass(frozen=True)
class Preference:
    key: str
    kind: str
    default: object = None


PREFERENCES = (
    Preference('asr', 'editable'), Preference('translation', 'editable'),
    Preference('source', 'text'), Preference('target', 'text'), Preference('compute', 'text'),
    Preference('offline', 'bool', False), Preference('translate', 'bool', True),
    Preference('backend', 'data', 'wlk-whisper'),
    Preference('qwen_model', 'editable', 'Qwen/Qwen3-ASR-0.6B'),
    Preference('translation_device', 'data'),
    Preference('translation_before', 'data', 3), Preference('translation_after', 'data', 1),
    Preference('update_seconds', 'float', 1.), Preference('endpoint_seconds', 'float', .5),
    Preference('semantic_lookahead', 'float', 3.), Preference('caption_max_seconds', 'float', 12.),
    Preference('draft_seconds', 'float', .5), Preference('semantic_mode', 'data', 'auto'),
    Preference('semantic_device', 'data', 'cpu'),
)


def read_preferences(store):
    values = {}
    for pref in PREFERENCES:
        converter = {'bool': bool, 'float': float}.get(pref.kind)
        try:
            values[pref.key] = store.value(pref.key, pref.default, **({'type': converter} if converter else {}))
        except (ValueError, TypeError):
            values[pref.key] = pref.default
    values['backend'] = {'whisper-live': 'wlk-whisper', 'qwen-stream': 'qwen3-streaming'}.get(
        values['backend'], values['backend'])
    try:
        values['audio_processing'] = AudioConfig.from_dict(json.loads(store.value('audio_processing', '{}'))).to_dict()
    except (ValueError, TypeError, AttributeError):
        values['audio_processing'] = AudioConfig().to_dict()
    return values


def write_preferences(store, values):
    for pref in PREFERENCES:
        store.setValue(pref.key, values[pref.key])
    store.setValue('audio_processing', json.dumps(values['audio_processing']))
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
