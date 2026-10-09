"""Local full-page rasterization through DSH's independent LibreOffice Kit dependency."""
import asyncio
import hashlib
import shutil
import struct
import tempfile
from pathlib import Path

from ..process_platform import spawn_options, stop_tree
from ..runtime_paths import (
    DOCUMENT_RENDERER_VERSION,
    document_renderer,
    installation_command,
    python_environment,
)
from .files import checked_path, material_cache, read_json, write_json

RENDER_VERSION = 'libreoffice-kit-' + DOCUMENT_RENDERER_VERSION + '-144dpi-v1'
WEB_RENDER_VERSION = 'qt-static-pages-v2'
MAX_IMAGE_BYTES = 4 * 1024**2
MAX_RENDER_BYTES = 256 * 1024**2
MAX_PIXELS = 4 * 1024**2
NATIVE_SUFFIXES = ('.pdf', '.pptx')
OFFICE_SUFFIXES = ('.doc', '.docx', '.odt', '.xls', '.xlsx', '.ods', '.ppt', '.odp')
SHEET_SUFFIXES = ('.xls', '.xlsx', '.ods')
WEB_SUFFIXES = ('.html', '.htm', '.md', '.markdown', '.txt', '.csv', '.tsv')
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.ico', '.svg')
IMPORT_SUFFIXES = NATIVE_SUFFIXES + OFFICE_SUFFIXES + WEB_SUFFIXES + IMAGE_SUFFIXES


async def run_renderer(arguments):
    """Own one helper and its descendants; EOF cancels, timeout/cancellation always reaps."""
    process = await asyncio.create_subprocess_exec(*map(str, arguments), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        env=python_environment(), **spawn_options())
    try:
        if await asyncio.wait_for(process.wait(), 130):
            raise RuntimeError('课件页面生成失败，请检查文件、字体、资源和组件安装；原件与已保存内容保留。')
    finally:
        process.stdin.close()
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                stop_tree(process, force=True)
                await asyncio.wait_for(process.wait(), 5)


async def render_source(source, output, limit=1000, *, resource_source=None):
    """Render Office/PDF with Kit, web/text/images with an isolated Qt helper."""
    source, output = Path(source), Path(output)
    request = output.parent / 'request.json'
    if source.suffix.lower() in WEB_SUFFIXES + IMAGE_SUFFIXES:
        write_json(output.parent, request, {'source': str(source), 'output': str(output), 'limit': limit,
                                          'resource_source': str(resource_source or source)})
        await run_renderer(installation_command('linguaflow.knowledge.render_web', request))
        error = read_json(output.parent / 'error.json') if (output.parent / 'error.json').is_file() else {}
        if error:
            raise ValueError(error['message'])
        return read_json(output / 'manifest.json')
    node, entry = document_renderer()
    if read_json(entry.parent.parent / 'package.json').get('version') != DOCUMENT_RENDERER_VERSION:
        raise ValueError('课件渲染组件版本不匹配，请重新运行 scripts/install_documents.py。')
    options = {'inputPath': str(source), 'outputDir': str(output), 'dpi': 144,
               'maxPages': limit, 'maxPixels': MAX_PIXELS, 'maxDimension': 4096}
    if source.suffix.lower() not in SHEET_SUFFIXES:
        options['pages'] = 'all'
    write_json(output.parent, request, {'options': {'timeoutMs': 120000, 'maxInputBytes': 64 * 1024**2,
        'maxOutputBytes': MAX_RENDER_BYTES}, 'render': options})
    await run_renderer([node, Path(__file__).with_name('render_document.mjs'), entry, request])
    return read_json(output / 'manifest.json')


def normalize_pages(output, manifest, document_id):
    """Normalize complete Kit worksheet tiles and physical pages to portable ordered sources."""
    rows = manifest.get('images', [])
    if not 0 < len(rows) <= 1000:
        raise ValueError('课件页面为空或超过 1000 页预算，请按章节导入。')
    sheets = any('sheet' in row for row in rows)
    if not sheets and manifest.get('pageCount') != len(rows):
        raise ValueError('渲染结果未覆盖完整课件。')
    if sheets and len({row['sheet'] for row in rows}) != manifest.get('pageCount'):
        raise ValueError('渲染结果未覆盖全部可见工作表。')
    used = 0
    for page, row in enumerate(rows, 1):
        old = checked_path(output, output / row['path'])
        if not sheets and row.get('page') != page:
            raise ValueError('渲染页面顺序无效。')
        row['sha256'] = hashlib.sha256(old.read_bytes()).hexdigest()
        used += len(image_bytes(old, row['sha256']))
        new = output / f'page-{page:04d}.png'
        if old != new:
            old.replace(new)
        row.update(page=page, path=new.name)
    if used > MAX_RENDER_BYTES:
        raise ValueError('页面图片超过 256 MiB 预算，请按章节导入。')
    manifest.pop('inputPath', None)
    if sheets:
        manifest['sheetCount'] = manifest['pageCount']
    manifest.update(render_version=RENDER_VERSION, sourceSha256=document_id, pageCount=len(rows))
    return manifest


def image_bytes(path, expected):
    """Validate a bounded PNG before displaying/uploading; never accept remote image URLs."""
    path = Path(path)
    if not path.is_file() or not 24 <= path.stat().st_size <= MAX_IMAGE_BYTES:
        raise ValueError('页面图片缺失或超出 4 MiB 预算，请重新阅读课件。')
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('页面图片格式无效，请重新阅读课件。')
    width, height = struct.unpack('>II', data[16:24])
    if not width or not height or width * height > MAX_PIXELS or max(width, height) > 4096:
        raise ValueError('页面图片尺寸超出处理预算。')
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('页面图片校验失败，未发送模型请求；请重新阅读课件。')
    return data


def page_images(library, base, document_id, count, checks=None):
    """Return only a complete, portable, source-bound render cache, or raise."""
    directory = checked_path(library.root, base / 'pages')
    manifest = (checks.json if checks else read_json)(directory / 'manifest.json')
    if (manifest.get('render_version') != RENDER_VERSION or manifest.get('sourceSha256') != document_id
            or manifest.get('pageCount') != count or len(manifest.get('images', [])) != count):
        raise ValueError('页面渲染缓存未覆盖完整课件，请重新阅读。')
    if manifest.get('viewport') and manifest.get('layoutVersion') != WEB_RENDER_VERSION:
        raise ValueError('网页页面使用旧布局版本，请重新导入以保留固定栏遮挡的内容。')
    used = 0
    for page, row in enumerate(manifest['images'], 1):
        if row.get('page') != page or row.get('path') != f'page-{page:04d}.png':
            raise ValueError('页面渲染顺序或路径无效，请重新阅读。')
        path = checked_path(library.root, directory / row['path'])
        used += (checks.get(path, row['sha256'], lambda entry: len(image_bytes(entry, row['sha256'])))
                 if checks else len(image_bytes(path, row['sha256'])))
    if used > MAX_RENDER_BYTES:
        raise ValueError('页面渲染缓存超过 256 MiB 预算，请按章节导入。')
    return manifest


async def render_material(library, course_path, descriptor, count):
    """Render all pages once, reuse verified caches, cancel and reap the owned process."""
    base = material_cache(library, course_path, descriptor)
    source = checked_path(library.root, course_path.parent / 'materials' / descriptor['id'] / ('original' + descriptor['suffix']))
    if hashlib.sha256(source.read_bytes()).hexdigest() != descriptor['id']:
        raise ValueError('课件原件已变化，请重新导入。')
    try:
        return page_images(library, base, descriptor['id'], count)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # Regenerate only the derived cache; preserve the original and completed readings.
    if descriptor['suffix'] not in NATIVE_SUFFIXES:
        raise ValueError('课件页面快照缺失或损坏，请重新导入原文件；旧笔记保留。')
    with tempfile.TemporaryDirectory(prefix='.render-', dir=base) as work:
        work = checked_path(library.root, work)
        output = work / 'pages'
        manifest = await render_source(source, output, count)
        if (manifest.get('sourceSha256') != descriptor['id'] or manifest.get('pageCount') != count
                or len(manifest.get('images', [])) != count):
            raise ValueError('渲染结果未覆盖完整课件；没有发送页面。')
        manifest = normalize_pages(output, manifest, descriptor['id'])
        if hashlib.sha256(source.read_bytes()).hexdigest() != descriptor['id']:
            raise ValueError('渲染期间课件变化或输出超出预算；没有发送页面。')
        directory = checked_path(library.root, base / 'pages')
        directory.mkdir(exist_ok=True)
        for row in manifest['images']:
            shutil.copyfile(output / row['path'], work / row['path'])
            (work / row['path']).replace(directory / row['path'])
        write_json(library.root, directory / 'manifest.json', manifest)
        return page_images(library, base, descriptor['id'], count)
