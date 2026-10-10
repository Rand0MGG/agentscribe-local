"""Recording export formats and atomic publication, shared by desktop platforms."""
import os
import tempfile
from pathlib import Path

from .core import export_md, export_srt, export_txt

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
    path = Path(item['path'])
    text = FORMATS[item['format']][1](captions)
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
