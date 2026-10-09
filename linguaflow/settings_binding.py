"""Adapt explicitly supplied controls to preferences and an immutable session snapshot."""
from pathlib import Path

from .audio_processing.config import automatic_audio_config
from .core import Settings
from .preferences import PREFERENCES
from .qt_controls import data_index
from .translation_config import CONTEXT_COUNTS


class SettingsBinding:
    def __init__(self, controls):
        self.controls = controls

    def restore(self, values):
        for pref in PREFERENCES:
            control, value = self.controls[pref.key], values[pref.key]
            if pref.key in CONTEXT_COUNTS:
                value = CONTEXT_COUNTS[pref.key][0]
            if pref.kind == 'editable':
                if value:
                    control.setCurrentText(str(value))
            elif pref.kind == 'text':
                index = control.findText(str(value))
                if pref.key == 'compute' and 'NVIDIA' in str(value):
                    index = data_index(control, 'cuda')
                if index >= 0:
                    control.setCurrentIndex(index)
            elif pref.kind == 'data':
                if pref.key == 'translation_device' and value is None:
                    value = self.controls['compute'].currentData()
                control.setCurrentIndex(max(0, data_index(control, value)))
            elif pref.kind == 'bool':
                control.setChecked(value)
            else:
                control.setValue(value)

    def snapshot(self):
        getters = {'editable': 'currentText', 'text': 'currentText', 'data': 'currentData',
                   'bool': 'isChecked', 'float': 'value'}
        values = {p.key: getattr(self.controls[p.key], getters[p.kind])() for p in PREFERENCES}
        values.update({key: default for key, (default, _maximum) in CONTEXT_COUNTS.items()})
        return values

    def session_settings(self, device):
        values = self.snapshot()
        if values['translation_engine'] == 'llama':
            from .llama_assets import HY_GGUF
            if values['llama_model'] != HY_GGUF:
                values['llama_model'] = str(Path(values['llama_model'].strip()).expanduser().resolve())
        source, source_nllb = self.controls['source'].currentData()
        return Settings(
            device_id=device[0], loopback=device[1], asr_model=values['asr'].strip(),
            asr_device=self.controls['compute'].currentData(),
            translation_model=values['translation'].strip(), source=source, source_nllb=source_nllb,
            target=self.controls['target'].currentData(), input_sample_rate=48000,
            audio_processing=automatic_audio_config(),
            **{key: values[key] for key in ('translate', 'backend', 'translation_device',
               'translation_engine', 'llama_model',
               'qwen_model', 'update_seconds', 'draft_seconds', 'endpoint_seconds',
               'translation_before', 'translation_after', 'translation_initial_before')})
