import json

from linguaflow.preferences import PREFERENCES, read_audio_device, read_preferences, write_preferences


class Store:
    def __init__(self, **values):
        self.values = values

    def value(self, key, default=None, **kwargs):
        value = self.values.get(key, default)
        return kwargs['type'](value) if kwargs.get('type') else value

    def setValue(self, key, value):
        self.values[key] = value


def test_legacy_defaults_and_corrupt_values():
    values = read_preferences(Store(backend='qwen-stream', draft_seconds='bad', audio_processing='bad'))
    assert values['backend'] == 'qwen3-streaming'
    assert values['draft_seconds'] == .5
    assert values['translate'] is True and values['offline'] is False
    assert values['translation_device'] is None  # UI falls back to selected compute device.
    assert isinstance(values['audio_processing'], dict)


def test_all_keys_roundtrip_and_missing_device_does_not_erase_selection():
    store = Store(audio_device=json.dumps(['microphone', False]))
    values = read_preferences(store)
    values.update(asr='local-checkpoint', update_seconds=1.5, offline=True)
    write_preferences(store, values)
    restored = read_preferences(store)
    assert {p.key: restored[p.key] for p in PREFERENCES} == {p.key: values[p.key] for p in PREFERENCES}
    assert restored['audio_processing'] == values['audio_processing']
    assert read_audio_device(store) == ('microphone', False)
    for invalid in ('bad', '[]', '"abc"', '["device", "False"]'):
        assert read_audio_device(Store(audio_device=invalid)) is None


def test_legacy_metal_migrates_to_llama_without_overriding_explicit_engine():
    assert read_preferences(Store(translation_device='metal'))['translation_engine'] == 'llama'
    assert read_preferences(Store(translation_device='cuda'))['translation_engine'] == 'pytorch'
    assert read_preferences(Store(translation_device='metal', translation_engine='pytorch'))['translation_engine'] == 'pytorch'


def test_draft_final_context_defaults_and_legacy_default_upgrade():
    assert read_preferences(Store())['translation_before'] == 10
    assert read_preferences(Store())['translation_initial_before'] == 1
    assert read_preferences(Store(translation_before=3))['translation_before'] == 10
    for before in (0, 2, 6):
        assert read_preferences(Store(translation_before=before))['translation_before'] == before
    assert read_preferences(Store(translation_before=3, translation_initial_before=0))['translation_before'] == 3
