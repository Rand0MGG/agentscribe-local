"""Optional dual-frontend payload using pinned Electron archives and built local UI.

The existing native launcher/updater identity remains unchanged. No models or
personal browser profile are copied, and Qt-only builds keep their old inputs.
"""
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.packaging_common import digest, obtain


def asset(root, target):
    value = json.loads((root / 'packaging/electron/assets.json').read_text())
    package = json.loads((root / 'desktop/package.json').read_text())
    if package['devDependencies']['electron'] != value['version']:
        raise ValueError('Electron 版本与已校验的安装包输入不一致。')
    return value['targets'][target]


def extract_runtime(archive, destination):
    """Preserve macOS framework symlinks, rejecting archive paths outside the stage."""
    links = []
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            relative = Path(entry.filename)
            if (relative.is_absolute() or '..' in relative.parts or '\\' in entry.filename
                    or ':' in entry.filename):
                raise ValueError('Electron 归档路径无效。')
            path = destination / relative
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                target = source.read(entry).decode('utf-8')
                if Path(target).is_absolute() or not (path.parent / target).resolve().is_relative_to(destination.resolve()):
                    raise ValueError('Electron 归档包含越界目录映射。')
                links.append((path, target))
            elif entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as input_file, path.open('xb') as output:
                    shutil.copyfileobj(input_file, output)
                if mode & 0o777:
                    path.chmod(mode & 0o777)
    for path, target in links:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)


def copy_electron(root, destination, downloads, target):
    description = asset(root, target)
    archive = obtain(description, downloads)
    frontend = root / 'desktop'
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--', 'desktop', 'packaging/electron',
                                      'scripts/package_electron.py'], encoding='utf-8').split('\0')
    source_files = {name: digest(root / name) for name in names if name}
    for required in ('desktop/package-lock.json', 'desktop/electron/main.cjs', 'desktop/src/App.tsx'):
        if required not in source_files:
            raise ValueError('前端源码尚未纳入版本控制，不能封存安装包：' + required)
    lock = json.loads((frontend / 'package-lock.json').read_text())
    licenses = {}
    for relative, package in lock['packages'].items():
        if not relative or package.get('dev'):
            continue
        directory = frontend / relative
        actual = json.loads((directory / 'package.json').read_text())
        if actual['version'] != package['version']:
            raise ValueError('前端依赖与锁文件不一致，请先 npm ci：' + relative)
        files = [p for p in directory.iterdir() if p.is_file() and p.name.split('.')[0].lower() in ('license', 'licence')]
        if not files and relative == 'node_modules/react-remove-scroll-bar':
            files = [root / 'packaging/electron/react-remove-scroll-bar-LICENSE']
        if not files or any(not path.is_file() for path in files):
            raise ValueError('前端依赖缺少许可全文：' + relative)
        licenses[relative.removeprefix('node_modules/').replace('/', '__')] = files
    subprocess.run(['npm.cmd' if sys.platform == 'win32' else 'npm', 'run', 'build'], cwd=frontend, check=True,
                   env={**os.environ, 'AGENTSCRIBE_DESKTOP_PYTHON': sys.executable})
    if any(digest(root / name) != value for name, value in source_files.items()):
        raise ValueError('前端源码在构建期间变化，未封存。')
    destination.mkdir()
    extract_runtime(archive, destination / 'runtime')
    if target == 'macos-arm64':
        info_path = destination / 'runtime/Electron.app/Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info.update(CFBundleName='AgentScribe', CFBundleDisplayName='AgentScribe',
                    NSMicrophoneUsageDescription='AgentScribe 使用你选择的音频输入进行本地录音、识别和字幕翻译。')
        info_path.write_bytes(plistlib.dumps(info))
    shutil.copytree(frontend / 'dist', destination / 'dist')
    runtime_modules = sorted(name.removeprefix('desktop/') for name in source_files
                             if name.startswith('desktop/electron/') and name.endswith(('.cjs', '.mjs')))
    for name in ('package.json', *runtime_modules):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frontend / name, path)
    shutil.copytree(frontend / 'node_modules/marked', destination / 'node_modules/marked')
    for name, paths in licenses.items():
        for source in paths:
            path = destination / 'Licenses' / name / source.name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, path)
    manifest = dict(runtime=description, source_files=source_files,
                    files={p.relative_to(destination).as_posix(): digest(p) for p in destination.rglob('*') if p.is_file()})
    (destination / 'frontend-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return source_files


def seal_manifest(destination):
    """Refresh payload hashes after native signing, before sealing the outer app."""
    path = destination / 'frontend-manifest.json'
    value = json.loads(path.read_text())
    value['files'] = {p.relative_to(destination).as_posix(): digest(p)
                      for p in destination.rglob('*') if p.is_file() and p != path}
    path.write_text(json.dumps(value, indent=2) + '\n')
