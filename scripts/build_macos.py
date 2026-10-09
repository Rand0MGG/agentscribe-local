"""Build an Apple Silicon test DMG from verified portable runtimes and locked wheels.

Run with the source desktop Python. No microphone, model or normal app startup is used.
Downloads and products stay under .work/packaging; no system environment is installed.
"""
import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'packaging' / 'macos'
WORK = ROOT / '.work' / 'packaging'
MACHO = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}


def run(*command, **kwargs):
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def assets():
    return json.loads((CONFIG / 'assets.json').read_text()), json.loads((CONFIG / 'licenses.json').read_text())


def obtain(item, base, download=False):
    path = base / item['filename']
    if not path.is_file() and download:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(item['url'], timeout=90) as response, temporary.open('wb') as handle:
            shutil.copyfileobj(response, handle)
        if digest(temporary) != item['sha256']:
            raise ValueError('下载校验失败：' + item['filename'])
        temporary.replace(path)
    if not path.is_file() or digest(path) != item['sha256']:
        raise ValueError('缺少已校验的依赖，请先使用 --fetch：' + item['filename'])
    return path


def extract(archive, destination):
    with tarfile.open(archive) as handle:
        handle.extractall(destination, filter='data')


def python_notices(archive, destination):
    import zstandard
    destination.mkdir(parents=True)
    with archive.open('rb') as handle, zstandard.ZstdDecompressor().stream_reader(handle) as reader:
        with tarfile.open(fileobj=reader, mode='r|') as source:
            for member in source:
                if member.isfile() and (member.name.startswith('python/licenses/')
                                        or member.name == 'python/PYTHON.json'):
                    (destination / Path(member.name).name).write_bytes(source.extractfile(member).read())


def native_files(root):
    for path in sorted(root.rglob('*')):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as handle:
                if handle.read(4) in MACHO:
                    yield path


def qt_subset(python):
    """Deploy used Qt modules plus their actual framework/plugin dependencies.

    Keep multimedia playback, WebEngine's helper/resources/locales and image
    plugins. Unused developer apps and unrelated GPL-only modules are omitted.
    """
    qt = python / 'lib/python3.12/site-packages/PySide6'
    modules = {'QtCore', 'QtGui', 'QtWidgets', 'QtNetwork', 'QtOpenGL', 'QtOpenGLWidgets',
               'QtPrintSupport', 'QtSvg', 'QtMultimedia', 'QtWebChannel', 'QtWebEngineCore',
               'QtWebEngineWidgets'}
    for path in qt.glob('Qt*'):
        if path.is_file() and path.name.split('.')[0] not in modules:
            path.unlink()
    for name in ('Assistant.app', 'Designer.app', 'Linguist.app', 'include', 'glue', 'typesystems',
                 'doc', 'QtAsyncio', 'scripts'):
        path = qt / name
        if path.is_dir():
            shutil.rmtree(path)
    plugins = qt / 'Qt/plugins'
    for path in plugins.iterdir():
        if path.name not in {'platforms', 'styles', 'imageformats', 'iconengines', 'tls',
                             'networkinformation', 'multimedia'}:
            shutil.rmtree(path)
    libraries = qt / 'Qt/lib'
    roots = list(qt.glob('*.so')) + list(qt.glob('*.dylib')) + list(native_files(plugins))
    keep, examined = set(), set()
    while roots:
        path = roots.pop()
        if path in examined:
            continue
        examined.add(path)
        output = run('otool', '-L', path, capture_output=True, text=True).stdout
        for name in re.findall(r'(Qt\w+\.framework)/Versions/[^/]+/(Qt\w+)', output):
            framework = libraries / name[0]
            if framework not in keep:
                keep.add(framework)
                roots.append(framework / 'Versions/A' / name[1])
    for framework in libraries.glob('*.framework'):
        if framework not in keep:
            shutil.rmtree(framework)
    for name in ('bin', 'libexec', 'qml', 'metatypes'):
        path = qt / 'Qt' / name
        # The WebEngine process is inside its retained framework in macOS wheels.
        if path.is_dir():
            shutil.rmtree(path)
    for path in list(native_files(qt)):
        if path.parent == qt and path.suffix not in {'.so', '.dylib'}:
            path.unlink()
    return sorted(path.name for path in keep)


def make_icon(resources):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    iconset = resources / 'AgentScribe.iconset'
    iconset.mkdir()
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(str(CONFIG / 'AgentScribe.svg')).render(painter)
    painter.end()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            image.scaled(size * scale, size * scale, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation).save(str(iconset / name))
    run('iconutil', '-c', 'icns', '-o', resources / 'AgentScribe.icns', iconset)
    shutil.rmtree(iconset)


def sign(app):
    bundles = [p for p in app.rglob('*') if p.is_dir() and not p.is_symlink()
               and p.suffix in {'.framework', '.app'}] + [app]
    mains = set()
    for bundle in bundles:
        info_path = bundle / ('Resources/Info.plist' if bundle.suffix == '.framework' else 'Contents/Info.plist')
        info = plistlib.loads(info_path.read_bytes())
        entry = bundle / info['CFBundleExecutable'] if bundle.suffix == '.framework' else (
            bundle / 'Contents/MacOS' / info['CFBundleExecutable'])
        mains.add(entry.resolve())
    native = list(native_files(app))
    for path in native:
        architectures = run('lipo', '-archs', path, capture_output=True, text=True).stdout.split()
        if 'arm64' not in architectures:
            raise ValueError('安装包含非 Apple Silicon 组件：' + str(path))
        if len(architectures) > 1:
            temporary = path.with_name(path.name + '.arm64')
            run('lipo', path, '-thin', 'arm64', '-output', temporary)
            temporary.chmod(path.stat().st_mode)
            temporary.replace(path)
        commands = run('otool', '-l', path, capture_output=True, text=True).stdout
        identifiers = re.findall(r'cmd LC_ID_DYLIB\s+cmdsize \d+\s+name (.+?) \(offset \d+\)', commands)
        # otool -L also prints the dylib's own install name, which is not a
        # dependency. Normalize build-prefix IDs before sealing the bundle.
        if any(name.startswith('/') for name in identifiers):
            run('install_name_tool', '-id', '@rpath/' + path.name, path, capture_output=True)
        dependencies = run('otool', '-L', path, capture_output=True, text=True).stdout
        linked = [p for p in re.findall(r'^\s+(.+?) \(compatibility version', dependencies, re.M)
                  if p not in identifiers]
        if any(p.startswith('/') and not p.startswith(('/System/Library/', '/usr/lib/')) for p in linked):
            raise ValueError('组件仍依赖外部目录：' + str(path))
        rpaths = re.findall(r'^\s+path (.+?) \(offset \d+\)', commands, re.M)
        # Some upstream wheels retain unused build-machine search directories
        # despite correctly repaired relative dependencies. Never ship those.
        for rpath in sorted(set(p for p in rpaths if p.startswith('/'))):
            run('install_name_tool', '-delete_rpath', rpath, path, capture_output=True)
        minimum = re.findall(r'^\s+minos (\d+)\.(\d+)', commands, re.M)
        if any(tuple(map(int, version)) > (15, 0) for version in minimum):
            raise ValueError('组件最低系统高于 macOS 15：' + str(path))
        if path.resolve() not in mains:
            run('codesign', '--force', '--sign', '-', '--timestamp=none', path, capture_output=True)
    for bundle in sorted(bundles, key=lambda p: len(p.parts), reverse=True):
        run('codesign', '--force', '--sign', '-', '--timestamp=none', bundle, capture_output=True)
    run('codesign', '--verify', '--deep', '--strict', '--verbose=2', app)
    return len(native)


def build(downloads):
    runtimes, notices = assets()
    paths = {name: obtain(item, downloads) for name, item in runtimes.items()}
    for item in notices:
        obtain(item, downloads / 'licenses')
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / 'linguaflow/__init__.py').read_text())[1]
    short = version.split('-')[0]
    bundle_version = short + ('b' + version.split('-beta.')[1] if '-beta.' in version else '')
    stage = Path(tempfile.mkdtemp(prefix='build-', dir=WORK))
    volume = stage / 'volume'
    app = volume / 'AgentScribe.app'
    contents = app / 'Contents'
    resources, frameworks, executable = [contents / name for name in ('Resources', 'Frameworks', 'MacOS')]
    for path in (resources, frameworks, executable):
        path.mkdir(parents=True)
    python_framework = frameworks / 'Python.framework'
    python_version = python_framework / 'Versions/A'
    python_version.parent.mkdir(parents=True)
    extract(paths['python'], stage / 'python-extract')
    (stage / 'python-extract/python').rename(python_version)
    python_framework.joinpath('Versions/Current').symlink_to('A', target_is_directory=True)
    python_framework.joinpath('Python').symlink_to('Versions/Current/Python')
    python_framework.joinpath('Resources').symlink_to('Versions/Current/Resources', target_is_directory=True)
    # macOS requires the framework's main executable to be a regular file.
    (python_version / 'lib/libpython3.12.dylib').rename(python_version / 'Python')
    python_version.joinpath('lib/libpython3.12.dylib').symlink_to('../Python')
    python_version.joinpath('Resources').mkdir()
    python_info = dict(CFBundleIdentifier='io.github.rand0mgg.agentscribe.python', CFBundleName='Python',
                       CFBundleExecutable='Python', CFBundlePackageType='FMWK', CFBundleInfoDictionaryVersion='6.0',
                       CFBundleShortVersionString='3.12.15', CFBundleVersion='3.12.15')
    (python_version / 'Resources/Info.plist').write_bytes(plistlib.dumps(python_info))
    extract(paths['node'], stage / 'node-extract')
    node_contents = frameworks / 'Node.app/Contents'
    (node_contents / 'Resources').mkdir(parents=True)
    (node_contents / 'MacOS').mkdir()
    node = node_contents / 'Resources/node'
    (stage / 'node-extract/node-v22.23.0-darwin-arm64').rename(node)
    (node / 'bin/node').rename(node_contents / 'MacOS/node')
    node.joinpath('bin/node').symlink_to('../../../MacOS/node')
    node_info = dict(CFBundleIdentifier='io.github.rand0mgg.agentscribe.node', CFBundleName='AgentScribe Node',
                     CFBundleExecutable='node', CFBundlePackageType='APPL', CFBundleInfoDictionaryVersion='6.0',
                     CFBundleShortVersionString='22.23.0', CFBundleVersion='22.23.0', LSUIElement=True)
    (node_contents / 'Info.plist').write_bytes(plistlib.dumps(node_info))
    python = python_version
    resources.joinpath('python').symlink_to('../Frameworks/Python.framework/Versions/A', target_is_directory=True)
    resources.joinpath('node').symlink_to('../Frameworks/Node.app/Contents/Resources/node', target_is_directory=True)
    interpreter = python / 'bin/python3'
    environment = {**os.environ, 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                   'PIP_CACHE_DIR': str(WORK / 'pip-cache')}
    # A full, fresh distribution is installed in place; no existing venv is copied.
    run(interpreter, '-m', 'pip', 'install', '--no-index', '--find-links', downloads / 'wheels',
        '--require-hashes', '-r', CONFIG / 'desktop.lock', env=environment)
    run(interpreter, '-m', 'pip', 'check', env=environment)
    qt_frameworks = qt_subset(python)
    # Console wrappers installed by pip retain the construction directory in
    # their shebangs. The app invokes modules through Python, so omit them;
    # the complete stdlib, headers, pip/ensurepip and interpreter remain.
    for path in (python / 'bin').iterdir():
        if path.name not in {'python', 'python3', 'python3.12'}:
            path.unlink()
    shutil.copytree(ROOT / 'linguaflow', resources / 'linguaflow',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('requirements-runtime.txt', 'requirements-mlx.txt', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, resources / name)
    shutil.copytree(downloads / 'licenses', resources / 'Licenses/Qt-PySide')
    # The standalone archive includes the CPython license in its stdlib.
    shutil.copy2(python / 'lib/python3.12/LICENSE.txt', resources / 'Licenses/Python-LICENSE.txt')
    python_notices(paths['python-notices'], resources / 'Licenses/Python-build')
    shutil.copy2(node / 'LICENSE', resources / 'Licenses/Node-LICENSE.txt')
    shutil.copy2(CONFIG / 'THIRD_PARTY.md', resources / 'Licenses/README.md')
    shutil.copy2(CONFIG / '安装说明.txt', volume / '安装说明.txt')
    shutil.copy2(CONFIG / 'desktop.lock', resources / 'desktop.lock')
    resources.joinpath('应用授权.txt').write_text(
        '本包为 AgentScribe 预览版。应用源码尚未指定开源许可证。\n'
        '第三方组件保持各自许可证，详见 Licenses 和 THIRD_PARTY_NOTICES.md。\n', encoding='utf-8')
    info = dict(CFBundleName='AgentScribe', CFBundleDisplayName='AgentScribe',
                CFBundleInfoDictionaryVersion='6.0', CFBundleSupportedPlatforms=['MacOSX'],
                CFBundleIdentifier='io.github.rand0mgg.agentscribe', CFBundleExecutable='AgentScribe',
                CFBundlePackageType='APPL', CFBundleShortVersionString=short, CFBundleVersion=bundle_version,
                AgentScribeVersion=version, CFBundleIconFile='AgentScribe', LSMinimumSystemVersion='15.0',
                LSApplicationCategoryType='public.app-category.productivity',
                LSRequiresNativeExecution=True, NSHighResolutionCapable=True,
                NSMicrophoneUsageDescription='AgentScribe 使用你选择的音频输入进行本地录音、识别和字幕翻译。')
    with (contents / 'Info.plist').open('wb') as handle:
        plistlib.dump(info, handle)
    make_icon(resources)
    run('clang', '-arch', 'arm64', '-mmacosx-version-min=15.0', '-O2', '-Wall', '-Wextra',
        '-I' + str(python / 'include/python3.12'), CONFIG / 'launcher.c',
        '-L' + str(python / 'lib'), '-lpython3.12', '-framework', 'CoreFoundation',
        '-Wl,-rpath,@executable_path/../Frameworks/Python.framework/Versions/A/lib',
        '-o', executable / 'AgentScribe')
    # Writable scripts generated by pip are not launch paths in the app. All
    # Python operations explicitly use the bundled interpreter with -m.
    for path in app.rglob('__pycache__'):
        shutil.rmtree(path)
    source_files = sorted(p for p in (ROOT / 'linguaflow').rglob('*') if p.suffix in {'.py', '.mjs'})
    build_files = sorted(p for p in CONFIG.rglob('*') if p.is_file()) + [Path(__file__).resolve()]
    source = {str(p.relative_to(ROOT)): digest(p) for p in source_files + build_files
              + [ROOT / 'pyproject.toml', ROOT / 'requirements-runtime.txt', ROOT / 'requirements-mlx.txt',
                 ROOT / 'THIRD_PARTY_NOTICES.md']}
    modified = bool(run('git', '-C', ROOT, 'status', '--porcelain', '--untracked-files=all',
                        '--', *source, capture_output=True, text=True).stdout.strip())
    manifest = dict(version=version, target='macos-arm64', minimum_macos='15.0',
                    created_at=datetime.now(timezone.utc).isoformat(),
                    source_commit=run('git', '-C', ROOT, 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip(),
                    source_modified=modified, source_files=source, portable_runtimes=runtimes,
                    desktop_lock_sha256=digest(CONFIG / 'desktop.lock'), qt_frameworks=qt_frameworks,
                    signature='ad-hoc', notarized=False, models_included=False)
    (resources / 'build-manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    index = resources / 'Licenses/Qt-PySide/qtwebengine/documentation/qtwebengine-licensing.html'
    if not index.is_file():
        raise ValueError('缺少同版 Qt WebEngine 第三方许可全文。')
    credits = index.read_text(encoding='utf-8')
    credits = re.sub(r'href="(qtwebengine-3rdparty-[^"/]+\.html)"',
                     r'href="Qt-PySide/qtwebengine/documentation/\1"', credits)
    (resources / 'Licenses/QtWebEngine-credits.html').write_text(credits, encoding='utf-8')
    count = sign(app)
    volume.joinpath('Applications').symlink_to('/Applications', target_is_directory=True)
    output = WORK / 'dist'
    output.mkdir(exist_ok=True)
    dmg = output / f'AgentScribe-{version}-macos-arm64.dmg'
    temporary = stage / dmg.name
    run('hdiutil', 'create', '-volname', f'AgentScribe {version}', '-srcfolder', volume,
        '-format', 'UDZO', '-fs', 'HFS+', '-imagekey', 'zlib-level=9', temporary)
    run('hdiutil', 'verify', temporary)
    temporary.replace(dmg)
    sha = digest(dmg)
    dmg.with_suffix('.dmg.sha256').write_text(f'{sha}  {dmg.name}\n')
    manifest.update(dmg_sha256=sha, dmg_bytes=dmg.stat().st_size, native_files=count)
    dmg.with_suffix('.build.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(dict(dmg=str(dmg), app=str(app), sha256=sha, bytes=dmg.stat().st_size), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='只下载校验后的构建依赖')
    parser.add_argument('--downloads', type=Path, default=WORK / 'downloads')
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('必须在原生 Apple Silicon Mac 构建此安装包。')
    WORK.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        runtimes, notices = assets()
        for item in runtimes.values():
            obtain(item, args.downloads, download=True)
        for item in notices:
            obtain(item, args.downloads / 'licenses', download=True)
        run(sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--require-hashes',
            '--cache-dir', WORK / 'pip-cache', '--dest', args.downloads / 'wheels', '-r', CONFIG / 'desktop.lock')
    else:
        build(args.downloads)


if __name__ == '__main__':
    main()
