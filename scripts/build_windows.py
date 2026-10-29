"""Build the complete Windows x64 desktop payload from locked portable assets.

Run in an x64 MSVC developer shell, then seal with build_windows_installer.py.
No installed developer environment, inference package or model is copied.
"""
import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.packaging_common import (
    copy_application,
    digest,
    extract,
    obtain,
    python_notices,
    trim_dependency_tests,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'packaging/windows'
WORK = ROOT / '.work/packaging'


def run(*args, **options):
    return subprocess.run(list(map(str, args)), check=True, **options)


def build(downloads, *, with_electron=True):
    if not with_electron:
        raise ValueError('正式安装包必须包含 Electron；Qt 界面已退役。')
    assets = json.loads((CONFIG / 'assets.json').read_text())
    archives = {name: obtain(item, downloads) for name, item in assets.items()}
    notices = []
    for notice in notices:
        obtain(notice, downloads / 'licenses')
    WORK.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='windows-payload-', dir=WORK))
    payload = stage / 'AgentScribe'
    payload.mkdir()
    extract(archives['python'], payload)
    python = payload / 'python'
    executable = python / 'python.exe'
    if not executable.is_file() or not (python / 'include/Python.h').is_file() or not (python / 'libs/python312.lib').is_file():
        raise ValueError('便携 Python 缺少完整解释器、头文件或链接库。')
    with zipfile.ZipFile(archives['node']) as archive:
        expected = 'node-v22.23.0-win-x64/'
        for item in archive.infolist():
            path = Path(item.filename)
            if not item.filename.startswith(expected) or '..' in path.parts or path.is_absolute():
                raise ValueError('Node archive contains an invalid path.')
        archive.extractall(stage)
    (stage / 'node-v22.23.0-win-x64').rename(payload / 'node')
    run(executable, '-m', 'pip', 'install', '--no-index', '--find-links', downloads / 'wheels',
        '--require-hashes', '-r', CONFIG / 'desktop.lock')
    run(executable, '-m', 'pip', 'check')
    frameworks = []
    trim_dependency_tests(python / 'Lib/site-packages')
    run('cl', '/nologo', '/O2', '/W4', '/DUNICODE', '/D_UNICODE',
        '/I' + str(python / 'include'), CONFIG / 'launcher.c', '/Fe:' + str(payload / 'AgentScribe.exe'),
        '/Fo:' + str(stage / 'launcher.obj'), '/link', '/SUBSYSTEM:WINDOWS',
        '/LIBPATH:' + str(python / 'libs'), 'python312.lib', 'shell32.lib', 'user32.lib')
    run('cl', '/nologo', '/O2', '/W4', '/LD', ROOT / 'packaging/recovery.c',
        '/Fe:' + str(payload / 'AgentScribeRecovery.dll'), '/Fo:' + str(stage / 'recovery.obj'),
        '/link', '/IMPLIB:' + str(stage / 'recovery.lib'))
    # Windows resolves the launcher's imports before wWinMain can set paths.
    for library in python.glob('*.dll'):
        shutil.copy2(library, payload / library.name)
    application_files = copy_application(ROOT, payload / 'linguaflow')
    if with_electron:
        from scripts.package_electron import copy_electron
        application_files.update(copy_electron(ROOT, payload / 'desktop', downloads, 'windows-x64'))
    for name in ('requirements-runtime.txt', 'requirements-mlx.txt', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, payload / name)
    shutil.copy2(CONFIG / 'desktop.lock', payload / 'desktop.lock')
    python_notices(archives['python-notices'], payload / 'Licenses/Python')
    shutil.copy2(payload / 'node/LICENSE', payload / 'Licenses/Node-LICENSE.txt')
    for path in payload.rglob('__pycache__'):
        shutil.rmtree(path)
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / 'linguaflow/__init__.py').read_text())[1]
    sources = sorted(p for p in CONFIG.rglob('*') if p.is_file()) + [ROOT / 'packaging/recovery.c',
                ROOT / 'scripts/build_windows.py', ROOT / 'scripts/packaging_common.py', ROOT / 'packaging/updates.json',
                ROOT / 'scripts/build_windows_installer.py', ROOT / 'scripts/probe_package.py',
                ROOT / 'scripts/probe_packaged_launcher.py',
                ROOT / 'pyproject.toml', ROOT / 'requirements-runtime.txt', ROOT / 'requirements-mlx.txt',
                ROOT / 'THIRD_PARTY_NOTICES.md', ROOT / 'packaging/macos/licenses.json']
    source_files = {**application_files, **{p.relative_to(ROOT).as_posix(): digest(p) for p in sources}}
    modified = bool(run('git', '-C', ROOT, 'status', '--porcelain', '--', *source_files,
                        capture_output=True, text=True).stdout.strip())
    manifest = dict(version=version, target='windows-x64', minimum_windows='10.0',
                    created_at=datetime.now(timezone.utc).isoformat(), source_modified=modified,
                    source_commit=run('git', '-C', ROOT, 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip(),
                    source_files=source_files, portable_runtimes=assets, qt_libraries=frameworks,
                    desktop_lock_sha256=digest(CONFIG / 'desktop.lock'), models_included=False,
                    payload_files={p.relative_to(payload).as_posix(): digest(p) for p in payload.rglob('*') if p.is_file()})
    (payload / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-electron', action='store_true', default=True, help='Compatibility argument; Electron is required')
    parser.add_argument('--fetch', action='store_true', help='Only fetch and verify locked inputs')
    parser.add_argument('--downloads', type=Path, default=WORK / 'windows-downloads')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise SystemExit('必须在 Windows x64 / MSVC 开发环境构建。')
    if args.fetch:
        if args.with_electron:
            from scripts.package_electron import asset
            obtain(asset(ROOT, 'windows-x64'), args.downloads, download=True)
        assets = json.loads((CONFIG / 'assets.json').read_text())
        for item in assets.values():
            obtain(item, args.downloads, download=True)
        for item in []:
            obtain(item, args.downloads / 'licenses', download=True)
        run(sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--require-hashes',
            '--dest', args.downloads / 'wheels', '-r', CONFIG / 'desktop.lock')
    else:
        build(args.downloads, with_electron=args.with_electron)


if __name__ == '__main__':
    main()
