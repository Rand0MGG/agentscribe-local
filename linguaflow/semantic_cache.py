"""Prepared, machine-specific SaT CPU graphs; never convert during listening."""
import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
from pathlib import Path


def _identity(model, version):
    files = {}
    for name in ('model_optimized.onnx', 'config.json'):
        path = (Path(model) / name).resolve()
        stat = path.stat()
        files[name] = [str(path), stat.st_size, stat.st_mtime_ns]
    return dict(format=1, runtime=version, machine=platform.machine(), source=files)


def _directory(model, version):
    # CPU mmap loading is available in the verified Windows 1.29 / Mac 1.30
    # runtimes. Cache format/runtime/architecture checks are shared, not OS gates.
    match = re.match(r'(\d+)\.(\d+)\.(\d+)', version)
    if not match or tuple(map(int, match.groups())) < (1, 29, 0):
        return None
    identity = _identity(model, version)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    return Path(__file__).resolve().parents[1] / '.work' / 'cache' / 'sat-ort' / key


def cached_cpu_model(model, version):
    """Return a complete compatible graph, or None; no model imports or writes."""
    directory = _directory(model, version)
    if directory is None:
        return None
    try:
        metadata = json.loads((directory / 'cache.json').read_text(encoding='utf-8'))
        if (metadata['identity'] == _identity(model, version)
                and metadata['bytes'] > 0
                and (directory / 'model_optimized.onnx').stat().st_size == metadata['bytes']
                and (directory / 'config.json').read_bytes() == (Path(model) / 'config.json').read_bytes()):
            return directory
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def prepare_cpu_model(model, ort, force=False):
    """Prepare local weights; force repairs caches that fail actual ORT loading."""
    directory = _directory(model, ort.__version__)
    if directory is None:
        return None
    cached = cached_cpu_model(model, ort.__version__)
    if cached is not None and not force:
        return cached
    directory.parent.mkdir(parents=True, exist_ok=True)
    identity = _identity(model, ort.__version__)
    with tempfile.TemporaryDirectory(prefix='prepare-', dir=directory.parent) as temporary:
        staged = Path(temporary)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        # wtpsplit requires this filename even though the payload is ORT format.
        options.optimized_model_filepath = str(staged / 'model_optimized.onnx')
        options.add_session_config_entry('session.save_model_format', 'ORT')
        session = ort.InferenceSession(str(Path(model) / 'model_optimized.onnx'),
                                       providers=['CPUExecutionProvider'], sess_options=options)
        if 'CPUExecutionProvider' not in session.get_providers():
            raise RuntimeError('SaT CPU 优化缓存未成功初始化。')
        del session
        shutil.copyfile(Path(model) / 'config.json', staged / 'config.json')
        if _identity(model, ort.__version__) != identity:
            raise RuntimeError('SaT 权重在准备缓存时改变，请重新准备分句模型。')
        metadata = dict(identity=identity,
                        bytes=(staged / 'model_optimized.onnx').stat().st_size)
        (staged / 'cache.json').write_text(json.dumps(metadata), encoding='utf-8')
        directory.mkdir(exist_ok=True)
        # Replace complete files, never mutate a graph mapped by a live session.
        # Publish the completeness marker last; failed conversion is not usable.
        for name in ('model_optimized.onnx', 'config.json', 'cache.json'):
            os.replace(staged / name, directory / name)
    return directory
