"""Bounded retention and preservation of modified, unknown and live runtime data."""
import json
import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest

from linguaflow import runtime_cleanup as cleanup
from linguaflow import runtime_install as runtime
from linguaflow import runtime_paths


def environment(base, number, previous=None, requirements='fixed==1'):
    slot = f'{number:032x}'
    directory = base / slot
    executable = runtime_paths.environment_python(directory)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'owned interpreter fixture')
    record = {'slot': slot, 'previous': previous, 'requirements': requirements}
    (directory / 'environment.json').write_text(json.dumps(record))
    cleanup.seal_slot(directory, 'python-' + base.name)
    return record


def history(tmp_path, monkeypatch, *, rollback=set()):
    monkeypatch.setattr(runtime, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(runtime, 'process_commands', lambda: 'unrelated fixture process')
    monkeypatch.setattr(runtime, 'retained_requirements', lambda _: rollback)
    base = tmp_path / 'python/wlk'
    values = []
    for number in range(1, 6):
        values.append(environment(base, number, values[-1]['slot'] if values else None,
                                  'fixed==' + str(number)))
    (base / 'active.json').write_text(json.dumps(values[-1]))
    return base, values


@pytest.mark.p0
def test_repeated_environments_retain_only_active_and_recent_rollback(tmp_path, monkeypatch):
    base, values = history(tmp_path, monkeypatch)
    recording = tmp_path / '录音/lecture.wav'
    recording.parent.mkdir()
    recording.write_bytes(b'user recording')
    assert runtime.clean_environments('wlk') == 3
    assert {path.name for path in base.iterdir() if path.is_dir()} == {values[-1]['slot'], values[-2]['slot']}
    assert json.loads((base / values[-2]['slot'] / 'environment.json').read_text())['previous'] is None
    assert runtime.clean_environments('wlk') == 0
    assert recording.read_bytes() == b'user recording'


@pytest.mark.p1
def test_saved_package_rollback_keeps_older_compatible_environment(tmp_path, monkeypatch):
    base, values = history(tmp_path, monkeypatch, rollback={'fixed==1'})
    assert runtime.clean_environments('wlk') == 2
    assert (base / values[0]['slot']).exists()
    record = json.loads((base / values[-2]['slot'] / 'environment.json').read_text())
    assert record['previous'] == values[0]['slot']
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: tmp_path)
    (tmp_path / 'requirements-runtime.txt').write_text('fixed==1')
    # Match production metadata without invoking any interpreter or audio.
    from linguaflow.hardware import TORCH_VERSION, platform_target
    for value in values:
        path = base / value['slot'] / 'environment.json'
        if path.exists():
            value = json.loads(path.read_text())
            value.update(platform=platform_target(), torch_version=TORCH_VERSION)
            path.write_text(json.dumps(value))
            if value['slot'] == values[-1]['slot']:
                (base / 'active.json').write_text(json.dumps(value))
    assert runtime_paths.active_directory(base, tmp_path / 'missing', python=True) == base / values[0]['slot']


@pytest.mark.p0
@pytest.mark.parametrize('change', ['extra-recording', 'modified', 'unknown', 'live', 'empty', 'inspection-failed'])
def test_environment_cleanup_preserves_user_changes_and_unconfirmed_ownership(tmp_path, monkeypatch, change):
    base, values = history(tmp_path, monkeypatch)
    protected = base / values[0]['slot']
    if change == 'extra-recording':
        (protected / 'lecture.wav').write_bytes(b'user data')
    elif change == 'modified':
        runtime_paths.environment_python(protected).write_bytes(b'user edited file')
    elif change == 'unknown':
        (protected / cleanup.MARKER).unlink()
    elif change == 'live':
        monkeypatch.setattr(runtime, 'process_commands', lambda: str(protected / 'bin/python'))
    elif change == 'empty':
        monkeypatch.setattr(runtime, 'process_commands', lambda: '')
    else:
        def fail():
            raise subprocess.TimeoutExpired('fixture-process-inspection', 15)
        monkeypatch.setattr(runtime, 'process_commands', fail)
    runtime.clean_environments('wlk')
    assert protected.exists()


@pytest.mark.p0
def test_environment_pointer_publication_failure_prevents_any_deletion(tmp_path, monkeypatch):
    base, values = history(tmp_path, monkeypatch)
    def fail(*args):
        raise OSError('fixture disk full')
    monkeypatch.setattr(runtime, 'publish', fail)
    assert runtime.clean_environments('wlk') == 0
    assert all((base / value['slot']).exists() for value in values)


def component(base, number):
    directory = base / f'{number:032x}'
    directory.mkdir(parents=True)
    (directory / 'runtime.bin').write_bytes(b'owned component')
    cleanup.seal_slot(directory, 'fixture')
    return directory


@pytest.mark.p0
@pytest.mark.parametrize('change', ['extra', 'modified', 'unknown', 'live', 'junction'])
def test_component_pruning_preserves_rollback_and_unowned_data(tmp_path, monkeypatch, change):
    base = tmp_path / 'components/fixture'
    slots = [component(base, index) for index in range(1, 5)]
    (base / 'active.json').write_text(json.dumps({'slot': slots[-1].name, 'previous': slots[-2].name}))
    commands = 'unrelated fixture process'
    if change == 'extra':
        (slots[0] / 'user.wav').write_bytes(b'user data')
    elif change == 'modified':
        (slots[0] / 'runtime.bin').write_bytes(b'user edited data')
    elif change == 'unknown':
        (slots[0] / cleanup.MARKER).unlink()
    elif change == 'live':
        commands = str(slots[0] / 'runtime.bin')
    else:
        monkeypatch.setattr(Path, 'is_junction', lambda path: path == slots[0], raising=False)
    monkeypatch.setattr(cleanup, 'process_commands', lambda: commands)
    assert cleanup.clean_component(base, 'fixture') == 1
    assert slots[0].exists() and not slots[1].exists()
    assert slots[-1].exists() and slots[-2].exists()


@pytest.mark.p0
def test_component_external_directory_link_preserves_target(tmp_path, monkeypatch):
    from filesystem_support import directory_symlink
    base = tmp_path / 'components/fixture'
    old, active = component(base, 1), component(base, 2)
    (base / 'active.json').write_text(json.dumps({'slot': active.name}))
    external = tmp_path / '录音'
    external.mkdir()
    (external / 'user.wav').write_bytes(b'user data')
    directory_symlink(old / 'link', external)
    monkeypatch.setattr(cleanup, 'process_commands', lambda: 'unrelated fixture process')
    assert cleanup.clean_component(base, 'fixture') == 0
    assert (external / 'user.wav').read_bytes() == b'user data' and old.exists()


@pytest.mark.p0
def test_changed_runtime_with_python_cache_preserves_added_data(tmp_path):
    directory = component(tmp_path, 1)
    (directory / '__pycache__').mkdir()
    (directory / '__pycache__/runtime.cpython-312.pyc').write_bytes(b'generated cache')
    assert cleanup.removable(directory, 'fixture', 'unrelated fixture process')
    (directory / '__pycache__/lecture.wav').write_bytes(b'user data')
    assert not cleanup.removable(directory, 'fixture', 'unrelated fixture process')


@pytest.mark.p0
def test_retained_package_requirements_and_mapping_fail_closed(tmp_path, monkeypatch):
    resources = tmp_path / 'installed/AgentScribe.app/Contents/Resources'
    resources.mkdir(parents=True)
    (resources / 'requirements-runtime.txt').write_text('fixed==current')
    monkeypatch.setattr(runtime_paths, 'packaged', lambda: True)
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: resources)
    backup = resources.parents[2] / ('.AgentScribe-previous-' + 'a' * 32)
    file = backup / 'Contents/Resources/requirements-runtime.txt'
    file.parent.mkdir(parents=True)
    file.write_text('fixed==old')
    assert cleanup.retained_requirements('wlk') == {'fixed==old', 'fixed==current'}
    monkeypatch.setattr(Path, 'is_junction', lambda path: path == backup, raising=False)
    assert cleanup.retained_requirements('wlk') is None


@pytest.mark.p2
@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_repeated_document_install_is_bounded_and_failure_preserves_current(tmp_path, monkeypatch, system):
    from linguaflow import document_install as installer
    monkeypatch.setattr('sys.platform', system)
    monkeypatch.setattr(installer, 'check_installation', lambda: system)
    monkeypatch.setattr(installer, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(installer, 'cache_root', lambda: tmp_path / 'cache')
    monkeypatch.setattr(installer, 'node_executable', lambda: tmp_path / 'node')
    monkeypatch.setattr(installer, 'npm_command', lambda _: ['fixture-npm'])
    monkeypatch.setattr(installer, 'preparation_lock', lambda _: nullcontext())
    monkeypatch.setattr('linguaflow.process_platform.spawn_options', lambda: {})
    monkeypatch.setattr(cleanup, 'process_commands', lambda: 'unrelated fixture process')
    monkeypatch.setattr(installer.subprocess, 'check_output',
                        lambda args, **kwargs: 'v22.23.0' if '--version' in args else '{}')
    def install(command, **kwargs):
        directory = Path(command[command.index('--prefix') + 1])
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'runtime.bin').write_bytes(b'owned runtime')
    monkeypatch.setattr(installer, 'run_command', install)
    for _ in range(5):
        installer.main()
    base = tmp_path / 'components/document-renderer'
    assert len([path for path in base.iterdir() if path.is_dir()]) == 2
    before = (base / 'active.json').read_bytes()
    def fail(*args, **kwargs):
        raise OSError('fixture install failed')
    monkeypatch.setattr(installer, 'run_command', fail)
    with pytest.raises(OSError):
        installer.main()
    assert (base / 'active.json').read_bytes() == before
    assert len([path for path in base.iterdir() if (path / 'runtime.bin').exists()]) == 2


@pytest.mark.p0
@pytest.mark.parametrize('system,device', [('darwin', 'metal'), ('win32', 'cuda')])
def test_repeated_llama_repair_is_bounded_and_preserves_unknown_files(tmp_path, monkeypatch, system, device):
    import zipfile

    from linguaflow import llama_install as installer
    monkeypatch.setattr('sys.platform', system)
    executable = 'llama-server.exe' if system == 'win32' else 'llama-server'
    archive = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr(executable, 'owned runtime')
    import hashlib
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    target = 'windows-x64' if system == 'win32' else 'macos-arm64'
    monkeypatch.setattr(installer, 'check_installation', lambda: target)
    monkeypatch.setattr(installer, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(installer, 'cache_root', lambda: tmp_path)
    monkeypatch.setattr(installer, 'preparation_lock', lambda _: nullcontext())
    monkeypatch.setattr(installer, 'run_command', lambda *args, **kwargs: None)
    monkeypatch.setattr('linguaflow.llama_assets.runtime_archives', lambda _: [(archive.name, expected)])
    monkeypatch.setattr(cleanup, 'process_commands', lambda: 'unrelated fixture process')
    component = 'llama-b11254-' + (target + '-' + device if system == 'win32' else target)
    base = tmp_path / 'components' / component
    unknown = base / ('f' * 32)
    unknown.mkdir(parents=True)
    (unknown / 'user-model.gguf').write_bytes(b'user data')
    for _ in range(5):
        installer.install(device, None)
    assert len([path for path in base.iterdir() if path.is_dir()]) == 3
    assert (unknown / 'user-model.gguf').read_bytes() == b'user data'


@pytest.mark.p0
def test_windows_311_reparse_mapping_is_rejected_without_path_junction_api(tmp_path, monkeypatch):
    import stat
    from types import SimpleNamespace

    directory = tmp_path / 'mapped-runtime'
    directory.mkdir()
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == directory:
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return value
    monkeypatch.delattr(Path, 'is_junction', raising=False)
    monkeypatch.setattr(Path, 'lstat', lstat)
    assert cleanup.mapped(directory)


@pytest.mark.p0
def test_missing_component_rollback_record_prevents_pruning(tmp_path, monkeypatch):
    base = tmp_path / 'component'
    old, active = component(base, 1), component(base, 2)
    (base / 'active.json').write_text(json.dumps({'slot': active.name, 'previous': 'f' * 32}))
    monkeypatch.setattr(cleanup, 'process_commands', lambda: 'unrelated fixture process')
    assert cleanup.clean_component(base, 'fixture') == 0 and old.exists()


@pytest.mark.p0
@pytest.mark.parametrize('kind', ['python', 'document', 'llama'])
def test_slot_collision_never_adopts_or_overwrites_existing_user_files(tmp_path, monkeypatch, kind):
    from types import SimpleNamespace

    from linguaflow import document_install, llama_install
    installers = {'python': runtime, 'document': document_install, 'llama': llama_install}
    installer = installers[kind]
    base = tmp_path / ('python/wlk' if kind == 'python' else 'components/document-renderer' if kind == 'document'
                       else 'components/llama-b11254-macos-arm64')
    directory = base / ('a' * 32)
    directory.mkdir(parents=True)
    user = directory / 'user-recording.wav'
    user.write_bytes(b'private user data')
    pointer = base / 'active.json'
    pointer.write_text(json.dumps({'slot': directory.name}))
    before = pointer.read_bytes()
    monkeypatch.setattr(installer, 'uuid4', lambda: SimpleNamespace(hex=directory.name))
    monkeypatch.setattr(installer, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(installer, 'preparation_lock', lambda _: nullcontext())
    monkeypatch.setattr(installer, 'check_installation', lambda: 'macos-arm64')
    monkeypatch.setattr(installer, 'run_command', lambda *args, **kwargs: pytest.fail('must reject before installing'))
    if kind == 'python':
        resources = tmp_path / 'app'
        resources.mkdir()
        (resources / 'requirements-runtime.txt').write_text('fixed==1')
        monkeypatch.setattr(installer, 'resource_root', lambda: resources)
        monkeypatch.setattr(installer, 'packaged', lambda: False)
        def call():
            installer.install('wlk')
    elif kind == 'document':
        monkeypatch.setattr(installer, 'node_executable', lambda: tmp_path / 'node')
        monkeypatch.setattr(installer, 'npm_command', lambda _: ['fixture-npm'])
        monkeypatch.setattr(installer.subprocess, 'check_output', lambda *args, **kwargs: 'v22.23.0')
        monkeypatch.setattr('linguaflow.process_platform.spawn_options', lambda: {})
        call = installer.main
    else:
        monkeypatch.setattr('linguaflow.llama_assets.runtime_archives', lambda _: [])
        def call():
            installer.install('metal', None)
    with pytest.raises(FileExistsError):
        call()
    assert pointer.read_bytes() == before and user.read_bytes() == b'private user data'
    assert not (directory / cleanup.MARKER).exists()
