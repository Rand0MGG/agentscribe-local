import json
import sys
from types import SimpleNamespace

from linguaflow import model_cache
from linguaflow.translation_models import HY_MODEL


def test_hy_incomplete_template_triggers_download_including_jinja(tmp_path, monkeypatch):
    monkeypatch.setattr(model_cache, '__file__', str(tmp_path / 'linguaflow' / 'model_cache.py'))
    cache = tmp_path / 'cached'
    cache.mkdir()
    (cache / 'model.safetensors').touch()
    (cache / 'tokenizer_config.json').write_text('{}')
    downloads = []

    def snapshot(model, **kwargs):
        if not kwargs.get('local_files_only'):
            downloads.append(kwargs)
        return str(cache)

    hub = SimpleNamespace(snapshot_download=snapshot,
                          HfApi=lambda: SimpleNamespace(list_repo_files=lambda _: ['model.safetensors']))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', hub)
    assert model_cache.resolve_translation(HY_MODEL, lambda _: None) == str(cache)
    assert '*.jinja' in downloads[0]['allow_patterns']
    (cache / 'chat_template.jinja').write_text('template')
    downloads.clear()
    model_cache.resolve_translation(HY_MODEL, lambda _: None)
    assert not downloads


def test_builtin_hy_choice_reuses_complete_project_local_package(tmp_path, monkeypatch):
    monkeypatch.setattr(model_cache, '__file__', str(tmp_path / 'linguaflow' / 'model_cache.py'))
    bundle = tmp_path / 'models' / 'Hy-MT2-1.8B'
    bundle.mkdir(parents=True)
    for name in ('model.safetensors', 'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja'):
        (bundle / name).touch()
    (bundle / 'config.json').write_text(json.dumps({'model_type': 'hunyuan_v1_dense'}))

    def unexpected(*args, **kwargs):
        raise AssertionError('Local package must never request another download')

    monkeypatch.setitem(sys.modules, 'huggingface_hub',
                        SimpleNamespace(snapshot_download=unexpected, HfApi=unexpected))
    assert model_cache.resolve_translation(HY_MODEL, lambda _: None) == str(bundle)
