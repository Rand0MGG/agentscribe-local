"""Preserve wallpaper appearance and caching across rasterizer replacement."""
import sys

import pytest
from ui_support import run_ui_process


@pytest.mark.p1
def test_material_helper_matches_qt_and_reuses_unchanged_wallpaper(tmp_path):
    run_ui_process(r'''
import base64, contextlib, io, json, os, sys
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from linguaflow import desktop_platform, ui_backdrop
app = QApplication([])
path = Path(os.environ['AGENTSCRIBE_LIBRARY']) / 'wallpaper.png'
source = QImage(60,40,QImage.Format.Format_RGB32)
source.fill(QColor('#8e47db'))
assert source.save(str(path))
def render(theme, previous=None):
    args = ['material','--material','--size','200','120','--appearance',theme]
    if previous is not None:
        args += ['--signature',json.dumps(previous)]
    output = io.StringIO()
    with patch.object(sys,'argv',args), patch.object(desktop_platform,'wallpaper_path',return_value=str(path)), contextlib.redirect_stdout(output):
        assert desktop_platform.main() == 0
    return json.loads(output.getvalue())
for theme in ('light','dark'):
    result = render(theme)
    assert not result['unchanged']
    image = QImage.fromData(base64.b64decode(result['image'].split(',',1)[1]))
    expected = ui_backdrop.render_wallpaper(str(path),QSize(200,120),theme,None,QImage())[1]
    import numpy as np
    actual = image.convertToFormat(QImage.Format.Format_RGBA8888)
    reference = expected.convertToFormat(QImage.Format.Format_RGBA8888)
    delta = np.abs(np.frombuffer(actual.constBits(),dtype=np.uint8).astype(int)-np.frombuffer(reference.constBits(),dtype=np.uint8).astype(int))
    assert delta.max() <= 1, f'Material differs beyond one 8-bit rounding level: {delta.max()}'
    cached = render(theme,result['signature'])
    assert cached['unchanged'] and 'image' not in cached
assert render('dark',render('light')['signature'])['unchanged'] is False
''', tmp_path)


@pytest.mark.p1
@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS native wallpaper formats')
def test_heic_wallpaper_renders_material_without_modifying_original(tmp_path):
    run_ui_process(r'''
import base64, hashlib, os, subprocess
from pathlib import Path
import numpy as np
from linguaflow.desktop_platform import material, png_rgba
directory = Path(os.environ['AGENTSCRIBE_LIBRARY'])
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
''', tmp_path)
