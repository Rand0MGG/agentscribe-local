"""Export preserves finalized bilingual content and existing files on failure."""
from pathlib import Path

import pytest

from linguaflow.core import Caption, export_md, export_srt, export_txt, srt_time
from linguaflow.recording_export import FORMATS, export_target, write_export


def captions():
    return [Caption(1, 1.25, 2.75, 'Hello *world*', 'en', '你好', translation_phase='initial'),
            Caption(2, 3, 4, 'Draft', 'en', final=False),
            Caption(3, 4, 5, 'Unconfirmed', 'en', asr_final=False),
            Caption(4, 5, 6, ' ', 'en'),
            Caption(5, 7, 8, 'Final', 'en', '最终', translation_phase='final')]


@pytest.mark.p2
def test_text_and_markdown_preserve_finality_translation_and_literal_text():
    assert srt_time(3599.9996) == "01:00:00,000"
    assert export_srt([Caption(7, 1.25, 2.75, "Hello", "en", "你好")]) == (
        "1\n00:00:01,250 --> 00:00:02,750\nHello\n你好\n"
    )
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


@pytest.mark.p2
@pytest.mark.parametrize('suffix', FORMATS)
def test_all_formats_write_unicode(tmp_path, suffix):
    target = tmp_path / ('中文录音.' + suffix)
    item = dict(path=str(target), format=suffix)
    write_export(item, captions())
    text = target.read_text(encoding='utf-8-sig')
    assert '你好' in text and 'Final' in text
    assert 'Draft' not in text and 'Unconfirmed' not in text


@pytest.mark.p0
@pytest.mark.parametrize('suffix', FORMATS)
def test_publish_failure_preserves_existing_export_and_cleans_temp(tmp_path, monkeypatch, suffix):
    target = tmp_path / ('中文录音.' + suffix)
    target.write_bytes(b'existing user export')
    item = dict(path=str(target), format=suffix)
    before = target.read_bytes()
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr('linguaflow.recording_export.os.replace', fail)
    with pytest.raises(OSError, match='disk full'):
        write_export(item, [])
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.p2
def test_extension_matches_content_and_missing_suffix_uses_selected_format():
    assert export_target('字幕', FORMATS['md'][0]) == (Path('字幕.md'), 'md')
    assert export_target('字幕.TXT', FORMATS['md'][0]) == (Path('字幕.TXT'), 'txt')
    assert export_target('字幕.other', FORMATS['txt'][0]) == (Path('字幕.other.txt'), 'txt')


@pytest.mark.p1
def test_recovery_includes_drafts_and_stale_translations(tmp_path):
    from linguaflow.recording_export import write_recovery
    target = tmp_path / '全部文字.txt'
    source = captions()
    source[1].translation = '旧译文'
    source[1].translation_source = 'previous draft'
    write_recovery({'path': str(target), 'name': '中文课堂'}, source)
    text = target.read_text(encoding='utf-8-sig')
    assert all(c.source in text for c in source)
    assert '草稿原文' in text and '旧译文' in text and '过期译文' in text and '不包含音频' in text


@pytest.mark.p0
def test_recovery_publish_failure_preserves_existing_file_and_cleans_temp(tmp_path, monkeypatch):
    from linguaflow.recording_export import write_recovery
    target = tmp_path / '全部文字.txt'
    target.write_bytes(b'existing recovery text')
    before = target.read_bytes()
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr('linguaflow.recording_export.os.replace', fail)
    with pytest.raises(OSError, match='disk full'):
        write_recovery({'path': str(target)}, [])
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]
