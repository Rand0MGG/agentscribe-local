"""Recording-owned course binding and immutable ASR context, without runtime imports."""
import re

from .files import checked_path, read_json, write_json
from .glossary import context_text
from .schemas import SCHEMA_VERSION


def manifest_path(library, identifier):
    return checked_path(library.root, library.directory(identifier) / 'knowledge' / 'manifest.json')


def read_manifest(library, identifier):
    path = manifest_path(library, identifier)
    if not path.exists():
        return {'schema_version': SCHEMA_VERSION, 'session_id': identifier, 'course_id': '',
                'asr_context': {}, 'notes_cloud': False}
    value = read_json(path)
    if value.get('schema_version') != SCHEMA_VERSION or value.get('session_id') != identifier:
        raise ValueError('课程关联格式或录音归属无效，原文件未修改。')
    value.setdefault('course_id', '')
    value.setdefault('notes_cloud', False)
    value.setdefault('asr_context', {})
    if (type(value.get('notes_cloud', False)) is not bool
            or not isinstance(value.get('course_id'), str)
            or value['course_id'] and not re.fullmatch('[0-9a-f]{32}', value['course_id'])):
        raise ValueError('课程关联或上传许可格式无效；不会因损坏配置启用云端。')
    context_text(value.get('asr_context', {}))
    return value


def write_manifest(library, value):
    write_json(library.root, manifest_path(library, value['session_id']), value)


def session_context(library, identifier):
    """Return a validated small snapshot; no parsing, model or database on the ASR path."""
    value = read_manifest(library, identifier)
    if not value['course_id']:
        from .glossary import compile_context
        from .materials import course_for_folder
        from .schemas import Term
        item = next(row for row in library.index['sessions'] if row['id'] == identifier)
        _, course = course_for_folder(library, item['folder'])
        if course:
            value['course_id'] = course['id']
            value['asr_context'] = compile_context((Term(**row) for row in course['terms']),
                ((row['id'], row['version']) for row in course['documents'])).to_dict()
            write_manifest(library, value)
    return value['asr_context']
