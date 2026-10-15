"""Windows temporary 8.3 aliases must not look like out-of-library writes."""
import asyncio
import ctypes
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from linguaflow.knowledge import rendering
from linguaflow.knowledge.files import file_path, write_json


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows 8.3 temporary path regression')
def test_render_temp_short_alias_is_canonicalized_before_checked_writes(tmp_path, monkeypatch):
    work = tmp_path / 'Temporary render workspace with spaces'
    work.mkdir()
    get_short = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
    get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    get_short.restype = ctypes.c_uint32
    size = get_short(str(work), None, 0)
    if not size:
        pytest.skip('Windows volume does not expose a short path')
    buffer = ctypes.create_unicode_buffer(size)
    assert get_short(str(work), buffer, size)
    short = Path(buffer.value)
    if short == work.resolve():
        pytest.skip('8.3 name generation is unavailable on this volume')
    assert short.samefile(work)

    @contextmanager
    def temporary_directory(**kwargs):
        yield str(short)

    async def renderer(source, output, limit, *, resource_source=None):
        # Exercise the real ownership check and atomic write at the renderer boundary.
        write_json(output.parent, output.parent / 'request.json', {'limit': limit})
        output.mkdir()
        (output / 'page-0001.png').write_bytes(b'fixture page')
        assert source.read_bytes() == b'original fixture'
        return {'images': [{'path': 'page-0001.png'}], 'pageCount': 1}

    monkeypatch.setattr(rendering.tempfile, 'TemporaryDirectory', temporary_directory)
    monkeypatch.setattr(rendering, '_render_source', renderer)
    source = tmp_path / '课程.pdf'
    source.write_bytes(b'original fixture')
    output = tmp_path / 'published-pages'
    result = asyncio.run(rendering.render_source(source, file_path(output)))
    assert result['images'][0]['path'] == 'page-0001.png'
    assert (output / 'page-0001.png').read_bytes() == b'fixture page'
    assert source.read_bytes() == b'original fixture'
