"""Electron material must reuse the Qt pixels, including its cache signature."""
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
    with patch.object(sys,'argv',args), patch.object(desktop_platform,'QApplication',return_value=app), \
         patch.object(ui_backdrop,'desktop_wallpaper_path',return_value=str(path)), contextlib.redirect_stdout(output):
        assert desktop_platform.main() == 0
    return json.loads(output.getvalue())
for theme in ('light','dark'):
    result = render(theme)
    assert not result['unchanged']
    image = QImage.fromData(base64.b64decode(result['image'].split(',',1)[1]))
    expected = ui_backdrop.render_wallpaper(str(path),QSize(200,120),theme,None,QImage())[1]
    assert image == expected, 'Material pixels differ from the original Qt renderer'
    cached = render(theme,result['signature'])
    assert cached['unchanged'] and 'image' not in cached
assert render('dark',render('light')['signature'])['unchanged'] is False
''', tmp_path)
