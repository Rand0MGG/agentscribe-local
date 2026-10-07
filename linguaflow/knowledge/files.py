"""Checked local paths and atomic companion files; user originals are never pruned."""
import json
from pathlib import Path
from uuid import uuid4


def checked_path(root, path):
    root, path = Path(root).resolve(), Path(path).absolute()
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents or root not in path.parents or '..' in path.parts:
        raise ValueError('知识数据必须位于当前录音库内。')
    cursor = path.absolute()
    while cursor != root:
        if cursor.is_symlink() or (hasattr(cursor, 'is_junction') and cursor.is_junction()):
            raise ValueError('不通过符号链接或快捷映射操作知识数据。')
        cursor = cursor.parent
    return resolved


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(root, path, value):
    path = checked_path(root, path)
    write_text(root, path, json.dumps(value, ensure_ascii=False, indent=2))


def write_text(root, path, value):
    path = checked_path(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = checked_path(root, path.parent / ('.' + uuid4().hex[:16] + '.tmp'))
    owned = False
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            owned = True
            stream.write(value)
        checked_path(root, path)
        temporary.replace(path)
    finally:
        if owned:
            temporary.unlink(missing_ok=True)
