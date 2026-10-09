import json

import pytest

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
    assert values['translate'] is True
    assert values['translation_device'] is None  # UI falls back to selected compute device.
    assert 'audio_processing' not in values


def test_all_keys_roundtrip_and_missing_device_does_not_erase_selection():
    store = Store(audio_device=json.dumps(['microphone', False]))
    values = read_preferences(store)
    values.update(asr='local-checkpoint', update_seconds=1.5)
    write_preferences(store, values)
    restored = read_preferences(store)
    assert {p.key: restored[p.key] for p in PREFERENCES} == {p.key: values[p.key] for p in PREFERENCES}
    assert read_audio_device(store) == ('microphone', False)
    for invalid in ('bad', '[]', '"abc"', '["device", "False"]'):
        assert read_audio_device(Store(audio_device=invalid)) is None


@pytest.mark.parametrize('stored, expected', [(False, False), (True, True), (0, False), (1, True),
    ('false', False), ('true', True), ('1', True), ('0', False), ('invalid', False), (None, False),
    (2, False), (1.0, False), ({}, False)])
def test_beta_opt_in_defaults_off_and_rejects_corrupt_settings(stored, expected):
    assert read_preferences(Store())['beta_features'] is False
    assert read_preferences(Store(beta_features=stored))['beta_features'] is expected


def test_retired_offline_preference_is_ignored():
    values = read_preferences(Store(offline=True, translate=False))
    assert 'offline' not in values
    assert values['translate'] is False


def test_retired_manual_audio_settings_do_not_return_or_get_saved():
    store = Store(audio_processing=json.dumps({'deepfilter': True, 'output_db': 10}))
    values = read_preferences(store)
    assert 'audio_processing' not in values
    destination = Store()
    write_preferences(destination, values)
    assert 'audio_processing' not in destination.values


def test_legacy_metal_migrates_to_llama_without_overriding_explicit_engine():
    assert read_preferences(Store(translation_device='metal'))['translation_engine'] == 'llama'
    assert read_preferences(Store(translation_device='cuda'))['translation_engine'] == 'pytorch'
    assert read_preferences(Store(translation_device='metal', translation_engine='pytorch'))['translation_engine'] == 'pytorch'


def test_draft_final_context_defaults_preserve_saved_user_choices():
    assert read_preferences(Store())['translation_before'] == 5
    assert read_preferences(Store())['translation_initial_before'] == 1
    for before in range(11):
        assert read_preferences(Store(translation_before=before))['translation_before'] == before
    assert read_preferences(Store(translation_before=3, translation_initial_before=0))['translation_before'] == 3


@pytest.mark.parametrize('stored, expected', [('3', 3), (-4, 0), (500, 10), (None, 5),
                                             ('bad', 5), (True, 5), (1.5, 5), (float('inf'), 5)])
def test_context_count_normalizes_old_or_corrupt_preferences(stored, expected):
    assert read_preferences(Store(translation_before=stored))['translation_before'] == expected
