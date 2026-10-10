"""Both platforms use the same orchestration and retain required-asset failures."""
import pytest

from linguaflow import recommended_prepare as worker
from linguaflow import runtime_install  # Import OS libraries before platform simulation.
from linguaflow.model_options import recommended_selection


@pytest.mark.parametrize('system', ['darwin', 'win32'])
@pytest.mark.parametrize('cached', [False, True])
def test_preparation_reuses_models_and_keeps_segmentation(monkeypatch, tmp_path, system, cached):
    monkeypatch.setattr('sys.platform', system)
    selection = recommended_selection()
    # Exercise both shared Qwen adapters with a custom selection, not only defaults.
    selection.update(backend='qwen3-mlx' if system == 'darwin' else 'qwen3-streaming',
                     asr_model='fixture', translation_engine='llama', translation_model='fixture.gguf')
    calls = []
    monkeypatch.setattr(runtime_install, 'maintain', lambda value: calls.append(('runtime', value.copy())))
    monkeypatch.setattr(worker, 'runtime_python', lambda: tmp_path/'python')
    def resolve(_):
        if not cached and not any(c[0] == 'qwen' for c in calls):
            raise ValueError('missing weights')
        return 'fixture'
    monkeypatch.setattr(worker, 'resolve_asr', resolve)
    monkeypatch.setattr('linguaflow.model_prepare.prepare', lambda kind, model: calls.append((kind, model)))
    monkeypatch.setattr('linguaflow.runtime_install.run_command', lambda command, **kwargs: calls.append(('command', command)))
    monkeypatch.setattr('linguaflow.llama_install.prepare_weights', lambda model: calls.append(('translation', model)))
    worker.main(selection)
    assert calls[0] == ('runtime', selection)
    assert ('qwen', 'fixture') in calls if not cached else ('qwen', 'fixture') not in calls
    assert any(c[0] == 'command' and c[1][-1] == 'linguaflow.semantic_model' for c in calls)
    assert calls[-1] == ('translation', 'fixture.gguf')


def test_windows_whisper_and_pytorch_use_shared_preparation(monkeypatch, tmp_path):
    monkeypatch.setattr('sys.platform', 'win32')
    selection = recommended_selection()
    selection.update(backend='wlk-whisper', asr_model='tiny', translation_engine='pytorch',
                     translation_model='tencent/Hy-MT2-1.8B')
    monkeypatch.setattr('linguaflow.runtime_install.maintain', lambda _: None)
    monkeypatch.setattr(worker, 'runtime_python', lambda: tmp_path/'python')
    calls = []
    monkeypatch.setattr('linguaflow.runtime_install.run_command', lambda command, **kwargs: calls.append(command))
    monkeypatch.setattr('linguaflow.model_prepare.prepare', lambda kind, model: calls.append((kind, model)))
    worker.main(selection)
    assert calls[0][-3:] == ['linguaflow.wlk_prepare', 'whisper', 'tiny']
    assert calls[1][-1] == 'linguaflow.semantic_model'
    assert calls[2] == ('translation', selection['translation_model'])


def test_segmentation_failure_stops_translation_and_success(monkeypatch):
    monkeypatch.setattr('linguaflow.runtime_install.maintain', lambda _: None)
    monkeypatch.setattr(worker, 'resolve_asr', lambda _: 'fixture')
    def fail(*args, **kwargs):
        raise RuntimeError('required segmentation failed')
    monkeypatch.setattr('linguaflow.runtime_install.run_command', fail)
    monkeypatch.setattr('linguaflow.llama_install.prepare_weights', lambda _: pytest.fail('must not proceed'))
    with pytest.raises(RuntimeError, match='segmentation'):
        worker.main(dict(backend='qwen3-streaming', asr_model='fixture', translation_engine='llama'))


def test_incompatible_backend_fails_before_installing(monkeypatch):
    monkeypatch.setattr('sys.platform', 'win32')
    monkeypatch.setattr('linguaflow.runtime_install.check_installation', lambda: 'windows-x64')
    monkeypatch.setattr('linguaflow.runtime_install.install', lambda _: pytest.fail('must validate first'))
    with pytest.raises(ValueError, match='识别引擎'):
        worker.main(recommended_selection('darwin'))


@pytest.mark.parametrize('only', ['asr', 'translation'])
def test_single_role_preparation_propagates_scope_and_skips_other_weights(monkeypatch, tmp_path, only):
    calls = []
    monkeypatch.setattr('linguaflow.runtime_install.maintain',
                        lambda selection, **kwargs: calls.append(('maintain', kwargs)))
    monkeypatch.setattr(worker, 'runtime_python', lambda: tmp_path/'python')
    monkeypatch.setattr(worker, 'resolve_asr', lambda _: calls.append(('asr', {})))
    monkeypatch.setattr('linguaflow.runtime_install.run_command', lambda *args, **kwargs: None)
    monkeypatch.setattr('linguaflow.llama_install.prepare_weights', lambda _: calls.append(('translation', {})))
    worker.main(dict(backend='qwen3-streaming', asr_model='fixture',
                     translation_engine='llama', translation_model='fixture.gguf'), only=only)
    assert calls == [('maintain', {'only': only}), (only, {})]


def test_asr_only_asset_check_does_not_require_translation(monkeypatch, tmp_path):
    python = tmp_path / 'python'
    python.touch()
    monkeypatch.setattr(worker, 'environment_python', lambda _: python)
    monkeypatch.setattr(worker, 'resolve_asr', lambda _: tmp_path)
    monkeypatch.setattr('linguaflow.semantic_model.paths', lambda **kwargs: (tmp_path, tmp_path))
    calls = []
    def translation(*args):
        calls.append('translation')
        raise ValueError('missing translation')
    monkeypatch.setattr(worker, 'resolve_translation', translation)
    selection = dict(backend='qwen3-streaming', asr_model='fixture',
                     translation_engine='pytorch', translation_model='missing')
    assert worker.missing_assets(selection, only='asr') == []
    assert calls == []
    assert worker.missing_assets(selection) == ['翻译模型：missing']
    assert calls == ['translation']
