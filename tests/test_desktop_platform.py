"""Native wallpaper decoding, original protection, cache and geometry compatibility."""
import base64
import sys

import numpy as np
import pytest

from linguaflow.desktop_platform import material, png_rgba
from tests.image_support import png_pixels


@pytest.mark.p2
def test_material_cache_theme_and_real_image_pixels(tmp_path):
    source = tmp_path / 'wallpaper.png'
    source.write_bytes(png_rgba(np.full((40, 60, 4), (142, 71, 219, 255), dtype=np.uint8)))
    original = source.read_bytes()
    light = material(str(source), (200, 120), 'light', None)
    assert material(str(source), (200, 120), 'light', light['signature'])['unchanged']
    dark = material(str(source), (200, 120), 'dark', light['signature'])
    assert not dark['unchanged'] and dark['image'] != light['image']
    output = tmp_path / 'render.png'
    output.write_bytes(base64.b64decode(dark['image'].split(',', 1)[1]))
    assert png_pixels(output).shape == (120, 200, 4)
    assert source.read_bytes() == original


@pytest.mark.p1
@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS native wallpaper formats')
def test_heic_wallpaper_renders_material_without_modifying_original(tmp_path):
    import base64
    import hashlib
    import subprocess

    import numpy as np

    from linguaflow.desktop_platform import material, png_rgba
    directory = tmp_path
    source, heic = directory/'source.png', directory/'wallpaper.heic'
    pixels = np.zeros((40,60,4), dtype=np.uint8)
    pixels[:,:,:] = (170,30,230,255)
    source.write_bytes(png_rgba(pixels))
    subprocess.run(['sips','-s','format','heic',str(source),'--out',str(heic)],check=True,capture_output=True)
    before = hashlib.sha256(heic.read_bytes()).digest()
    result = material(str(heic), (200,120), 'dark', None)
    assert base64.b64decode(result['image'].split(',',1)[1]).startswith(b'\x89PNG')
    assert result['image'] != material('', (200,120), 'dark', None)['image']
    assert material(str(heic), (200,120), 'dark', result['signature'])['unchanged']
    assert hashlib.sha256(heic.read_bytes()).digest() == before
