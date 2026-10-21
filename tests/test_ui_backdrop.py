"""Background material is bounded, responsive, and independent of native audio."""
import os

from ui_support import run_ui_process


def test_close_during_wallpaper_render_waits_without_blocking_qt(tmp_path):
    code = r'''
import os, time
from threading import Event
from unittest.mock import patch
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow import ui_backdrop
from scripts.probe_package import close_window
app = QApplication([])
started, release = Event(), Event()
def slow(*args):
    started.set()
    assert release.wait(5)
    return ('fixture', QImage())
def wait(predicate):
    deadline = time.monotonic()+5
    while not predicate():
        app.processEvents()
        assert time.monotonic() < deadline
        time.sleep(.005)
with patch.object(ui_backdrop, 'render_wallpaper', slow), \
     patch.object(ui_backdrop, 'desktop_wallpaper_path', return_value=''), \
     patch.object(Window, 'start_background_check', return_value=None):
    w = Window(discover=False, prefs=QSettings(os.environ['PREFS'], QSettings.Format.IniFormat),
               library_root=os.environ['LIBRARY'])
    w.show()
    wait(started.is_set)
    backdrop = w.centralWidget()
    job = backdrop._job
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    try:
        assert not w.close(), 'close must wait for its active rendering thread'
        assert not w.close(), 'repeated close must retain the same worker'
        assert w.isVisible() and backdrop._job is job
        wait(lambda: len(ticks) >= 3)
        release.set()
        close_window(w, app)
        assert not job.is_alive() and backdrop._job is None
        assert backdrop.shutdown() is True
        assert not backdrop.poll.isActive() and not backdrop.wallpaper_timer.isActive()
        assert backdrop._image.isNull(), 'closed workers must not publish late images'
    finally:
        release.set()
        job.join(5)
        timer.stop()
'''
    run_ui_process(code, timeout=15,
                   env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PREFS': str(tmp_path / 'prefs.ini'), 'LIBRARY': str(tmp_path / 'library')})
