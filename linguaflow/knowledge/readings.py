"""Page reading provenance and coverage; native evidence is never replaced by model prose."""
from dataclasses import asdict

from .files import checked_path, material_cache, read_json, write_json
from .glossary import term_text
from .rendering import RENDER_VERSION, image_bytes
from .schemas import DEFAULT_TEXT_MODEL, DocumentBlock, fingerprint

READING_VERSION = 'full-page-vision-v1'


def reading_path(library, course_path, document_id, page=None):
    directory = checked_path(library.root, course_path.parent / 'materials' / document_id / 'readings')
    return directory if page is None else checked_path(library.root, directory / f'page-{page:04d}.json')


def load_readings(library, course_path, document_id, checks=None):
    path = reading_path(library, course_path, document_id)
    cache = {}
    for entry in checks.entries(path) if checks else path.glob('page-*.json'):
        if len(cache) >= 1000:
            raise ValueError('课件阅读记录超出页数预算。')
        try:
            row = (checks.json if checks else read_json)(checked_path(library.root, entry))
            if isinstance(row, dict) and isinstance(row.get('id'), str):
                cache[row['id']] = row
        except (OSError, ValueError, TypeError):
            continue
    return cache


def reading_key(block, image_hash):
    return fingerprint([READING_VERSION, RENDER_VERSION, DEFAULT_TEXT_MODEL, asdict(block), image_hash])


def validate_reading(block, row, image_hash):
    if (row.get('id') != block.id or row.get('key') != reading_key(block, image_hash)
            or row.get('hash') != fingerprint(row.get('result'))):
        raise ValueError('本页阅读与课件版本不一致，请重新阅读。')
    result = row['result']
    if (not isinstance(result.get('text'), str) or not 0 < len(result['text']) <= 12000
            or not isinstance(result.get('terms'), list) or len(result['terms']) > 50
            or not isinstance(result.get('uncertainties'), list) or len(result['uncertainties']) > 10
            or any(not isinstance(value, str) or len(value) > 500 for value in result['uncertainties'])):
        raise ValueError('本页阅读缓存无效，请重新阅读。')
    evidence = {block.id: block.text, block.id + ':visual': result['text']}
    for term in result['terms']:
        refs = term.get('refs', [])
        term_text(term.get('canonical'))
        if not isinstance(term.get('aliases'), list) or len(term['aliases']) > 3:
            raise ValueError('本页术语别名缓存无效，请重新阅读。')
        for alias in term['aliases']:
            term_text(alias)
        if (not isinstance(refs, list) or not 1 <= len(refs) <= 3
                or any(ref.get('id') not in evidence or not ref.get('quote')
                       or ref['quote'] not in evidence[ref['id']] for ref in refs)
                or not any(term['canonical'].casefold() in ref['quote'].casefold() for ref in refs)):
            raise ValueError('本页术语缓存引用无效，请重新阅读。')
    return result


def save_reading(library, course_path, block, image_hash, result):
    row = {'id': block.id, 'key': reading_key(block, image_hash), 'hash': fingerprint(result), 'result': result}
    validate_reading(block, row, image_hash)
    write_json(library.root, reading_path(library, course_path, block.document_id, block.page), row)


def visual_blocks(library, course_path, native, documents=(), checks=None):
    """Return valid visual sources and per-document coverage, including image-only pages."""
    blocks, coverage = [], {}
    for document_id in dict.fromkeys(block.document_id for block in native):
        pages = [block for block in native if block.document_id == document_id]
        progress = coverage[document_id] = {'total': len(pages), 'read': 0, 'uncertain': 0, 'complete': False}
        try:
            cache = load_readings(library, course_path, document_id, checks)
        except (ValueError, TypeError):
            cache = {}
        descriptor = next((row for row in documents if row['id'] == document_id), {'id': document_id})
        base = checked_path(library.root, material_cache(library, course_path, descriptor) / 'pages')
        try:
            manifest_path = base / 'manifest.json'
            manifest = (checks.get(manifest_path, 'json', lambda entry: read_json(entry) if entry.is_file() else {})
                        if checks else read_json(manifest_path) if manifest_path.is_file() else {})
        except (ValueError, TypeError):
            manifest = {}
        if (manifest.get('render_version') != RENDER_VERSION or manifest.get('sourceSha256') != document_id
                or manifest.get('pageCount') != len(pages) or len(manifest.get('images', [])) != len(pages)):
            continue
        for block, image in zip(pages, manifest['images']):
            if block.id not in cache:
                continue
            path = checked_path(library.root, base / f'page-{block.page:04d}.png')
            if image.get('page') != block.page or image.get('path') != path.name:
                continue
            try:
                if checks:
                    checks.get(path, image['sha256'], lambda entry: len(image_bytes(entry, image['sha256'])))
                else:
                    image_bytes(path, image['sha256'])
                result = validate_reading(block, cache[block.id], image['sha256'])
            except (OSError, ValueError, KeyError, TypeError):
                continue  # Damaged/stale derived pages are incomplete; never silently considered read.
            progress['read'] += 1
            progress['uncertain'] += bool(result['uncertainties'])
            text = result['text']
            if result['uncertainties']:
                text += '\n\n模型标记待核对：' + '；'.join(result['uncertainties'])
            blocks.append(DocumentBlock(block.id + ':visual', document_id, block.page, block.title,
                text, fingerprint([cache[block.id]['key'], cache[block.id]['hash']]),
                bool(result['uncertainties']), 'visual', str(path), image['sha256']))
        progress['complete'] = progress['read'] == progress['total']
    return blocks, coverage
