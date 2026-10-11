"""Shared asynchronous wallpaper material; native discovery stays on the GUI thread."""
import ctypes
import logging
import sys
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from scipy.ndimage import gaussian_filter

from .ui_theme import GLASS_BLUR_RADIUS, GLASS_WALLPAPER_OPACITY, theme_colors


def desktop_wallpaper_path(native_view=0):
    """No capture/automation permission; never initialise AppKit in offscreen tests."""
    if sys.platform == 'win32':
        try:
            path = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.user32.SystemParametersInfoW(0x0073, len(path), path, 0):
                return path.value
        except (AttributeError, OSError, ValueError):
            return ''
    elif sys.platform == 'darwin' and QApplication.platformName() == 'cocoa':
        return mac_wallpaper_path(native_view)
    return ''


def mac_wallpaper_path(native_view=0):
    from .ui_macos import wallpaper_path
    try:
        return wallpaper_path(native_view)
    except (AttributeError, OSError, ValueError, UnicodeError):
        return ''


def frosted_image(source, size, appearance='light'):
    """QImage-only worker rendering; reuse existing NumPy/SciPy, no GUI objects.

    Gaussian smoothing at quarter resolution keeps the 112px soft material.
    Composition is RGBA64, with fixed grain before RGB8 output.
    """
    image = QImage(size, QImage.Format.Format_RGBA64_Premultiplied)
    image.fill(QColor(theme_colors(appearance)['glass']))
    if not source.isNull():
        quarter = QSize(max(1, size.width() // 4), max(1, size.height() // 4))
        small = source.scaled(quarter, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        small = small.copy((small.width()-quarter.width())//2, (small.height()-quarter.height())//2,
                           quarter.width(), quarter.height()).convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(small.constBits(), dtype=np.uint8).reshape(small.height(), small.bytesPerLine())
        pixels = pixels[:, :small.width()*4].reshape(small.height(), small.width(), 4)
        blurred = gaussian_filter(pixels, sigma=(GLASS_BLUR_RADIUS / 8, GLASS_BLUR_RADIUS / 8, 0),
                                  mode='nearest', output=np.float32).clip(0, 255).astype(np.uint8)
        smooth = QImage(blurred.data, small.width(), small.height(), small.width()*4,
                        QImage.Format.Format_RGBA8888)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(GLASS_WALLPAPER_OPACITY)
        painter.drawImage(image.rect(), smooth)
        painter.end()
    noise = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    for y in range(32):
        for x in range(32):
            value = ((x + y * 32 + 1) * 2654435761) & 0xffffffff
            value ^= value >> 13
            shade = 255 if value & 1 else 0
            noise.setPixelColor(x, y, QColor(shade, shade, shade, (value >> 1) % 3))
    # QPainter on a QImage is supported off the GUI thread; QPixmap is not.
    painter = QPainter(image)
    for y in range(0, size.height(), 32):
        for x in range(0, size.width(), 32):
            painter.drawImage(x, y, noise)
    painter.end()
    return image.convertToFormat(QImage.Format.Format_RGB32)


def frosted_wallpaper(source, size, appearance='light'):
    """GUI-only convenience for previews/tests; production rendering uses QImage."""
    return QPixmap.fromImage(frosted_image(source.toImage(), size, appearance))


def render_wallpaper(path, size, appearance, previous_signature, previous_image):
    """All filesystem I/O and filtering run in a worker; unchanged files reuse cache."""
    try:
        stamp = Path(path).stat().st_mtime_ns if path else 0
    except OSError:
        stamp = 0
    signature = (path, stamp, size.width(), size.height(), appearance)
    if signature == previous_signature:
        return signature, previous_image
    return signature, frosted_image(QImage(path) if path else QImage(), size, appearance)


class WallpaperBackdrop(QWidget):
    """Paint cached material; coalesce changes and reject superseded worker results."""
    def __init__(self):
        super().__init__()
        self.setObjectName('appRoot')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._path = ''
        self._image = QImage()
        self._signature = None
        self._requested = None
        self._rendered = None
        self._job = None
        self._results = Queue()
        self._closed = False
        self._window_handle = None
        self.wallpaper_timer = QTimer(self)
        self.wallpaper_timer.timeout.connect(self.refresh_wallpaper)
        self.poll = QTimer(self)
        self.poll.setInterval(16)
        self.poll.timeout.connect(self._finished)

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.window().windowHandle()
        if handle is not self._window_handle:
            self._window_handle = handle
            if handle:
                handle.screenChanged.connect(self.refresh_wallpaper)
        self.wallpaper_timer.start(30000)
        self.refresh_wallpaper()

    def event(self, event):
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self.update()
        return super().event(event)

    def refresh_wallpaper(self, *_):
        if self._closed:
            return
        native_view = int(self.window().winId()) if QApplication.platformName() == 'cocoa' else 0
        self._path = desktop_wallpaper_path(native_view)
        self._requested = None  # Re-check stamp, even if the path is unchanged.
        self.update()

    def _key(self):
        screen = self.window().screen() or QApplication.primaryScreen()
        if screen is None:
            return None
        size = screen.geometry().size()
        appearance = QApplication.instance().property('appearance') or 'light'
        return (self._path, size.width(), size.height(), self.devicePixelRatioF(), appearance)

    def _request(self, key):
        if self._closed or not key or key == self._requested:
            return
        if self._job is not None:
            return  # The next paint after completion requests only the latest key.
        self._requested = key
        path, width, height, _, appearance = key
        signature, image, results = self._signature, self._image, self._results

        def run():
            try:
                result = render_wallpaper(path, QSize(width, height), appearance, signature, image)
                results.put((key, result, None))
            except Exception as exc:
                results.put((key, None, exc))

        self._job = Thread(target=run, name='wallpaper-material', daemon=True)
        self._job.start()
        self.poll.start()

    def _finished(self):
        if self._job is None or self._job.is_alive():
            return
        try:
            key, result, error = self._results.get_nowait()
        except Empty:
            return
        self._job.join()
        self._job = None
        self.poll.stop()
        if error:
            logging.getLogger(__name__).warning('Wallpaper material failed: %s', error)
        elif key == self._key() and key == self._requested:
            self._signature, self._image = result
            self._rendered = key
        self.update()

    def shutdown(self):
        # Worker owns only images and its queue, never the widget or application.
        self._closed = True
        self.poll.stop()
        self.wallpaper_timer.stop()

    def paintEvent(self, event):
        key = self._key()
        self._request(key)
        painter = QPainter(self)
        mode = QApplication.instance().property('appearance') or 'light'
        painter.fillRect(self.rect(), QColor(theme_colors(mode)['glass']))
        if not self._image.isNull() and self._rendered == key:
            geometry = (self.window().screen() or QApplication.primaryScreen()).geometry()
            origin = self.mapToGlobal(QPoint(0, 0))
            source = QRect(origin.x()-geometry.x(), origin.y()-geometry.y(), self.width(), self.height())
            painter.drawImage(self.rect(), self._image, source)
        painter.end()
