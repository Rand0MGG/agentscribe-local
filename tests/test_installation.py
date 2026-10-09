"""Installation/update prerequisites, without downloads, models or audio."""
import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile
from contextlib import nullcontext
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from linguaflow import hardware, runtime_install, runtime_paths
from linguaflow.library_startup import open_library


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    root, data = tmp_path / '只读 程序', tmp_path / '用户 数据'
    root.mkdir()
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: root)
    monkeypatch.setattr(runtime_paths, 'user_data_root', lambda: data)
    monkeypatch.setattr(runtime_paths, 'packaged', lambda: True)
    return root, data


@pytest.mark.parametrize('system,machine,allowed', [
    ('darwin', 'arm64', True), ('darwin', 'x86_64', False),
    ('win32', 'AMD64', True), ('win32', 'ARM64', False), ('linux', 'x86_64', False),
])
def test_platform_eligibility(monkeypatch, system, machine, allowed):
    monkeypatch.setattr(sys, 'platform', system)
    monkeypatch.setattr(hardware.platform, 'machine', lambda: machine)
    if allowed:
        assert hardware.platform_target() in ('windows-x64', 'macos-arm64')
    else:
        with pytest.raises(ValueError, match='不允许安装'):
            hardware.platform_target()


@pytest.mark.parametrize('output,compatible', [
    ('RTX 3060, 8.6, 570.65\n', True), ('RTX 3060, 8.6, 569.99\n', False),
    ('GTX 1080, 6.1, 590.00\n', False), ('V100, 7.0, 590.00\n', False),
    ('GTX 1080, 6.1, 590.00\nRTX 4090, 8.9, 590.00\n', True), ('', False),
])
def test_gpu_driver_and_architecture_match_pinned_torch(monkeypatch, output, compatible):
    monkeypatch.setattr(hardware, 'platform_target', lambda: 'windows-x64')
    monkeypatch.setattr(hardware, 'spawn_options', lambda: {})
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=output))
    if compatible:
        assert hardware.check_installation() == 'windows-x64'
    else:
        with pytest.raises(ValueError, match='不会回退 CPU'):
            hardware.check_installation()


def test_missing_gpu_detection_fails_closed(monkeypatch):
    monkeypatch.setattr(hardware, 'platform_target', lambda: 'windows-x64')
    monkeypatch.setattr(hardware, 'spawn_options', lambda: {})
    def missing(*args, **kwargs):
        raise FileNotFoundError('nvidia-smi')
    monkeypatch.setattr(subprocess, 'run', missing)
    with pytest.raises(ValueError, match='不会安装 CPU'):
        hardware.check_installation()


def test_hardware_rejection_precedes_all_writes(tmp_path, monkeypatch):
    def reject():
        raise ValueError('hardware rejected')
    monkeypatch.setattr(runtime_install, 'check_installation', reject)
    monkeypatch.setattr(runtime_install, 'runtime_root', lambda: tmp_path / 'runtime')
    with pytest.raises(ValueError, match='hardware rejected'):
        runtime_install.install('wlk')
    assert list(tmp_path.iterdir()) == []


def test_packaged_paths_survive_installation_replacement(isolated_paths):
    root, data = isolated_paths
    recording = runtime_paths.recordings_root() / '课一' / '录音.wav'
    recording.parent.mkdir(parents=True)
    recording.write_bytes(b'personal recording')
    model = runtime_paths.model_directory('example') / 'weights'
    model.parent.mkdir(parents=True)
    model.write_bytes(b'personal model')
    assert runtime_paths.runtime_root() == data / 'runtime'
    assert runtime_paths.cache_root() == data / 'cache'
    root.rmdir()  # The app directory can be removed without touching data.
    assert recording.read_bytes() == b'personal recording'
    assert model.read_bytes() == b'personal model'


def test_frozen_app_is_never_used_as_python(isolated_paths):
    root, _ = isolated_paths
    with pytest.raises(RuntimeError, match='缺少桌面 Python'):
        runtime_paths.knowledge_python()
    python = root / 'python' / ('python.exe' if sys.platform == 'win32' else 'bin/python3')
    python.parent.mkdir(parents=True)
    python.write_bytes(b'bundled interpreter')
    command = runtime_paths.installation_command('linguaflow.model_prepare', 'qwen', 'a/b')
    assert command[0] == str(python) and command[0] != sys.executable
    environment = runtime_paths.python_environment()
    assert environment['AGENTSCRIBE_PACKAGED'] == '1'
    assert environment['AGENTSCRIBE_RESOURCES'] == str(root)


@pytest.mark.parametrize('slot', ['../../escape', '', 'A' * 32, None])
def test_runtime_pointer_rejects_invalid_paths(isolated_paths, slot):
    _, data = isolated_paths
    base = data / 'runtime/python/wlk'
    base.mkdir(parents=True)
    (base / 'active.json').write_text(json.dumps({'slot': slot}))
    with pytest.raises(RuntimeError, match='记录损坏'):
        runtime_paths.runtime_python()


def test_runtime_requires_matching_app_dependencies(isolated_paths, monkeypatch):
    root, data = isolated_paths
    (root / 'requirements-runtime.txt').write_text('fixed==2')
    base = data / 'runtime/python/wlk'
    python = runtime_paths.environment_python(base / ('a' * 32))
    python.parent.mkdir(parents=True)
    python.write_bytes(b'python')
    pointer = {'slot': 'a' * 32, 'requirements': 'fixed==1', 'platform': 'windows-x64', 'torch_version': '2.11.0'}
    (base / 'active.json').write_text(json.dumps(pointer))
    with pytest.raises(RuntimeError, match='不匹配'):
        runtime_paths.runtime_python()
    pointer['requirements'] = 'fixed==2'
    pointer['platform'] = hardware.platform_target()
    (base / 'active.json').write_text(json.dumps(pointer))
    assert runtime_paths.runtime_python() == python


@pytest.mark.parametrize('fail_at', ['pip', 'verify', 'publish', None])
def test_environment_failure_preserves_active_and_recordings(tmp_path, monkeypatch, fail_at):
    source, base = tmp_path / 'source', tmp_path / 'runtime'
    source.mkdir()
    (source / 'requirements-runtime.txt').write_text('fixed==1')
    active = base / 'python/wlk/active.json'
    active.parent.mkdir(parents=True)
    original = json.dumps({'slot': 'a' * 32})
    active.write_text(original)
    recording = tmp_path / '录音.wav'
    recording.write_bytes(b'preserve')
    monkeypatch.setattr(runtime_install, 'check_installation', lambda: 'windows-x64')
    monkeypatch.setattr(runtime_install, 'resource_root', lambda: source)
    monkeypatch.setattr(runtime_install, 'runtime_root', lambda: base)
    monkeypatch.setattr(runtime_install, 'cache_root', lambda: tmp_path / 'cache')
    monkeypatch.setattr(runtime_install, 'preparation_lock', lambda _: nullcontext())
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if 'venv' in command:
            python = runtime_paths.environment_python(command[-1])
            python.parent.mkdir(parents=True)
            python.write_bytes(b'python')
        if (fail_at == 'pip' and 'pip' in command) or (fail_at == 'verify' and '--verify' in command):
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(runtime_install, 'run_command', run)
    if fail_at == 'publish':
        monkeypatch.setattr(runtime_install, 'publish', lambda *args: (_ for _ in ()).throw(PermissionError('disk')))
    if fail_at:
        with pytest.raises((subprocess.CalledProcessError, PermissionError)):
            runtime_install.install('wlk')
        assert active.read_text() == original
    else:
        runtime_install.install('wlk')
        value = json.loads(active.read_text())
        assert value['previous'] == 'a' * 32
        python = runtime_paths.environment_python(active.parent / value['slot'])
        assert python.is_file()
        assert calls[0][-1] == str(python.parent.parent)  # No rename after creating venv.
        assert any('--verify' in command for command in calls)
    assert recording.read_bytes() == b'preserve'


def test_new_library_default_and_existing_location_are_preserved(isolated_paths):
    root, data = isolated_paths
    saved = {}
    store = SimpleNamespace(value=lambda key: saved.get(key), setValue=saved.__setitem__)
    def no_prompt(*args):
        pytest.fail('must open without a prompt')
    paths = []
    def factory(path):
        paths.append(Path(path))
        return SimpleNamespace()
    kwargs = dict(choose_directory=no_prompt, migration_failed=no_prompt, factory=factory)
    open_library(store, root, **kwargs)
    assert paths[-1] == data / '录音'
    legacy = root / '录音'
    legacy.mkdir()
    (legacy / 'original.wav').write_bytes(b'keep')
    open_library(store, root, **kwargs)
    assert paths[-1] == legacy and saved['library_directory'] == str(legacy)
    custom = data / 'custom'
    saved['library_directory'] = str(custom)
    open_library(store, root, **kwargs)
    assert paths[-1] == custom
    assert (legacy / 'original.wav').read_bytes() == b'keep'


def test_atomic_pointer_write_error_preserves_old(tmp_path, monkeypatch):
    pointer = tmp_path / 'active.json'
    pointer.write_text('{"slot":"old"}')
    monkeypatch.setattr(Path, 'replace', lambda *args: (_ for _ in ()).throw(PermissionError('locked')))
    with pytest.raises(PermissionError):
        runtime_install.publish(pointer, {'slot': 'new'})
    assert pointer.read_text() == '{"slot":"old"}'
    assert list(tmp_path.iterdir()) == [pointer]


def test_cancel_preparation_reaps_download_and_descendants(tmp_path):
    from linguaflow.management import ModelManager
    saved = tmp_path / '已下载部分.bin'
    code = '''
import subprocess, sys, time
from pathlib import Path
Path(sys.argv[1]).write_bytes(b'partial-download')
subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
print('fixture child ready', flush=True)
time.sleep(30)
'''
    logs, errors = [], []
    worker = SimpleNamespace(cancelled=False, process=None, progress=SimpleNamespace(emit=logs.append))
    manager = SimpleNamespace(worker=worker)
    def run():
        try:
            ModelManager.run_preparation(manager, [sys.executable, '-u', '-c', code, str(saved)])
        except RuntimeError as exc:
            errors.append(str(exc))
    thread = Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 6
    try:
        while 'fixture child ready' not in logs and time.monotonic() < deadline:
            time.sleep(.02)
        assert 'fixture child ready' in logs
        worker.cancelled = True
        thread.join(12)
        # A surviving grandchild holds stdout open, preventing the reader/worker
        # from completing. This verifies the whole owned tree, not only a flag.
        assert not thread.is_alive()
        assert errors and '已取消' in errors[0]
        assert worker.process is None and saved.read_bytes() == b'partial-download'
    finally:
        worker.cancelled = True
        if worker.process is not None:
            worker.process.stdin.close()
        thread.join(12)


def test_source_preparation_preserves_code_and_licenses_without_experiments(tmp_path):
    revision = 'a' * 40
    directory = tmp_path / 'cache'
    directory.mkdir()
    archive = directory / (revision + '.zip')
    files = {'upstream/src/model.py': b'original source', 'upstream/pyproject.toml': b'version=1',
             'upstream/README.md': b'readme', 'upstream/LICENSE': b'license',
             'upstream/experiments/' + 'long-' * 60 + '.json': b'unnecessary output'}
    with zipfile.ZipFile(archive, 'w') as output:
        for name, data in files.items():
            output.writestr(name, data)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    requirements = tmp_path / 'original.txt'
    requirements.write_text(f'qwen3-asr-causal[streaming] @ https://github.com/example/archive/{revision}.zip#sha256={digest}\nfixed==1\n')
    result = runtime_install.prepare_sources(requirements, directory)
    assert 'fixed==1' in result.read_text()
    assert requirements.read_text().startswith('qwen3-asr-causal')
    with zipfile.ZipFile(directory / ('qwen3-asr-causal-' + revision + '.zip')) as prepared:
        assert all('/experiments/' not in name for name in prepared.namelist())
        for name, data in files.items():
            if '/experiments/' not in name:
                assert prepared.read(name) == data


def test_source_checksum_failure_does_not_publish(tmp_path, monkeypatch):
    revision = 'b' * 40
    requirements = tmp_path / 'original.txt'
    requirements.write_text(f'whisperlivekit @ https://github.com/example/{revision}.zip#sha256=' + '0' * 64)
    monkeypatch.setattr(runtime_install.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(b'corrupt download'))
    directory = tmp_path / 'cache'
    with pytest.raises(ValueError, match='SHA256 校验失败'):
        runtime_install.prepare_sources(requirements, directory)
    assert list(directory.iterdir()) == []
