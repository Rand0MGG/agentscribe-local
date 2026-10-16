"""Recording export formats and atomic publication, shared by desktop platforms."""
import os
import tempfile
from pathlib import Path

from .core import export_md, export_srt, export_txt, source_is_final, srt_time

FORMATS = {'srt': ('SubRip 字幕 (*.srt)', export_srt),
           'txt': ('纯文本 (*.txt)', export_txt),
           'md': ('Markdown 文档 (*.md)', export_md)}


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
    _write_text(Path(item['path']), text)


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
    _write_text(Path(item['path']), '\n'.join(rows))


def _write_text(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text.encode('utf-8-sig'))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
