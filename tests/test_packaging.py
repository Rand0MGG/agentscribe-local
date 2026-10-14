"""Release file boundaries, sealed-probe ordering and bounded Windows cleanup."""
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from linguaflow import windows_install_cleanup as cleanup
from scripts import build_macos, build_windows_installer, packaging_common, probe_package

ROOT = Path(__file__).resolve().parents[1]


def tracked_source(root):
    (root / 'linguaflow/knowledge').mkdir(parents=True)
    (root / 'linguaflow/__init__.py').write_text('__version__ = "0.8.0"')
    (root / 'linguaflow/knowledge/render.mjs').write_text('export {};')
    (root / '.gitignore').write_text('.env\n')
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)


@pytest.mark.parametrize('destination', ['Contents/Resources/linguaflow', 'AgentScribe/linguaflow'])
def test_both_builds_copy_only_tracked_declared_application_inputs(tmp_path, destination):
    root = tmp_path / 'source'
    tracked_source(root)
    (root / 'linguaflow/.env').write_text('SYNTHETIC_LOCAL_ONLY=fixture')
    (root / 'linguaflow/untracked.py').write_text('raise RuntimeError("local experiment")')
    target = tmp_path / destination
    inventory = packaging_common.copy_application(root, target)
    assert set(inventory) == {'linguaflow/__init__.py', 'linguaflow/knowledge/render.mjs'}
    assert not (target / '.env').exists() and not (target / 'untracked.py').exists()
    assert all(packaging_common.digest(tmp_path / destination / Path(name).relative_to('linguaflow')) == sha
               for name, sha in inventory.items())


def test_copy_rejects_undeclared_tracked_resource_and_missing_code(tmp_path):
    tracked_source(tmp_path)
    extra = tmp_path / 'linguaflow/local.json'
    extra.write_text('{}')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    with pytest.raises(ValueError, match='未声明'):
        packaging_common.copy_application(tmp_path, tmp_path / 'output')
    subprocess.run(['git', '-C', str(tmp_path), 'rm', '--cached', '-q', 'linguaflow/local.json'], check=True)
    (tmp_path / 'linguaflow/__init__.py').unlink()
    with pytest.raises(ValueError, match='缺失'):
        packaging_common.copy_application(tmp_path, tmp_path / 'output')


def installation(root):
    names = ['AgentScribe.exe', 'python/python.exe', 'linguaflow/current.py']
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'new program fixture')
    files = {name: cleanup.checksum(root / name) for name in names}
    manifest = dict(target='windows-x64', source_modified=False, payload_files=files)
    (root / 'build-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    obsolete = root / 'linguaflow/obsolete.py'
    obsolete.write_bytes(b'old code fixture')
    previous = root / cleanup.PREVIOUS_MANIFEST
    previous.write_text(json.dumps({**manifest, 'payload_files': {
        **files, 'linguaflow/obsolete.py': cleanup.checksum(obsolete)}}), encoding='utf-8')
    return previous, obsolete


def test_upgrade_removes_only_unchanged_manifested_program_files(tmp_path):
    previous, obsolete = installation(tmp_path)
    old = json.loads(previous.read_text())
    for name in ['models/personal.gguf', '录音/lecture.wav', 'linguaflow/personal.srt']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'keep user data')
        old['payload_files'][name] = cleanup.checksum(path)
    previous.write_text(json.dumps(old), encoding='utf-8')
    unlisted = tmp_path / 'linguaflow/unlisted.py'
    unlisted.write_bytes(b'keep unowned file')
    assert cleanup.cleanup(tmp_path, previous) == ['linguaflow/obsolete.py']
    assert not obsolete.exists() and not previous.exists()
    assert unlisted.is_file()
    assert all((tmp_path / name).read_bytes() == b'keep user data'
               for name in ['models/personal.gguf', '录音/lecture.wav', 'linguaflow/personal.srt'])
    assert cleanup.cleanup(tmp_path, previous) == []


@pytest.mark.parametrize('change', ['old', 'new'])
def test_changed_program_files_stop_cleanup_and_preserve_retry_manifest(tmp_path, change):
    previous, obsolete = installation(tmp_path)
    (obsolete if change == 'old' else tmp_path / 'AgentScribe.exe').write_bytes(b'changed')
    with pytest.raises(ValueError, match='变化|校验失败'):
        cleanup.cleanup(tmp_path, previous)
    assert obsolete.exists() and previous.exists()


@pytest.mark.parametrize('name', ['../outside.py', 'C:/outside.py', '/outside.py',
                                 'linguaflow/a/../other.py', 'linguaflow/other.py:stream',
                                 'linguaflow/other.py.', 'linguaflow\\other.py'])
def test_invalid_old_inventory_cannot_delete_program_or_external_data(tmp_path, name):
    previous, obsolete = installation(tmp_path)
    manifest = json.loads(previous.read_text())
    manifest['payload_files'][name] = 'a' * 64
    previous.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='无效路径'):
        cleanup.cleanup(tmp_path, previous)
    assert obsolete.exists() and previous.exists()


def test_windows_case_alias_is_not_an_obsolete_file(tmp_path):
    previous, obsolete = installation(tmp_path)
    manifest = json.loads(previous.read_text())
    manifest['payload_files']['linguaflow/CURRENT.py'] = manifest['payload_files'].pop('linguaflow/current.py')
    previous.write_text(json.dumps(manifest), encoding='utf-8')
    cleanup.cleanup(tmp_path, previous)
    assert not obsolete.exists() and (tmp_path / 'linguaflow/current.py').exists()


def test_cleanup_rejects_directory_mapping_and_external_manifest(tmp_path, monkeypatch):
    previous, obsolete = installation(tmp_path)
    with pytest.raises(ValueError, match='必须位于'):
        cleanup.cleanup(tmp_path, tmp_path.parent / 'external.json')
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path == tmp_path / 'linguaflow')
    with pytest.raises(ValueError, match='映射'):
        cleanup.cleanup(tmp_path, previous)
    assert previous.exists() and obsolete.exists()


def test_cleanup_io_failure_keeps_inventory_and_can_retry(tmp_path, monkeypatch):
    previous, obsolete = installation(tmp_path)
    original = Path.unlink
    def fail(path, *args, **kwargs):
        if path == obsolete:
            raise PermissionError('fixture busy file')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', fail)
        with pytest.raises(PermissionError):
            cleanup.cleanup(tmp_path, previous)
    assert obsolete.exists() and previous.exists()
    assert cleanup.cleanup(tmp_path, previous) == ['linguaflow/obsolete.py']


@pytest.mark.parametrize('failure', [None, 'launcher', 'full', 'attach'])
def test_mac_final_image_probe_detaches_after_probe_failure(tmp_path, monkeypatch, failure):
    calls = []
    def run(*args, **kwargs):
        calls.append(args[1])
        if failure == 'attach' and args[1] == 'attach':
            raise RuntimeError('fixture attach failure')
    def probe(kind):
        calls.append(kind)
        if failure == kind:
            raise RuntimeError('fixture probe failure')
    from scripts import probe_packaged_launcher
    monkeypatch.setattr(build_macos, 'run', run)
    monkeypatch.setattr(probe_packaged_launcher, 'probe', lambda path: probe('launcher'))
    monkeypatch.setattr(probe_package, 'run_probe', lambda path: probe('full'))
    if failure:
        with pytest.raises(RuntimeError):
            build_macos.probe_image(tmp_path / 'sealed.dmg', tmp_path / 'mount')
    else:
        build_macos.probe_image(tmp_path / 'sealed.dmg', tmp_path / 'mount')
    assert calls[0] == 'attach'
    assert (calls[-1] == 'detach') == (failure != 'attach')


@pytest.mark.parametrize('mac', [False, True])
@pytest.mark.parametrize('failure', [None, 'audio', 'process'])
def test_shared_probe_isolates_both_platforms_and_rejects_guard_failures(tmp_path, monkeypatch, mac, failure):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/test_no_audio.py').write_text("GUARD = 'fixture guard'\n")
    monkeypatch.setattr(probe_package, 'ROOT', tmp_path)
    def run(command, **options):
        env, work = options['env'], options['cwd']
        resources = app / 'Contents/Resources' if mac else app
        assert env['AGENTSCRIBE_RESOURCES'] == str(resources)
        assert env['HOME'] == str(work) and env['LOCALAPPDATA'] == str(work / 'Local')
        assert str(work) in env['PYTHONPATH'] and 'PYTHONHOME' not in env
        assert command[0] == str(app / 'Contents/MacOS/AgentScribe' if mac else app / 'AgentScribe.exe')
        if failure == 'audio':
            Path(env['AGENTSCRIBE_AUDIO_GUARD_LOG']).write_text('blocked fixture import')
        (work / 'result.json').write_text('{"shutdown_complete":true}')
        return SimpleNamespace(returncode=1 if failure == 'process' else 0, stdout='', stderr='')
    monkeypatch.setattr(probe_package.subprocess, 'run', run)
    app = tmp_path / ('AgentScribe.app' if mac else 'AgentScribe')
    if failure:
        with pytest.raises(RuntimeError, match='音频访问|探针失败'):
            probe_package.run_probe(app)
    else:
        assert probe_package.run_probe(app).is_dir()


def test_inside_probe_installs_guard_when_launcher_replaces_pythonpath(tmp_path):
    # -I models a launcher that does not import an inherited sitecustomize.
    # Check the guard's presence without attempting any audio backend import.
    code = '''
import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_probe',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(type(f).__name__=='NoNativeAudio' for f in sys.meta_path)
def guarded(*args,**kwargs):
    assert any(type(f).__name__=='NoNativeAudio' for f in sys.meta_path)
module.probe=guarded
sys.argv=['probe',sys.argv[2],'--inside',sys.argv[2]]
module.main()
'''
    subprocess.run([sys.executable, '-I', '-c', code, str(ROOT / 'scripts/probe_package.py'), str(tmp_path)],
                   check=True, timeout=15)


@pytest.mark.parametrize('failure', [False, True])
def test_windows_sealer_probes_final_updater_payload_before_compilation(tmp_path, monkeypatch, failure):
    builder = build_windows_installer
    payload = tmp_path / 'original'
    payload.mkdir()
    (payload / 'AgentScribe.exe').write_bytes(b'fixture launcher')
    manifest = dict(version=builder.__version__, target='windows-x64', source_modified=False)
    (payload / 'build-manifest.json').write_text(json.dumps(manifest))
    configuration = {'feed_base': 'https://example.org/updates', 'targets': {'windows-x64': {
        'public_key': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=', 'filename': 'sparkle.zip'}}}
    (tmp_path / 'packaging').mkdir()
    (tmp_path / 'packaging/updates.json').write_text(json.dumps(configuration))
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    with zipfile.ZipFile(downloads / 'sparkle.zip', 'w') as archive:
        archive.writestr('WinSparkle-0.9.4/x64/Release/WinSparkle.dll', b'fixture dll')
        archive.writestr('WinSparkle-0.9.4/COPYING', 'fixture license')
    configuration['targets']['windows-x64']['sha256'] = builder.digest(downloads / 'sparkle.zip')
    (tmp_path / 'packaging/updates.json').write_text(json.dumps(configuration))
    calls = []
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(builder, 'validate_payload', lambda _: manifest.copy())
    def probe(sealed):
        calls.append('full')
        assert (sealed / 'WinSparkle.dll').is_file()
        info = json.loads((sealed / 'build-manifest.json').read_text())
        assert info['updater'] == json.loads((sealed / 'update-config.json').read_text())
        if failure:
            raise RuntimeError('fixture rejected payload')
    monkeypatch.setattr(builder, 'probe', lambda _: calls.append('launcher'))
    monkeypatch.setattr(builder, 'run_probe', probe)
    def compile(command, **options):
        calls.append('compiler')
        stage = Path(next(arg[len('/DOutput='):] for arg in command if arg.startswith('/DOutput=')))
        (stage / f'AgentScribe-{builder.__version__}-windows-x64.exe').write_bytes(b'fixture installer')
    monkeypatch.setattr(builder.subprocess, 'run', compile)
    if failure:
        with pytest.raises(RuntimeError, match='rejected'):
            builder.build(payload, Path('fixture-iscc'), downloads)
        assert calls == ['launcher', 'full']
        assert not list((tmp_path / '.work/packaging/dist').iterdir())
    else:
        builder.build(payload, Path('fixture-iscc'), downloads)
        assert calls == ['launcher', 'full', 'compiler']


def test_actual_windows_builder_excludes_ignored_file_from_clean_source_payload(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('audit_build_windows', ROOT / 'scripts/build_windows.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    root = tmp_path / 'source'
    config = root / 'packaging/windows'
    config.mkdir(parents=True)
    (root / 'packaging/macos').mkdir()
    (root / 'scripts').mkdir()
    (root / 'linguaflow').mkdir()
    (root / 'linguaflow/__init__.py').write_text('__version__ = "0.8.0"\n')
    (root / '.gitignore').write_text('.env\n.work/\n')
    for name in ('packaging/recovery.c', 'scripts/build_windows.py', 'scripts/packaging_common.py', 'scripts/build_windows_installer.py',
                 'scripts/probe_package.py', 'scripts/probe_packaged_launcher.py',
                 'packaging/updates.json', 'pyproject.toml', 'requirements-runtime.txt',
                 'requirements-mlx.txt', 'THIRD_PARTY_NOTICES.md', 'packaging/windows/desktop.lock'):
        (root / name).write_text('fixture input')
    (config / 'assets.json').write_text(json.dumps({name: {'filename': name + '.zip'}
                                                  for name in ('python', 'python-notices', 'node')}))
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Audit', '-c', 'user.email=audit@example.org',
                    'commit', '-qm', 'isolated fixture'], check=True)
    # A synthetic value; no real credential is read or printed.
    (root / 'linguaflow/.env').write_text('AUDIT_LOCAL_ONLY=fixture\n')
    assert not subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain']).strip()
    downloads = tmp_path / 'downloads'
    credit = downloads / 'licenses/qtwebengine/documentation/qtwebengine-licensing.html'
    credit.parent.mkdir(parents=True)
    credit.write_text('<html>fixture license</html>')
    (root / 'packaging/macos/licenses.json').write_text(json.dumps([
        {'filename': 'qtwebengine/documentation/qtwebengine-licensing.html',
         'sha256': builder.digest(credit)}]))
    subprocess.run(['git', '-C', str(root), 'add', 'packaging/macos/licenses.json'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Audit', '-c', 'user.email=audit@example.org',
                    'commit', '-qm', 'sealed license fixture'], check=True)
    (downloads / 'licenses/unrelated-local.txt').write_text('synthetic unrelated content')
    with zipfile.ZipFile(downloads / 'node.zip', 'w') as archive:
        archive.writestr('node-v22.23.0-win-x64/LICENSE', 'fixture license')

    def extract(_archive, payload):
        for name in ('python/python.exe', 'python/include/Python.h', 'python/libs/python312.lib'):
            path = payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'not executable')

    def run(*args, **kwargs):
        if str(args[0]) == 'git':
            return subprocess.run(list(map(str, args)), check=True, **kwargs)
        if str(args[0]) == 'cl':
            Path(next(str(arg)[4:] for arg in args if str(arg).startswith('/Fe:'))).write_bytes(b'fixture native')
        return SimpleNamespace(stdout='')

    monkeypatch.setattr(builder, 'ROOT', root)
    monkeypatch.setattr(builder, 'CONFIG', config)
    monkeypatch.setattr(builder, 'WORK', root / '.work')
    monkeypatch.setattr(builder, 'obtain', lambda item, base: base / item['filename'])
    monkeypatch.setattr(builder, 'extract', extract)
    monkeypatch.setattr(builder, 'run', run)
    monkeypatch.setattr(builder, 'qt_subset', lambda _: [])
    monkeypatch.setattr(builder, 'python_notices', lambda _archive, destination: destination.mkdir(parents=True))
    payload = builder.build(downloads)
    manifest = json.loads((payload / 'build-manifest.json').read_text())
    assert not (payload / 'linguaflow/.env').exists()
    assert 'linguaflow/.env' not in manifest['payload_files']
    assert 'linguaflow/.env' not in manifest['source_files']
    assert manifest['source_modified'] is False
    assert not (payload / 'Licenses/Qt-PySide/unrelated-local.txt').exists()


@pytest.mark.parametrize('extra', ['private.txt', '.env', 'unrelated.py'])
def test_declared_licenses_exclude_unlisted_files(tmp_path, extra):
    source, target = tmp_path / 'downloads', tmp_path / 'payload'
    source.mkdir()
    license = source / 'license.txt'
    license.write_text('allowed fixture')
    (source / extra).write_text('not allowed fixture')
    packaging_common.copy_notices([{'filename': 'license.txt', 'sha256': packaging_common.digest(license)}],
                                  source, target)
    assert {p.name for p in target.iterdir()} == {'license.txt'}


@pytest.mark.parametrize('change', ['corrupt', 'symlink', 'escape'])
def test_licenses_reject_corruption_and_mappings(tmp_path, change):
    source, target = tmp_path / 'downloads', tmp_path / 'payload'
    source.mkdir()
    license = source / 'license.txt'
    license.write_text('allowed fixture')
    notice = {'filename': 'license.txt', 'sha256': packaging_common.digest(license)}
    if change == 'corrupt':
        license.write_text('changed')
    elif change == 'symlink':
        license.unlink()
        outside = tmp_path / 'user-data.txt'
        outside.write_text('allowed fixture')
        try:
            license.symlink_to(outside)
        except OSError as error:
            if sys.platform == 'win32' and error.winerror == 1314:
                pytest.skip('Real file symlink requires Windows symlink privilege')
            raise
    else:
        notice['filename'] = '../license.txt'
    with pytest.raises(ValueError):
        packaging_common.copy_notices([notice], source, target)
    assert not target.exists()


@pytest.mark.parametrize('warning', ['QProcess: Destroyed while process is still running.',
                                    'QThread: Destroyed while thread is still running'])
def test_package_probe_rejects_success_exit_with_lifecycle_warning(tmp_path, monkeypatch, warning):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/test_no_audio.py').write_text("GUARD = ''")
    monkeypatch.setattr(probe_package, 'ROOT', tmp_path)
    def run(command, **options):
        (options['cwd'] / 'result.json').write_text('{"shutdown_complete":true}')
        return SimpleNamespace(returncode=0, stdout='', stderr=warning)
    monkeypatch.setattr(probe_package.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='退出或绘制错误'):
        probe_package.run_probe(tmp_path / 'AgentScribe.app')


def test_package_window_waits_for_accepted_close_and_owned_processes():
    from PySide6.QtCore import QProcess
    state = {'steps': 0}
    job = SimpleNamespace(state=lambda: QProcess.ProcessState.NotRunning if state['steps'] >= 3
                          else QProcess.ProcessState.Running)
    window = SimpleNamespace(close=lambda: None, isVisible=lambda: state['steps'] < 2,
                             background_checks=set(), findChildren=lambda _: [job])
    application = SimpleNamespace(processEvents=lambda: state.update(steps=state['steps'] + 1))
    probe_package.close_window(window, application)
    assert state['steps'] == 3


def test_package_window_timeout_is_failure():
    window = SimpleNamespace(close=lambda: None, isVisible=lambda: True,
                             background_checks=set(), findChildren=lambda _: [])
    with pytest.raises(RuntimeError, match='未完成退出'):
        probe_package.close_window(window, SimpleNamespace(processEvents=lambda: None), timeout=0)


def test_dependency_test_trimming_keeps_helpers_datasets_and_licenses(tmp_path):
    for name in ('numpy/tests/test_fixture.py', 'scipy/linalg/tests/test_fixture.py',
                 'scipy/_lib/_testutils.py', 'scipy/datasets/sample.dat', 'numpy/LICENSE.txt',
                 'unrelated/tests/user.txt'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    packaging_common.trim_dependency_tests(tmp_path)
    assert not (tmp_path / 'numpy/tests').exists() and not (tmp_path / 'scipy/linalg/tests').exists()
    assert all((tmp_path / name).is_file() for name in ('scipy/_lib/_testutils.py', 'scipy/datasets/sample.dat',
                                                     'numpy/LICENSE.txt', 'unrelated/tests/user.txt'))
