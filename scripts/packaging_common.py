"""Verified portable assets and license extraction shared by platform builds."""
import hashlib
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

QT_MODULES = {'QtCore', 'QtGui', 'QtWidgets', 'QtNetwork', 'QtOpenGL', 'QtOpenGLWidgets',
              'QtPrintSupport', 'QtSvg', 'QtMultimedia', 'QtWebChannel', 'QtWebEngineCore',
              'QtWebEngineWidgets'}
QT_PLUGIN_GROUPS = {'platforms', 'styles', 'imageformats', 'iconengines', 'tls',
                    'networkinformation', 'multimedia'}


def copy_notices(items, source, destination):
    """Copy only declared, hash-verified licenses; never adopt local extra files."""
    copied = set()
    for item in items:
        name = item['filename']
        relative = Path(name)
        if (relative.is_absolute() or relative.as_posix() != name or '\\' in name
                or any(char in name for char in ':*?"<>|\0')
                or '..' in relative.parts or name.casefold() in copied):
            raise ValueError('许可证清单包含无效或重复路径。')
        path = source / relative
        if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
               for p in (path, *path.parents) if p.is_relative_to(source)):
            raise ValueError('许可证包含目录映射：' + name)
        if not path.is_file() or digest(path) != item['sha256']:
            raise ValueError('许可证校验失败：' + name)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if digest(target) != item['sha256']:
            raise ValueError('许可证在复制时变化：' + name)
        copied.add(name.casefold())


def trim_dependency_tests(site_packages):
    """Exclude NumPy/SciPy regression suites while retaining runtime/test helpers.

    Only fresh locked build outputs are passed here, never a developer/user
    environment. Keep _testutils, datasets, licenses and all non-test modules.
    """
    for name in ('numpy', 'scipy'):
        package = site_packages / name
        for directory in sorted(package.rglob('tests'), key=lambda path: len(path.parts), reverse=True):
            if directory.is_dir() and not directory.is_symlink():
                shutil.rmtree(directory)


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def copy_application(root, destination):
    """Copy tracked application code/resources and return the same sealed inventory.

    Only the formats currently shipped by the application are permitted. Local
    ignored/untracked files never become release inputs, even in a clean checkout.
    """
    names = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '-z', '--', 'linguaflow'], encoding='utf-8').split('\0')
    files = {}
    for name in sorted(filter(None, names)):
        relative = Path(name)
        if relative.suffix not in {'.py', '.mjs'}:
            raise ValueError('未声明的应用资源格式：' + name)
        source = root / relative
        if (not source.is_file() or any(path.is_symlink() or (
                hasattr(path, 'is_junction') and path.is_junction())
                for path in (source, *source.parents) if path.is_relative_to(root))):
            raise ValueError('应用源码缺失或包含目录映射：' + name)
        target = destination / relative.relative_to('linguaflow')
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = digest(source)
        shutil.copy2(source, target)
        if digest(target) != expected:
            raise ValueError('应用源码在复制时变化：' + name)
        files[relative.as_posix()] = expected
    if 'linguaflow/__init__.py' not in files:
        raise ValueError('缺少受版本控制的应用入口。')
    return files


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
