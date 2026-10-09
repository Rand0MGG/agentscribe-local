"""Checked local paths and atomic companion files; user originals are never pruned."""
import hashlib
import json
import re
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


def material_cache(library, course_path, descriptor):
    """Resolve a published snapshot; descriptors without a snapshot retain the legacy layout."""
    document_id = descriptor.get('id', '')
    snapshot = descriptor.get('snapshot', '')
    if (not isinstance(document_id, str) or not re.fullmatch('[0-9a-f]{64}', document_id)
            or not isinstance(snapshot, str) or (snapshot and not re.fullmatch('[0-9a-f]{16}', snapshot))):
        raise ValueError('课件缓存位置无效，请重新导入。')
    base = course_path.parent / 'materials' / document_id
    return checked_path(library.root, base / 'snapshots' / snapshot if snapshot else base)


class FileChecks:
    """Task-local validation memo: retain hashes/JSON/lengths, never image buffers.

    A changed file identity, size or timestamp forces validation again. Parent link
    identities are checked too, so replacing a directory cannot bypass path checks.
    """
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.values = {}
        self.parents = {}

    @staticmethod
    def signature(path):
        try:
            stat = path.lstat()
        except FileNotFoundError:
            return None
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_mode

    def get(self, path, tag, load):
        path = checked_path(self.root, path)
        before = self.signature(path)
        key = (path, tag)
        if key not in self.values or self.values[key][0] != before:
            value = load(path)
            if self.signature(path) != before:
                raise ValueError('处理期间课件文件发生变化，请重试；旧结果保留。')
            self.values[key] = before, value
        for parent in path.parents:
            if parent == self.root:
                break
            stat = self.signature(parent)
            self.parents[parent] = None if stat is None else (stat[0], stat[1], stat[-1])
        return self.values[key][1]

    def json(self, path):
        return self.get(path, 'json', read_json)

    def digest(self, path):
        return self.get(path, 'sha256', lambda entry: hashlib.sha256(entry.read_bytes()).hexdigest())

    def entries(self, path):
        return self.get(path, 'readings', lambda entry: tuple(entry.glob('page-*.json')))

    def unchanged(self):
        for parent, expected in self.parents.items():
            stat = self.signature(parent)
            if (None if stat is None else (stat[0], stat[1], stat[-1])) != expected:
                return False
        return all(self.signature(path) == expected for (path, _), (expected, _) in self.values.items())


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
