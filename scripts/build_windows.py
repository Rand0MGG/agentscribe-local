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
    QT_MODULES,
    QT_PLUGIN_GROUPS,
    digest,
    extract,
    obtain,
    python_notices,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'packaging/windows'
WORK = ROOT / '.work/packaging'


def run(*args, **options):
    return subprocess.run(list(map(str, args)), check=True, **options)


def qt_subset(python):
    """Keep actual PE dependencies, playback and WebEngine; exclude unused Qt."""
    qt = python / 'Lib/site-packages/PySide6'

    for path in qt.glob('Qt*.pyd'):
        if path.stem not in QT_MODULES:
            path.unlink()
    for name in ('include', 'glue', 'typesystems', 'doc', 'QtAsyncio', 'scripts'):
        if (qt / name).is_dir():
            shutil.rmtree(qt / name)
    for name in ('designer.exe', 'assistant.exe', 'linguist.exe', 'qml.exe'):
        (qt / name).unlink(missing_ok=True)
    plugins = qt / 'plugins'
    for path in plugins.iterdir():
        if path.name not in QT_PLUGIN_GROUPS:
            shutil.rmtree(path)
    pending = list(qt.glob('*.pyd')) + list(plugins.rglob('*.dll')) + [qt / 'QtWebEngineProcess.exe']
    keep, examined = set(), set()
    while pending:
        path = pending.pop()
        if path in examined:
            continue
        examined.add(path)
        output = run('dumpbin', '/DEPENDENTS', path, capture_output=True, text=True).stdout
        for name in re.findall(r'\b(Qt6\w+\.dll)\b', output, re.IGNORECASE):
            dependency = next((p for p in qt.glob('Qt6*.dll') if p.name.lower() == name.lower()), None)
            if dependency is None:
                raise ValueError('Qt dependency missing: ' + name)
            if dependency.name not in keep:
                keep.add(dependency.name)
                pending.append(dependency)
    for path in qt.glob('Qt6*.dll'):
        if path.name not in keep:
            path.unlink()
    return sorted(keep)


def build(downloads):
    assets = json.loads((CONFIG / 'assets.json').read_text())
    archives = {name: obtain(item, downloads) for name, item in assets.items()}
    notices = json.loads((ROOT / 'packaging/macos/licenses.json').read_text())
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
    frameworks = qt_subset(python)
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
    shutil.copytree(ROOT / 'linguaflow', payload / 'linguaflow', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('requirements-runtime.txt', 'requirements-mlx.txt', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, payload / name)
    shutil.copy2(CONFIG / 'desktop.lock', payload / 'desktop.lock')
    shutil.copytree(downloads / 'licenses', payload / 'Licenses/Qt-PySide')
    python_notices(archives['python-notices'], payload / 'Licenses/Python')
    shutil.copy2(payload / 'node/LICENSE', payload / 'Licenses/Node-LICENSE.txt')
    credits = payload / 'Licenses/Qt-PySide/qtwebengine/documentation/qtwebengine-licensing.html'
    if not credits.is_file():
        raise ValueError('缺少同版 Qt WebEngine 第三方许可全文。')
    text = re.sub(r'href="(qtwebengine-3rdparty-[^"/]+\.html)"',
                  r'href="Qt-PySide/qtwebengine/documentation/\1"', credits.read_text(encoding='utf-8'))
    (payload / 'Licenses/QtWebEngine-credits.html').write_text(text, encoding='utf-8')
    for path in payload.rglob('__pycache__'):
        shutil.rmtree(path)
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / 'linguaflow/__init__.py').read_text())[1]
    sources = sorted(p for p in (ROOT / 'linguaflow').rglob('*') if p.suffix in {'.py', '.mjs'})
    sources += sorted(p for p in CONFIG.rglob('*') if p.is_file()) + [ROOT / 'packaging/recovery.c',
                ROOT / 'scripts/build_windows.py', ROOT / 'scripts/packaging_common.py', ROOT / 'packaging/updates.json',
                ROOT / 'pyproject.toml', ROOT / 'requirements-runtime.txt', ROOT / 'requirements-mlx.txt',
                ROOT / 'THIRD_PARTY_NOTICES.md', ROOT / 'packaging/macos/licenses.json']
    source_files = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}
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
    parser.add_argument('--fetch', action='store_true', help='Only fetch and verify locked inputs')
    parser.add_argument('--downloads', type=Path, default=WORK / 'windows-downloads')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise SystemExit('必须在 Windows x64 / MSVC 开发环境构建。')
    if args.fetch:
        assets = json.loads((CONFIG / 'assets.json').read_text())
        for item in assets.values():
            obtain(item, args.downloads, download=True)
        for item in json.loads((ROOT / 'packaging/macos/licenses.json').read_text()):
            obtain(item, args.downloads / 'licenses', download=True)
        run(sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--require-hashes',
            '--dest', args.downloads / 'wheels', '-r', CONFIG / 'desktop.lock')
    else:
        build(args.downloads)


if __name__ == '__main__':
    main()
