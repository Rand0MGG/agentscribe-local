import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import linguaflow.semantic_cache as cache


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.sys, 'platform', 'darwin')
    monkeypatch.setattr(cache.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(cache, '__file__', str(tmp_path / 'linguaflow' / 'semantic_cache.py'))
    model = tmp_path / 'source'
    model.mkdir()
    (model / 'model_optimized.onnx').write_bytes(b'original weights')
    (model / 'config.json').write_text('{}')
    return model


def runtime(load=None):
    class Options:
        def add_session_config_entry(self, key, value):
            assert (key, value) == ('session.save_model_format', 'ORT')
    def create(path, providers, sess_options):
        assert providers == ['CPUExecutionProvider']
        assert Path(path).read_bytes() == b'original weights'
        assert (sess_options.intra_op_num_threads, sess_options.inter_op_num_threads) == (2, 1)
        if load:
            load(path)
        Path(sess_options.optimized_model_filepath).write_bytes(b'prepared ORT weights')
        return SimpleNamespace(get_providers=lambda: providers)
    return SimpleNamespace(__version__='1.30.0', SessionOptions=Options, InferenceSession=create)


def test_preparation_preserves_original_and_reuses_complete_graph(source):
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    directory = cache.prepare_cpu_model(source, runtime())
    assert cache.cached_cpu_model(source, '1.30.0') == directory
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original
    assert cache.prepare_cpu_model(source, runtime(lambda _: pytest.fail('must reuse'))) == directory
    assert cache.cached_cpu_model(source, '1.30.1') is None
    (source / 'config.json').write_text('{"changed": true}')
    assert cache.cached_cpu_model(source, '1.30.0') is None


@pytest.mark.parametrize('damage', ['truncated', 'marker', 'config', 'missing'])
def test_incomplete_cache_is_ignored_and_repaired(source, damage):
    directory = cache.prepare_cpu_model(source, runtime())
    if damage == 'truncated':
        (directory / 'model_optimized.onnx').write_bytes(b'bad')
    elif damage == 'marker':
        (directory / 'cache.json').write_text('[]')
    elif damage == 'config':
        (directory / 'config.json').write_text('{"wrong": true}')
    else:
        (directory / 'model_optimized.onnx').unlink()
    assert cache.cached_cpu_model(source, '1.30.0') is None
    assert cache.prepare_cpu_model(source, runtime()) == directory
    assert cache.cached_cpu_model(source, '1.30.0') == directory


def test_conversion_failure_does_not_publish_or_modify_source(source):
    def fail(_):
        raise OSError('disk full')
    with pytest.raises(OSError, match='disk full'):
        cache.prepare_cpu_model(source, runtime(fail))
    assert cache.cached_cpu_model(source, '1.30.0') is None
    assert (source / 'model_optimized.onnx').read_bytes() == b'original weights'
    assert not list((source.parent / '.work/cache/sat-ort').glob('prepare-*'))


def test_explicit_preparation_repairs_same_size_corruption(source):
    directory = cache.prepare_cpu_model(source, runtime())
    path = directory / 'model_optimized.onnx'
    original = path.read_bytes()
    path.write_bytes(b'x' * len(original))
    assert cache.cached_cpu_model(source, '1.30.0') == directory
    assert cache.prepare_cpu_model(source, runtime(), force=True) == directory
    assert path.read_bytes() == original


def test_changed_weights_during_preparation_are_not_published(source):
    def change(path):
        Path(path).write_bytes(b'new weights')
    with pytest.raises(RuntimeError, match='改变'):
        cache.prepare_cpu_model(source, runtime(change))
    assert cache.cached_cpu_model(source, '1.30.0') is None


def test_interrupted_publish_leaves_no_complete_cache(source, monkeypatch):
    replace = cache.os.replace
    def interrupt(old, new):
        if Path(new).name == 'config.json':
            raise OSError('publish interrupted')
        replace(old, new)
    monkeypatch.setattr(cache.os, 'replace', interrupt)
    with pytest.raises(OSError, match='publish interrupted'):
        cache.prepare_cpu_model(source, runtime())
    assert cache.cached_cpu_model(source, '1.30.0') is None
    assert not list((source.parent / '.work/cache/sat-ort').glob('prepare-*'))


@pytest.mark.parametrize(('system', 'version'), [('win32', '1.30.0'), ('linux', '1.30.0'),
                                             ('darwin', '1.29.0'), ('darwin', 'unknown')])
def test_other_platforms_and_old_runtimes_do_not_read_or_prepare(tmp_path, monkeypatch, system, version):
    monkeypatch.setattr(cache.sys, 'platform', system)
    model = tmp_path / 'missing'
    assert cache.cached_cpu_model(model, version) is None
    ort = SimpleNamespace(__version__=version, SessionOptions=lambda: pytest.fail('must not load'))
    assert cache.prepare_cpu_model(model, ort) is None
    assert not model.exists()


def test_cache_is_specific_to_machine(source, monkeypatch):
    directory = cache.prepare_cpu_model(source, runtime())
    assert json.loads((directory / 'cache.json').read_text())['identity']['machine'] == 'arm64'
    monkeypatch.setattr(cache.platform, 'machine', lambda: 'x86_64')
    assert cache.cached_cpu_model(source, '1.30.0') is None


@pytest.mark.parametrize('prepared', [False, True])
def test_semantic_adapter_maps_only_prepared_graphs(source, monkeypatch, prepared):
    import linguaflow.semantic_model as semantic
    selected = cache.prepare_cpu_model(source, runtime()) if prepared else source
    monkeypatch.setattr(semantic, 'paths', lambda: (str(source), 'local-tokenizer'))
    entries = {}
    class Options:
        def add_session_config_entry(self, key, value):
            entries[key] = value
    def sat(model, tokenizer_name_or_path, ort_providers, ort_kwargs, from_pretrained_kwargs):
        assert Path(model) == selected
        assert tokenizer_name_or_path == 'local-tokenizer'
        assert ort_providers == ['CPUExecutionProvider']
        assert from_pretrained_kwargs == {'local_files_only': True}
        return SimpleNamespace(model=SimpleNamespace(ort_session=SimpleNamespace(
            get_providers=lambda: ort_providers)))
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(__version__='1.30.0', SessionOptions=Options))
    monkeypatch.setitem(sys.modules, 'wtpsplit', SimpleNamespace(SaT=sat))
    semantic.SemanticModel('cpu')
    assert entries == ({'session.load_model_format': 'ORT', 'session.use_memory_mapped_ort_model': '1',
                        'session.use_ort_model_bytes_for_initializers': '1'} if prepared else {})
