"""Unified maintenance repairs failures and never deletes referenced or live slots."""
import json
import subprocess
from contextlib import nullcontext

import pytest

from linguaflow import runtime_install as runtime


def slot(base, name, previous=None):
    directory = base / name
    directory.mkdir(parents=True)
    (directory / 'environment.json').write_text(json.dumps({'slot': name, 'previous': previous}))
    return directory


def test_cleanup_keeps_active_rollback_live_custom_and_symlink(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'runtime_root', lambda: tmp_path)
    base = tmp_path / 'python' / 'wlk'
    previous = slot(base, 'a' * 32)
    active = slot(base, 'b' * 32, previous.name)
    (base / 'active.json').write_text((active / 'environment.json').read_text())
    unused = slot(base, 'c' * 32)
    live = slot(base, 'd' * 32)
    failed = base / ('e' * 32)
    failed.mkdir()
    custom = base / 'user-environment'
    custom.mkdir()
    external = tmp_path / 'models'
    external.mkdir()
    (external / 'weights').write_text('keep')
    link = base / ('f' * 32)
    link.symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(runtime, 'process_commands', lambda: str(live).casefold())
    assert runtime.clean_environments('wlk') == 2
    assert not unused.exists() and not failed.exists()
    assert all(path.exists() for path in (active, previous, live, custom, link, external / 'weights'))


@pytest.mark.parametrize('failure', ['pointer', 'empty', 'process'])
def test_cleanup_fails_closed(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(runtime, 'runtime_root', lambda: tmp_path)
    base = tmp_path / 'python' / 'mlx'
    active = slot(base, 'a' * 32)
    unused = slot(base, 'b' * 32)
    (base / 'active.json').write_text('{broken' if failure == 'pointer' else '{}' if failure == 'empty' else
                                    (active / 'environment.json').read_text())
    def unavailable():
        raise subprocess.TimeoutExpired('ps', 15)
    monkeypatch.setattr(runtime, 'process_commands', unavailable)
    assert runtime.clean_environments('mlx') == 0
    assert active.exists() and unused.exists()


@pytest.mark.parametrize('target,kinds', [('macos-arm64', ['wlk', 'mlx']), ('windows-x64', ['wlk'])])
def test_maintenance_reuses_healthy_and_repairs_failed(monkeypatch, tmp_path, target, kinds):
    monkeypatch.setattr('sys.platform', 'darwin' if target == 'macos-arm64' else 'win32')
    monkeypatch.setattr(runtime, 'check_installation', lambda: target)
    monkeypatch.setattr(runtime, 'preparation_lock', lambda _: nullcontext())
    translation_checks = []
    monkeypatch.setattr('linguaflow.llama_install.ensure_runtime', translation_checks.append)
    monkeypatch.setattr(runtime, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(runtime, 'runtime_environment', lambda kind: tmp_path / kind)
    for kind in kinds:
        python = runtime.environment_python(tmp_path / kind)
        python.parent.mkdir(parents=True)
        python.touch()
    installs, checks, cleanups = [], [], []
    def check(command, **kwargs):
        checks.append(command[-1])
        if command[-1] == kinds[-1]:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(runtime, 'run_command', check)
    monkeypatch.setattr(runtime, 'install', installs.append)
    monkeypatch.setattr(runtime, 'clean_environments', lambda kind: cleanups.append(kind) or 0)
    runtime.maintain()
    assert checks == kinds and installs == [kinds[-1]] and cleanups == kinds
    assert translation_checks == (['metal'] if target == 'macos-arm64' else ['cuda'])


def test_failed_repair_never_cleans_previous_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'check_installation', lambda: 'macos-arm64')
    monkeypatch.setattr(runtime, 'runtime_environment', lambda kind: tmp_path / 'missing')
    def fail(kind):
        raise RuntimeError('installation cancelled')
    monkeypatch.setattr(runtime, 'install', fail)
    monkeypatch.setattr(runtime, 'clean_environments', lambda kind: pytest.fail('must not clean after failed repair'))
    with pytest.raises(RuntimeError, match='cancelled'):
        runtime.maintain()


@pytest.mark.parametrize('system,device', [('darwin', 'metal'), ('win32', 'cuda')])
@pytest.mark.parametrize('broken', [False, True])
def test_llama_runtime_is_reused_or_repaired_without_model_download(monkeypatch, tmp_path, system, device, broken):
    from linguaflow import llama_install
    monkeypatch.setattr('sys.platform', system)
    binary = tmp_path/'llama-server'
    binary.touch()
    monkeypatch.setattr(llama_install, 'llama_server', lambda _: binary)
    installs = []
    def check(*args, **kwargs):
        if broken:
            raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(llama_install, 'run_command', check)
    monkeypatch.setattr(llama_install, 'install', lambda *args: installs.append(args))
    monkeypatch.setattr(llama_install, 'prepare_weights', lambda _: pytest.fail('maintenance must not download weights'))
    llama_install.ensure_runtime(device)
    assert installs == ([(device, None)] if broken else [])


def test_whisper_selection_does_not_prepare_unneeded_mlx(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'check_installation', lambda: 'macos-arm64')
    monkeypatch.setattr(runtime, 'runtime_root', lambda: tmp_path)
    checks = []
    monkeypatch.setattr(runtime, 'ensure_runtime', checks.append)
    monkeypatch.setattr(runtime, 'clean_environments', lambda _: 0)
    runtime.maintain(dict(backend='wlk-whisper', translation_engine='pytorch', translation_device='cpu'))
    assert checks == ['wlk']


@pytest.mark.parametrize('system,device', [('darwin', 'metal'), ('win32', 'cuda')])
@pytest.mark.parametrize('fails', [False, True])
def test_llama_repair_publishes_only_a_startable_binary(monkeypatch, tmp_path, system, device, fails):
    import hashlib
    import zipfile

    from linguaflow import llama_install
    monkeypatch.setattr('sys.platform', system)
    archive = tmp_path/'fixture.zip'
    name = 'llama-server.exe' if system == 'win32' else 'llama-server'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr(name, 'fixture executable')
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    target = 'macos-arm64' if system == 'darwin' else 'windows-x64'
    component = 'llama-b11254-' + (target+'-'+device if system == 'win32' else target)
    base = tmp_path/'components'/component
    base.mkdir(parents=True)
    pointer = base/'active.json'
    pointer.write_text('{"slot":"old"}')
    monkeypatch.setattr(llama_install, 'check_installation', lambda: target)
    monkeypatch.setattr(llama_install, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(llama_install, 'cache_root', lambda: tmp_path)
    monkeypatch.setattr(llama_install, 'preparation_lock', lambda _: nullcontext())
    monkeypatch.setattr('linguaflow.llama_assets.runtime_archives', lambda _: [(archive.name, checksum)])
    def check(command, **kwargs):
        assert command[-1] == '--version'
        if fails:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(llama_install, 'run_command', check)
    monkeypatch.setattr(llama_install, 'prepare_weights', lambda _: pytest.fail('runtime repair must preserve weights'))
    if fails:
        with pytest.raises(subprocess.CalledProcessError):
            llama_install.install(device, None)
        assert json.loads(pointer.read_text()) == {'slot':'old'}
    else:
        llama_install.install(device, None)
        new = json.loads(pointer.read_text())['slot']
        assert new != 'old' and (base/new/name).is_file()


@pytest.mark.parametrize('only,engine,expected', [
    ('asr', 'llama', ['wlk', 'mlx']),
    ('translation', 'llama', ['llama']),
    ('translation', 'pytorch', ['wlk']),
])
def test_single_role_maintenance_does_not_touch_unrelated_components(monkeypatch, tmp_path, only, engine, expected):
    monkeypatch.setattr('sys.platform', 'darwin')
    monkeypatch.setattr(runtime, 'check_installation', lambda: 'macos-arm64')
    monkeypatch.setattr(runtime, 'preparation_lock', lambda _: nullcontext())
    monkeypatch.setattr(runtime, 'runtime_root', lambda: tmp_path)
    calls = []
    monkeypatch.setattr(runtime, 'ensure_runtime', calls.append)
    monkeypatch.setattr(runtime, 'clean_environments', lambda _: 0)
    monkeypatch.setattr('linguaflow.llama_install.ensure_runtime', lambda _: calls.append('llama'))
    # Invalid inactive values must not prevent preparing the other role.
    selection = dict(backend='qwen3-mlx' if only == 'asr' else 'inactive-engine',
                     translation_engine=engine,
                     translation_device='inactive-device' if only == 'asr' else 'metal' if engine == 'llama' else 'cpu')
    runtime.maintain(selection, only=only)
    assert calls == expected
