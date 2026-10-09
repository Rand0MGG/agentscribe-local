import json
import sys
from types import SimpleNamespace

from linguaflow import model_cache
from linguaflow.translation_models import HY_MODEL


def test_hy_incomplete_template_triggers_download_including_jinja(tmp_path, monkeypatch):
    monkeypatch.setattr(model_cache, 'model_directory', lambda name: tmp_path / 'models' / name)
    cache = tmp_path / 'cached'
    cache.mkdir()
    (cache / 'model.safetensors').write_bytes(b'weights')
    (cache / 'config.json').write_text('{}')
    (cache / 'tokenizer_config.json').write_text('{}')
    downloads = []

    def snapshot(model, **kwargs):
        if not kwargs.get('local_files_only'):
            downloads.append(kwargs)
            (cache / 'chat_template.jinja').write_text('downloaded template')
        return str(cache)

    hub = SimpleNamespace(snapshot_download=snapshot,
                          HfApi=lambda: SimpleNamespace(list_repo_files=lambda _: ['model.safetensors']))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', hub)
    assert model_cache.resolve_translation(HY_MODEL, lambda _: None, allow_download=True) == str(cache)
    assert '*.jinja' in downloads[0]['allow_patterns']
    (cache / 'chat_template.jinja').write_text('template')
    downloads.clear()
    model_cache.resolve_translation(HY_MODEL, lambda _: None)
    assert not downloads


def test_builtin_hy_choice_reuses_complete_project_local_package(tmp_path, monkeypatch):
    monkeypatch.setattr(model_cache, 'model_directory', lambda name: tmp_path / 'models' / name)
    bundle = tmp_path / 'models' / 'Hy-MT2-1.8B'
    bundle.mkdir(parents=True)
    for name in ('model.safetensors', 'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja'):
        (bundle / name).write_bytes(b'fixture')
    (bundle / 'config.json').write_text(json.dumps({'model_type': 'hunyuan_v1_dense'}))

    def unexpected(*args, **kwargs):
        raise AssertionError('Local package must never request another download')

    monkeypatch.setitem(sys.modules, 'huggingface_hub',
                        SimpleNamespace(snapshot_download=unexpected, HfApi=unexpected))
    assert model_cache.resolve_translation(HY_MODEL, lambda _: None) == str(bundle)
