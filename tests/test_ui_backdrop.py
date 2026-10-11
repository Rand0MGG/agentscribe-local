"""Background material is bounded, responsive, and independent of native audio."""
import os
import subprocess
import sys

from ui_support import assert_ui_process


def test_wallpaper_worker_coalesces_changes_and_keeps_gui_responsive(tmp_path):
    code = r'''
import time
from threading import Event, get_ident
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from linguaflow import ui_backdrop
app = QApplication([])
app.setProperty('appearance', 'light')
started, release = Event(), Event()
gui = get_ident()
calls, ticks = [], []
original = ui_backdrop.render_wallpaper

def slow(path, size, appearance, signature, image):
    assert get_ident() != gui
    calls.append(appearance)
    if len(calls) == 1:
        started.set()
        assert release.wait(3)
    return original(path, size, appearance, signature, image)

def wait(predicate):
    deadline = time.monotonic()+5
    while not predicate():
        app.processEvents()
        assert time.monotonic() < deadline
        time.sleep(.005)

with patch.object(ui_backdrop, 'render_wallpaper', slow), \
     patch.object(ui_backdrop, 'desktop_wallpaper_path', return_value=''):
    backdrop = ui_backdrop.WallpaperBackdrop()
    backdrop.resize(400, 300)
    backdrop.show()
    wait(started.is_set)
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start(5)
    for mode in ('dark', 'light', 'dark'):
        app.setProperty('appearance', mode)
        backdrop.grab()
    QTimer.singleShot(50, release.set)
    wait(lambda: backdrop._rendered == backdrop._key())
    assert len(ticks) >= 3, ticks
    assert calls == ['light', 'dark'], calls
    assert isinstance(backdrop._image, QImage)
    assert backdrop._signature[-1] == 'dark'
    image = backdrop._image
    # Moving/repainting does not re-read or re-filter. A stamp check reuses pixels.
    backdrop.grab()
    backdrop.refresh_wallpaper()
    wait(lambda: backdrop._job is None and len(calls) == 3)
    assert backdrop._image == image
    backdrop.shutdown()
    backdrop.refresh_wallpaper()
    assert not backdrop.poll.isActive() and not backdrop.wallpaper_timer.isActive()
    backdrop.close()

# The filesystem cache notices replacement at the same path.
path = os.environ['BACKDROP_FIXTURE']
source = QImage(50, 50, QImage.Format.Format_RGB32)
source.fill(QColor('red'))
assert source.save(path)
signature, rendered = original(path, source.size(), 'light', None, QImage())
again_signature, again = original(path, source.size(), 'light', signature, rendered)
assert signature == again_signature and rendered == again
source.fill(QColor('blue'))
assert source.save(path)
from pathlib import Path
stat = Path(path).stat()
os.utime(path, ns=(stat.st_atime_ns, signature[1]+1000000000))
new_signature, changed = original(path, source.size(), 'light', signature, rendered)
assert new_signature != signature and changed != rendered
'''
    result = subprocess.run([sys.executable, '-c', 'import os\n'+code], capture_output=True,
                            text=True, errors='backslashreplace', timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'BACKDROP_FIXTURE': str(tmp_path/'wallpaper.png')})
    assert_ui_process(result)


def test_overlay_restores_offscreen_preferences_without_changing_text_settings(tmp_path):
    code = r'''
import os
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget
from linguaflow.subtitles_overlay import Overlay
app = QApplication([])
prefs = QSettings(os.environ['OVERLAY_PREFS'], QSettings.Format.IniFormat)
former = QWidget()
former.setGeometry(-3000, -2000, 780, 220)
prefs.setValue('overlay_geometry', former.saveGeometry())
prefs.setValue('overlay_font_size', 31)
prefs.setValue('overlay_background_opacity', 55)
overlay = Overlay(prefs)
overlay.show()
app.processEvents()
assert any(screen.availableGeometry().contains(overlay.geometry()) for screen in app.screens())
assert overlay.font_size.value() == 31
before = overlay.geometry()
overlay.hide()
reopened = Overlay(prefs)
reopened.show()
app.processEvents()
assert reopened.geometry() == before and reopened.font_size.value() == 31
reopened.close()
overlay.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                            errors='backslashreplace', timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'OVERLAY_PREFS': str(tmp_path/'overlay.ini')})
    assert_ui_process(result)
