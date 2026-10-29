"""Pinned dual-frontend payload inputs; Qt-only packaging stays independent."""
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.package_electron import asset, extract_runtime, seal_manifest
from scripts.packaging_common import digest


@pytest.mark.p1
def test_packaged_electron_keeps_tracked_main_process_dependencies(tmp_path, monkeypatch):
    from scripts import package_electron

    root = tmp_path / 'source'
    frontend = root / 'desktop'
    (frontend / 'electron').mkdir(parents=True)
    (frontend / 'src').mkdir()
    (frontend / 'dist').mkdir()
    (frontend / 'node_modules/marked').mkdir(parents=True)
    (frontend / 'node_modules/marked/package.json').write_text('{"name":"marked","version":"18.1.2"}')
    (frontend / 'node_modules/marked/LICENSE').write_text('MIT fixture')
    (root / 'packaging/electron').mkdir(parents=True)
    description = {'filename': 'electron.zip', 'sha256': 'a' * 64}
    (root / 'packaging/electron/assets.json').write_text(json.dumps({
        'version': '45.0.0', 'targets': {'windows-x64': description}}))
    (frontend / 'package.json').write_text(json.dumps({'devDependencies': {'electron': '45.0.0'}}))
    (frontend / 'package-lock.json').write_text(json.dumps({'packages': {}}))
    (frontend / 'src/App.tsx').write_text('export {};')
    (frontend / 'dist/index.html').write_text('<html>isolated built UI</html>')
    modules = {'main.cjs': "module.exports=require('./window-layout.cjs');",
               'window-layout.cjs': 'exports.isSplitLayout=()=>false;',
               'preload.cjs': 'module.exports={};', 'service.cjs': 'module.exports={};',
               'markdown-tool.mjs': 'export const test = 1;'}
    for name, content in modules.items():
        (frontend / 'electron' / name).write_text(content)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    (frontend / 'electron/local-only.cjs').write_text('untracked local fixture')
    archive = tmp_path / 'electron.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('electron.exe', b'isolated runtime boundary')
    monkeypatch.setattr(package_electron, 'obtain', lambda *_: archive)
    original_run = subprocess.run
    def run(command, **kwargs):
        if command[0] in ('npm', 'npm.cmd'):
            assert command[1:] == ['run', 'build'] and kwargs['cwd'] == frontend
            assert kwargs['env']['AGENTSCRIBE_DESKTOP_PYTHON'] == sys.executable
            return subprocess.CompletedProcess(command, 0)
        return original_run(command, **kwargs)
    monkeypatch.setattr(package_electron.subprocess, 'run', run)
    target = tmp_path / 'desktop'
    inventory = package_electron.copy_electron(root, target, tmp_path, 'windows-x64')
    for name, content in modules.items():
        assert (target / 'electron' / name).read_text() == content
        assert inventory['desktop/electron/' + name] == digest(target / 'electron' / name)
    assert not (target / 'electron/local-only.cjs').exists()
    assert (target / 'node_modules/marked/LICENSE').read_text() == 'MIT fixture'
    manifest = json.loads((target / 'frontend-manifest.json').read_text())
    assert manifest['files']['electron/window-layout.cjs'] == digest(target / 'electron/window-layout.cjs')


@pytest.mark.p1
def test_electron_platform_assets_are_exact_and_match_lock():
    root = Path(__file__).resolve().parents[1]
    for target, suffix in (('macos-arm64', 'darwin-arm64'), ('windows-x64', 'win32-x64')):
        item = asset(root, target)
        assert item['filename'].endswith(suffix + '.zip')
        assert len(item['sha256']) == 64
        assert item['url'].startswith('https://github.com/electron/electron/releases/download/')
    value = json.loads((root / 'desktop/package-lock.json').read_text())
    assert value['packages']['node_modules/electron']['version'] == json.loads((root / 'packaging/electron/assets.json').read_text())['version']


@pytest.mark.p1
def test_electron_extract_preserves_executable_and_rejects_escape(tmp_path):
    archive = tmp_path / 'runtime.zip'
    entry = zipfile.ZipInfo('bin/electron')
    entry.external_attr = (stat.S_IFREG | 0o755) << 16
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr(entry, b'owned-runtime')
    destination = tmp_path / 'stage'
    extract_runtime(archive, destination)
    assert (destination / 'bin/electron').read_bytes() == b'owned-runtime'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('../outside', 'escape')
    with pytest.raises(ValueError, match='路径无效'):
        extract_runtime(archive, tmp_path / 'rejected')
    link = zipfile.ZipInfo('escape')
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr(link, '../outside')
    with pytest.raises(ValueError, match='越界'):
        extract_runtime(archive, tmp_path / 'rejected')
    assert not (tmp_path / 'outside').exists()


@pytest.mark.p1
def test_signed_frontend_manifest_uses_final_bytes(tmp_path):
    path = tmp_path / 'frontend-manifest.json'
    path.write_text(json.dumps({'runtime': {'sha256': 'original-archive'}, 'files': {}}))
    binary = tmp_path / 'electron.exe'
    binary.write_bytes(b'after-native-signing')
    seal_manifest(tmp_path)
    value = json.loads(path.read_text())
    assert value['runtime']['sha256'] == 'original-archive'
    assert value['files'] == {'electron.exe': digest(binary)}


@pytest.mark.p1
def test_electron_helper_bundle_executable_fallback_requires_actual_file(tmp_path):
    import plistlib

    from scripts.build_macos import bundle_executable
    bundle = tmp_path / 'Electron Helper (Renderer).app'
    contents = bundle / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleName': 'Electron Helper (Renderer)'}))
    with pytest.raises(ValueError, match='缺少可执行文件'):
        bundle_executable(bundle)
    entry = contents / 'MacOS/Electron Helper (Renderer)'
    entry.write_bytes(b'fixture-executable')
    assert bundle_executable(bundle) == entry


@pytest.mark.p1
def test_qt_framework_without_root_symlink_keeps_versioned_executable(tmp_path):
    import plistlib

    from scripts.build_macos import bundle_executable
    bundle = tmp_path / 'QtCore.framework'
    (bundle / 'Resources').mkdir(parents=True)
    (bundle / 'Resources/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'QtCore'}))
    entry = bundle / 'Versions/A/QtCore'
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b'qt-runtime')
    assert bundle_executable(bundle) == entry
