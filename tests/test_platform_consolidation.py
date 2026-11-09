"""Shared platform rules preserve defaults, ownership and both ASR contracts."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.asr_review import RepetitionReviewError
from linguaflow.os_lock import exclusive_lock
from linguaflow.qwen_generation import install_generation_review
from linguaflow.runtime_paths import user_data_root
from linguaflow.settings_store import SettingsStore


@pytest.mark.p1
@pytest.mark.parametrize('system', ['darwin', 'win32', 'linux'])
@pytest.mark.parametrize('override', [None, '', 'custom'])
def test_preferences_share_canonical_user_directory(tmp_path, monkeypatch, system, override):
    monkeypatch.setattr(sys, 'platform', system)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(SettingsStore, '_native_legacy', lambda *_: {})
    for key in ('LOCALAPPDATA', 'XDG_DATA_HOME'):
        monkeypatch.delenv(key, raising=False)
        if override is not None:
            monkeypatch.setenv(key, str(tmp_path / override) if override else '')
    assert SettingsStore().path == user_data_root() / 'preferences.json'
    explicit = tmp_path / 'selected.json'
    assert SettingsStore(explicit, 1).path == explicit


@pytest.mark.p0
def test_common_os_lock_excludes_other_owner_and_releases_after_failure(tmp_path):
    path = tmp_path / 'guard'
    with path.open('a+b') as one, path.open('a+b') as two:
        with pytest.raises(ValueError, match='body failed'):
            with exclusive_lock(one):
                with pytest.raises(OSError):
                    with exclusive_lock(two):
                        pytest.fail('concurrent owner acquired lock')
                raise ValueError('body failed')
        with exclusive_lock(two):
            pass
    assert path.exists()


def official_model(outputs):
    calls, decoded = [], []
    outputs = iter(outputs)
    texts = {}
    def generate(**options):
        calls.append(options)
        text, count = next(outputs)
        key = len(calls)
        texts[key] = text
        ids = np.full((1, options['input_ids'].shape[1] + count), key)
        return SimpleNamespace(sequences=ids)
    def batch_decode(ids, **options):
        decoded.append(ids.shape[1])
        return [texts[int(ids[0, 0])] if ids.shape[1] else '']
    model = SimpleNamespace(model=SimpleNamespace(generate=generate),
                            processor=SimpleNamespace(batch_decode=batch_decode))
    install_generation_review(model)
    return model, calls, decoded


@pytest.mark.p1
@pytest.mark.parametrize('text,count', [('yeah, '*255, 511), ('yeah, yeah, I agree',512), (' '.join(f'word{i}' for i in range(512)),512)])
def test_official_normal_output_keeps_raw_result_and_single_generation(text, count):
    asr, calls, decoded = official_model([(text, count)])
    features = np.ones((1, 8))
    result = asr.model.generate(input_ids=np.ones((1, 37)), input_features=features, max_new_tokens=512)
    assert result.sequences.shape == (1, 37 + count) and len(calls) == 1
    assert calls[0]['input_features'] is features and 'repetition_penalty' not in calls[0]
    assert len(decoded) == (count == 512)


@pytest.mark.p1
def test_official_recovery_uses_actual_generated_ids_same_input_and_no_parameter_leak():
    asr, calls, _ = official_model([('Oh, '+ 'yeah, '*255,512),('Oh, yeah.',4),('Next sentence',3)])
    parameters = dict(input_ids=np.ones((1, 37)), input_features=np.ones((1, 200)), max_new_tokens=512)
    result = asr.model.generate(**parameters)
    assert result.sequences.shape[1] == 41 and len(calls) == 2
    assert calls[1]['repetition_penalty'] == 1.1
    for key in ('input_ids','input_features'):
        assert calls[0][key] is calls[1][key] is parameters[key]
    asr.model.generate(**parameters)
    assert 'repetition_penalty' not in calls[2]


@pytest.mark.p1
@pytest.mark.parametrize('recovery', [('',1),('yeah, '*255,512)])
def test_official_failed_recovery_rejects_the_candidate(recovery):
    asr, calls, _ = official_model([('yeah, '*255,512),recovery])
    with pytest.raises(RepetitionReviewError):
        asr.model.generate(input_ids=np.ones((1, 37)), max_new_tokens=512)
    assert len(calls) == 2


@pytest.mark.p0
@pytest.mark.parametrize('system', ['win32', 'linux'])
def test_old_default_json_is_preserved_when_canonical_root_changes(tmp_path, monkeypatch, system):
    monkeypatch.setattr(sys, 'platform', system)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg'))
    monkeypatch.setattr(SettingsStore, '_native_legacy', lambda *_: {})
    old = tmp_path / '.local/share/AgentScribe/preferences.json'
    old.parent.mkdir(parents=True)
    original = b'{"library_root":"old-library","translate":false}'
    old.write_bytes(original)
    prefs = SettingsStore()
    assert prefs.path != old and prefs.value('library_root') == 'old-library'
    prefs.setValue('appearance', 'dark')
    prefs.sync()
    assert prefs.status() == SettingsStore.Status.NoError
    assert old.read_bytes() == original
    assert SettingsStore().value('library_root') == 'old-library'
    assert SettingsStore().value('appearance') == 'dark'
