"""Verified portable assets and license extraction shared by platform builds."""
import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

QT_MODULES = {'QtCore', 'QtGui', 'QtWidgets', 'QtNetwork', 'QtOpenGL', 'QtOpenGLWidgets',
              'QtPrintSupport', 'QtSvg', 'QtMultimedia', 'QtWebChannel', 'QtWebEngineCore',
              'QtWebEngineWidgets'}
QT_PLUGIN_GROUPS = {'platforms', 'styles', 'imageformats', 'iconengines', 'tls',
                    'networkinformation', 'multimedia'}


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


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
