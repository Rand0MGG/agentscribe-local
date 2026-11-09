"""Adapt explicitly supplied controls to preferences and an immutable session snapshot."""
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
        from .session_settings import session_settings
        return session_settings(self.snapshot(), device)
