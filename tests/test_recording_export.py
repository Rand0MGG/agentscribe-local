"""Export preserves finalized bilingual content and existing files on failure."""
from pathlib import Path

import pytest

from linguaflow.core import Caption, export_md, export_txt
from linguaflow.recording_export import FORMATS, export_target, write_export


def captions():
    return [Caption(1, 1.25, 2.75, 'Hello *world*', 'en', '你好', translation_phase='initial'),
            Caption(2, 3, 4, 'Draft', 'en', final=False),
            Caption(3, 4, 5, 'Unconfirmed', 'en', asr_final=False),
            Caption(4, 5, 6, ' ', 'en'),
            Caption(5, 7, 8, 'Final', 'en', '最终', translation_phase='final')]


def test_text_and_markdown_preserve_finality_translation_and_literal_text():
    source = captions()
    assert export_txt(source) == 'Hello *world*\n[初译] 你好\n\nFinal\n最终'
    md = export_md(source)
    assert 'Hello \\*world\\*' in md
    assert '**初译：** 你好' in md and '**译文：** 最终' in md
    assert '00:00:01.250 → 00:00:02.750' in md
    assert 'Draft' not in md and 'Unconfirmed' not in md
    source[0].source = '# 标题\n<script>test</script>\n`code`'
    assert '\\# 标题  \n\\<script\\>' in export_md(source)
    assert '\\`code\\`' in export_md(source)


@pytest.mark.parametrize('suffix', FORMATS)
def test_all_formats_write_unicode_and_keep_existing_target_on_publish_failure(tmp_path, monkeypatch, suffix):
    target = tmp_path / ('中文录音.' + suffix)
    item = dict(path=str(target), format=suffix)
    write_export(item, captions())
    assert '你好' in target.read_text(encoding='utf-8-sig')
    before = target.read_bytes()
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr('linguaflow.recording_export.os.replace', fail)
    with pytest.raises(OSError, match='disk full'):
        write_export(item, [])
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_extension_matches_content_and_missing_suffix_uses_selected_format():
    assert export_target('字幕', FORMATS['md'][0]) == (Path('字幕.md'), 'md')
    assert export_target('字幕.TXT', FORMATS['md'][0]) == (Path('字幕.TXT'), 'txt')
    assert export_target('字幕.other', FORMATS['txt'][0]) == (Path('字幕.other.txt'), 'txt')
