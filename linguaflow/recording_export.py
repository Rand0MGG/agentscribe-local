"""Recording export formats and atomic publication, shared by desktop platforms."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from .core import export_md, export_srt, export_txt, source_is_final, srt_time
from .storage_io import Directory, atomic_write, file_digest, identity

FORMATS = {'srt': ('SubRip 字幕 (*.srt)', export_srt),
           'txt': ('纯文本 (*.txt)', export_txt),
           'md': ('Markdown 文档 (*.md)', export_md)}


@dataclass(frozen=True)
class ExportReceipt:
    parent: tuple[int, int]
    file: tuple[int, int]
    digest: str


def check_export(path, receipt):
    """Read in bounded chunks, and reject replaced directories/files or mappings."""
    path = Path(path)
    with Directory(path.parent) as directory:
        if tuple(identity(directory.info)) != receipt.parent:
            raise OSError('备份目录已变化，请重新备份再关闭。')
        file_id, digest = file_digest(directory, path.name)
        if tuple(file_id) != receipt.file or digest != receipt.digest:
            raise ValueError('备份已被修改，请重新备份再关闭。')


def export_target(path, selected_filter):
    """Honor an explicit supported suffix; otherwise append the selected format suffix."""
    path = Path(path)
    kind = path.suffix.lower().lstrip('.')
    if kind not in FORMATS:
        kind = next((key for key, (label, _) in FORMATS.items() if label == selected_filter), 'srt')
        path = Path(str(path) + '.' + kind)
    return path, kind


def write_export(item, captions, state=None):
    """RecordingSaver callback: publish only a complete UTF-8 document; raise on failure."""
    text = FORMATS[item['format']][1](captions)
    return _write_text(Path(item['path']), text, item.get('parent_identity'))


def write_recovery(item, captions, state=None):
    """Preserve every recognized word without giving drafts ordinary export status."""
    rows = ['录音文字恢复备份', '包含草稿和未完成译文，请对照原录音核对。',
            '不包含音频，也不表示原录音已成功保存。', '录音：' + item.get('name', ''), '']
    for caption in sorted(captions, key=lambda c: (c.start, c.id)):
        rows += [f'[{srt_time(caption.start)} → {srt_time(caption.end)}] '
                 + ('定稿原文' if source_is_final(caption) else '草稿原文'), caption.source]
        if caption.translation:
            label = ('过期译文，原文已更新' if caption.translation_source and caption.translation_source != caption.source
                     else '初译，未完成' if caption.translation_phase == 'initial' or not source_is_final(caption)
                     else '已有译文')
            rows += [label, caption.translation]
        if caption.error:
            rows.append('未完成说明：' + caption.error)
        rows.append('')
    return _write_text(Path(item['path']), '\n'.join(rows), item.get('parent_identity'))


def _write_text(path, text, expected_parent=None):
    if expected_parent is None:
        with Directory(path.parent) as directory:
            expected_parent = identity(directory.info)
    content = text.encode('utf-8-sig')
    digest = hashlib.sha256(content).hexdigest()
    owned = atomic_write(path, content, expected_parent=expected_parent)
    receipt = ExportReceipt(tuple(expected_parent), tuple(owned), digest)
    check_export(path, receipt)
    return receipt
