"""Native PDF/PPTX evidence extraction, bounded imports and stable course identity."""
import hashlib
import posixpath
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from .files import checked_path, material_cache, read_json, write_json
from .glossary import term_text
from .rendering import (
    IMPORT_SUFFIXES,
    NATIVE_SUFFIXES,
    RENDER_VERSION,
    normalize_pages,
    page_images,
    render_source,
)
from .schemas import SCHEMA_VERSION, DocumentBlock, fingerprint

PARSER_VERSION = 'native-1-pypdf-6.19.0'
RENDERED_PARSER = 'page-snapshot-1-' + RENDER_VERSION
MAX_FILE_BYTES = 64 * 1024**2
MAX_XML_BYTES = 64 * 1024**2
MAX_PAGES = 1000
MAX_TEXT_BYTES = 4 * 1024**2


def cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('材料处理已取消。')


def course_for_folder(library, folder_id, create=False):
    directory = library.directory(folder_id)
    path = checked_path(library.root, directory / '.agentscribe' / 'course.json')
    if path.exists():
        data = read_json(path)
        if data.get('schema_version') != SCHEMA_VERSION or not re.fullmatch('[0-9a-f]{32}', data.get('id', '')):
            raise ValueError('课程资料格式无效，请检查 course.json；原件未修改。')
        if (type(data.get('material_cloud', False)) is not bool
                or type(data.get('material_images_cloud', False)) is not bool or not isinstance(data.get('documents'), list)
                or not isinstance(data.get('terms'), list) or len(data['terms']) > 200):
            raise ValueError('课程材料或上传许可格式无效；不会因损坏配置启用云端。')
        for row in data['terms']:
            if (not isinstance(row, dict) or type(row.get('approved', False)) is not bool
                    or not isinstance(row.get('aliases', []), list)
                    or not isinstance(row.get('evidence_ids', []), list)
                    or row.get('origin', 'material') not in ('material', 'manual')):
                raise ValueError('术语审核格式无效，请修正课程资料。')
            term_text(row['canonical'])
            for alias in row.get('aliases', []):
                term_text(alias)
    elif create:
        marker = directory / library.folder_file
        stable_id = read_json(marker).get('id', '') if marker.is_file() else ''
        data = {'schema_version': SCHEMA_VERSION,
                'id': stable_id if re.fullmatch('[0-9a-f]{32}', stable_id) else uuid4().hex,
                'documents': [], 'terms': [], 'material_cloud': False}
        write_json(library.root, path, data)
    else:
        return None, None
    return path, data


def locate_course(library, course_id):
    library.refresh()
    for folder in library.index['folders']:
        try:
            path, data = course_for_folder(library, folder['id'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if data is not None and data['id'] == course_id:
            return path, data
    raise FileNotFoundError('关联的课程资料暂不可用，请恢复课程文件夹或重新关联课程。')


def _pptx_pages(path, cancel):
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if any(item.filename.startswith('/') or '..' in item.filename.split('/')
                   or (item.external_attr >> 16) & 0o170000 == 0o120000 for item in entries):
                raise ValueError('课件压缩结构包含不安全路径或符号链接。')
            xml_entries = [item for item in entries if item.filename.endswith(('.xml', '.rels'))]
            if sum(item.file_size for item in xml_entries) > MAX_XML_BYTES or len(entries) > 20000:
                raise ValueError('课件展开后的 XML 超出处理预算，请拆分课件。')
            if len({item.filename for item in entries}) != len(entries):
                raise ValueError('课件压缩结构存在重复条目。')
            types = archive.read('[Content_Types].xml')
            if b'presentationml.presentation.main+xml' not in types:
                raise ValueError('文件不是受支持的 PPTX 演示文稿。')
            links = {item.attrib['Id']: item.attrib for item in ET.fromstring(
                archive.read('ppt/_rels/presentation.xml.rels'))}
            slides = ET.fromstring(archive.read('ppt/presentation.xml')).find(
                '{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst')
            if slides is None or len(slides) > MAX_PAGES:
                raise ValueError('课件页数为空或超出处理预算。')
            for slide in slides:
                cancelled(cancel)
                link = links[slide.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
                target = posixpath.normpath(posixpath.join('ppt', link['Target']))
                if link.get('TargetMode') == 'External' or not target.startswith('ppt/slides/'):
                    raise ValueError('课件幻灯片引用越界。')
                document = ET.fromstring(archive.read(target))
                paragraphs = document.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}p')
                text = '\n'.join(''.join(p.itertext()) for p in paragraphs)
                # Pictures, charts and math require human review; never claim OCR.
                review = any(item.tag.rsplit('}', 1)[-1] in ('pic', 'graphicFrame', 'oMath', 'oMathPara')
                             for item in document.iter())
                yield text, review or not text.strip()
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError('PPTX 结构无法读取，请检查文件是否完整。') from exc


def extract_material(path, cancel=None):
    """Return page blocks; extraction errors do not imply entire-file success."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('课件不存在或超过本次 64 MiB 输入预算，请拆分材料。')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    version = fingerprint([digest, PARSER_VERSION])
    if path.suffix.lower() == '.pptx':
        pages = _pptx_pages(path, cancel)
    elif path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        with path.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise ValueError('文件内容不是 PDF。')
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('请先在本机解密 PDF 后再导入。')
        if not 0 < len(reader.pages) <= MAX_PAGES:
            raise ValueError('PDF 页数为空或超出处理预算。')
        def pdf_pages():
            for page in reader.pages:
                cancelled(cancel)
                try:
                    value = page.extract_text() or ''
                    resources = page.get('/Resources', {})
                    resources = resources.get_object() if hasattr(resources, 'get_object') else resources
                    objects = resources.get('/XObject', {})
                    objects = objects.get_object() if hasattr(objects, 'get_object') else objects
                    image = any(obj.get_object().get('/Subtype') == '/Image' for obj in objects.values())
                    yield value, image or not value.strip()
                except Exception:
                    yield '', True
        pages = pdf_pages()
    else:
        raise ValueError('此格式需通过课程资料的后台导入处理。')
    blocks, used = [], 0
    for page, (text, review) in enumerate(pages, 1):
        cancelled(cancel)
        text = text.strip()
        used += len(text.encode('utf-8'))
        if used > MAX_TEXT_BYTES:
            raise ValueError('提取文本超过 4 MiB 预算，请分批导入。')
        title = text.splitlines()[0][:120] if text else f'第 {page} 页（待核对）'
        blocks.append(DocumentBlock(f'{digest}:{page}', digest, page, title, text, version, review))
    return {'id': digest, 'version': version, 'name': path.name, 'parser': PARSER_VERSION,
            'suffix': path.suffix.lower(), 'blocks': [asdict(block) for block in blocks]}


def import_material(library, folder_id, path, cancel=None, *, prepared=None, artifacts=None):
    """Publish a native import or a validated rendered snapshot; no cloud calls or Qt imports."""
    course_path, course = course_for_folder(library, folder_id, create=True)
    source = Path(path)
    if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('课件不存在或超过本次 64 MiB 输入预算。')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    base = checked_path(library.root, course_path.parent / 'materials' / digest)
    descriptor = next((item for item in course['documents'] if item['id'] == digest), None)
    cached = material_cache(library, course_path, descriptor) / 'blocks.json' if descriptor else base / 'blocks.json'
    document = prepared
    if document is None and cached.is_file():
        try:
            candidate = read_json(cached)
            if (candidate.get('id') == digest and candidate.get('parser') == PARSER_VERSION
                    and candidate.get('suffix') == source.suffix.lower()
                    and candidate.get('version') == fingerprint([digest, PARSER_VERSION])
                    and descriptor and descriptor.get('blocks_hash') == fingerprint(candidate['blocks'])):
                document = candidate
        except (ValueError, KeyError, TypeError):
            pass
    if document is None:
        document = extract_material(source, cancel)
        cancelled(cancel)
    if document['id'] != digest:
        raise ValueError('导入期间课件发生变化，请重新导入。')
    # Validate aggregate limits before replacing any valid original/cache/snapshot.
    course = read_json(course_path)
    retained = {**course, 'documents': [item for item in course['documents'] if item['id'] != digest]}
    existing = read_blocks(library, course_path, retained)
    if len(existing) + len(document['blocks']) > MAX_PAGES:
        raise ValueError('本课程超过 1000 页处理预算，请按课程章节分组；已导入材料保留。')
    if (sum(len(block.text.encode('utf-8')) for block in existing)
            + sum(len(block['text'].encode('utf-8')) for block in document['blocks']) > MAX_TEXT_BYTES):
        raise ValueError('本课程文本超过 4 MiB 预算，请按课程章节分组；已导入材料保留。')
    original = checked_path(library.root, base / ('original' + source.suffix.lower()))
    if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest() != digest:
        original.parent.mkdir(parents=True, exist_ok=True)
        temporary = original.with_name('.import-' + uuid4().hex)
        try:
            shutil.copyfile(source, temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise ValueError('导入期间课件发生变化，请重新导入。')
            cancelled(cancel)
            temporary.replace(original)
        finally:
            temporary.unlink(missing_ok=True)
    cancelled(cancel)
    return _publish_document(library, course_path, document, artifacts, cancel)


def _publish_document(library, course_path, document, artifacts, cancel):
    """Build an immutable version before the single atomic course-pointer publication.

    Killing/cancelling the worker at any point leaves either the old complete version or
    the new complete version readable. Unreferenced versions are retained, never pruned.
    """
    document = {key: value for key, value in document.items() if key != 'snapshot'}
    descriptor = {**{key: document[key] for key in ('id', 'version', 'name', 'suffix', 'parser')},
                  'blocks_hash': fingerprint(document['blocks']), 'snapshot': fingerprint(document)[:16]}
    destination = material_cache(library, course_path, descriptor)
    if destination.exists():
        try:
            read_blocks(library, course_path, {'documents': [descriptor]})
        except (OSError, ValueError, KeyError, TypeError):
            # Repair corrupted derived data without overwriting a published directory.
            descriptor['snapshot'] = fingerprint([document, uuid4().hex])[:16]
            destination = material_cache(library, course_path, descriptor)
    if not destination.exists():
        destination.mkdir(parents=True)
        if artifacts is not None:
            for name in ('pages', 'resources'):
                if (artifacts / name).exists():
                    shutil.copytree(artifacts / name, destination / name)
        cancelled(cancel)
        write_json(library.root, destination / 'blocks.json', document)
    read_blocks(library, course_path, {'documents': [descriptor]})
    cancelled(cancel)
    # Reload last, preserving approvals made while parsing/rendering was in progress.
    course = read_json(course_path)
    course['documents'] = [item for item in course['documents'] if item['id'] != document['id']] + [descriptor]
    write_json(library.root, course_path, course)
    return {**document, 'snapshot': descriptor['snapshot']}


async def import_document(library, folder_id, path):
    """Import all supported formats in the worker's cancellable owned task."""
    source = Path(path)
    if source.suffix.lower() not in IMPORT_SUFFIXES:
        raise ValueError('课件格式不支持，请选择 PDF、Office、网页、文本或图片。')
    if source.suffix.lower() in NATIVE_SUFFIXES:
        return import_material(library, folder_id, source)
    if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('课件不存在或超过本次 64 MiB 输入预算。')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    course_path, _ = course_for_folder(library, folder_id, create=True)
    directory = checked_path(library.root, course_path.parent / 'materials')
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.import-', dir=directory) as temporary:
        work = checked_path(library.root, temporary)
        snapshot = work / ('source' + source.suffix.lower())
        shutil.copyfile(source, snapshot)
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
            raise ValueError('导入期间课件发生变化，请重新导入。')
        # Render an immutable input; web assets resolve against the selected file's addresses.
        manifest = await render_source(snapshot, work / 'pages', resource_source=source)
        if manifest.get('sourceSha256', digest) != digest:
            raise ValueError('生成的课件页面与原件版本不一致，请重新导入。')
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('导入期间课件发生变化，请重新导入。')
        texts = manifest.pop('native_text', [])
        resources = manifest.pop('resources', [])
        manifest = normalize_pages(work / 'pages', manifest, digest)
        write_json(library.root, work / 'pages' / 'manifest.json', manifest)
        version = fingerprint([digest, RENDERED_PARSER, fingerprint(manifest), resources])
        blocks, used = [], 0
        for page, image in enumerate(manifest['images'], 1):
            text = texts[page-1] if texts else ''
            used += len(text.encode('utf-8'))
            if used > MAX_TEXT_BYTES:
                raise ValueError('提取文本超过 4 MiB 预算，请按章节导入。')
            title = (f"工作表 {image['sheet']} · {image['range']} · 分片 {image['index']}" if 'sheet' in image else
                     f"网页分片 {page} · x={image['rectangle']['x']}, y={image['rectangle']['y']}"
                     if manifest.get('viewport') else
                     '图片（多帧仅静态首帧）' if manifest.get('staticFrame') else
                     text.splitlines()[0][:120] if text.strip() else f'第 {page} 页（原页待阅读）')
            blocks.append(asdict(DocumentBlock(f'{digest}:{page}', digest, page, title, text, version,
                not text.strip() or bool(manifest.get('missingFonts')))))
        document = {'id': digest, 'version': version, 'name': source.name, 'suffix': source.suffix.lower(),
                    'parser': RENDERED_PARSER, 'blocks': blocks, 'render_hash': fingerprint(manifest), 'resources': resources}
        return import_material(library, folder_id, source, prepared=document, artifacts=work)


def read_blocks(library, course_path, course, checks=None):
    blocks = []
    for item in course.get('documents', []):
        if (not re.fullmatch('[0-9a-f]{64}', item.get('id', ''))
                or item.get('parser') not in (PARSER_VERSION, RENDERED_PARSER) or item.get('suffix') not in IMPORT_SUFFIXES):
            raise ValueError('材料版本或位置无效，请重新导入。')
        base = material_cache(library, course_path, item)
        path = checked_path(library.root, base / 'blocks.json')
        document = (checks.json if checks else read_json)(path)
        if document.get('id') != item['id'] or document.get('version') != item['version']:
            raise ValueError('课件来源版本不一致，请重新导入。')
        if item.get('blocks_hash') != fingerprint(document['blocks']):
            raise ValueError('课件文本缓存已变化，请重新导入。')
        original = checked_path(library.root, course_path.parent / 'materials' / item['id'] / ('original' + item['suffix']))
        if (checks.digest(original) if checks else hashlib.sha256(original.read_bytes()).hexdigest()) != item['id']:
            raise ValueError('课件原件校验失败，请重新导入；旧笔记保留。')
        if not 0 < len(document['blocks']) <= MAX_PAGES:
            raise ValueError('课件缓存页数无效。')
        if item['parser'] == RENDERED_PARSER:
            manifest = page_images(library, base, item['id'], len(document['blocks']), checks)
            resources = document.get('resources', [])
            if (len(resources) > 64 or fingerprint(manifest) != document.get('render_hash')
                    or item['version'] != fingerprint([item['id'], RENDERED_PARSER, fingerprint(manifest), resources])):
                raise ValueError('课件页面或资源版本不一致，请重新导入；旧笔记保留。')
            for resource in resources:
                path = checked_path(library.root, base / 'resources' / resource['path'])
                if (not path.is_file() or path.stat().st_size > 4*1024**2
                        or (checks.digest(path) if checks else hashlib.sha256(path.read_bytes()).hexdigest()) != resource['sha256']):
                    raise ValueError('网页资源快照已变化，请重新导入；旧笔记保留。')
        for page, value in enumerate(document['blocks'], 1):
            block = DocumentBlock(**value)
            if (block.id != f'{item["id"]}:{page}' or block.document_id != item['id'] or block.page != page
                    or block.version != item['version'] or not isinstance(block.text, str)
                    or not isinstance(block.title, str) or block.evidence_type != 'native'
                    or block.image_path or block.image_hash):
                raise ValueError('课件缓存来源标识无效。')
            blocks.append(block)
    if len(blocks) > MAX_PAGES:
        raise ValueError('本课程超过 1000 页处理预算，请按课程章节分组。')
    if sum(len(block.text.encode('utf-8')) for block in blocks) > MAX_TEXT_BYTES:
        raise ValueError('本课程文本超过 4 MiB 处理预算，请按课程章节分组。')
    return blocks
