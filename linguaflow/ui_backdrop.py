"""Read platform wallpaper; render one cached, opaque frosted material for both OSes."""
import ctypes
import sys

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsScene

from .ui_theme import GLASS_BLUR_RADIUS, GLASS_WALLPAPER_OPACITY, theme_colors


def desktop_wallpaper_path():
    """Best-effort wallpaper path, without screen capture or automation permission."""
    if sys.platform == 'win32':
        try:
            path = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.user32.SystemParametersInfoW(0x0073, len(path), path, 0):
                return path.value
        except (AttributeError, OSError, ValueError):
            return ''
    elif sys.platform == 'darwin':
        return mac_wallpaper_path()
    return ''


def mac_wallpaper_path():
    """Use AppKit's desktop-image API on the GUI thread; no PyObjC dependency."""
    try:
        ctypes.CDLL('/System/Library/Frameworks/AppKit.framework/AppKit')
        objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
        send_arg = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p)(address)
        text = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)(address)
        selector = objc.sel_registerName
        workspace = send(objc.objc_getClass(b'NSWorkspace'), selector(b'sharedWorkspace'))
        screen = send(objc.objc_getClass(b'NSScreen'), selector(b'mainScreen'))
        url = send_arg(workspace, selector(b'desktopImageURLForScreen:'), screen) if screen else None
        path = send(url, selector(b'path')) if url else None
        value = text(path, selector(b'UTF8String')) if path else None
        return value.decode('utf-8') if value else ''
    except (AttributeError, OSError, ValueError, UnicodeError):
        return ''


def frosted_wallpaper(source, size, appearance='light'):
    """Build an RGB8 texture once per wallpaper/size/theme, never per animation frame.

    Blur at quarter resolution with padded edges, then composite in RGBA64 before
    quantizing. Static sub-level noise breaks up broad colour bands without shimmer.
    Missing wallpaper uses the same neutral material on either platform.
    """
    c = theme_colors(appearance)
    image = QImage(size, QImage.Format.Format_RGBA64_Premultiplied)
    image.fill(QColor(c['glass']))
    if not source.isNull():
        quarter = QSize(max(1, size.width() // 4), max(1, size.height() // 4))
        padding = GLASS_BLUR_RADIUS // 2
        expanded = quarter + QSize(padding * 2, padding * 2)
        small = source.scaled(expanded, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        small = small.copy((small.width() - expanded.width()) // 2,
                           (small.height() - expanded.height()) // 2,
                           expanded.width(), expanded.height())
        scene = QGraphicsScene()
        item = scene.addPixmap(small)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(GLASS_BLUR_RADIUS / 4)
        blur.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
        item.setGraphicsEffect(blur)
        blurred = QImage(quarter, QImage.Format.Format_RGBA64_Premultiplied)
        blurred.fill(Qt.GlobalColor.transparent)
        painter = QPainter(blurred)
        scene.render(painter, QRectF(0, 0, quarter.width(), quarter.height()),
                     QRectF(padding, padding, quarter.width(), quarter.height()))
        painter.end()
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(GLASS_WALLPAPER_OPACITY)
        painter.drawImage(image.rect(), blurred)
        painter.end()
    noise = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    # A fixed hash avoids RNG state, repeated patterns at 8px, and animated grain.
    for y in range(32):
        for x in range(32):
            value = ((x + y * 32 + 1) * 2654435761) & 0xffffffff
            value ^= value >> 13
            noise.setPixelColor(x, y, QColor(255 if value & 1 else 0,
                                            255 if value & 1 else 0,
                                            255 if value & 1 else 0, (value >> 1) % 3))
    painter = QPainter(image)
    painter.drawTiledPixmap(image.rect(), QPixmap.fromImage(noise))
    painter.end()
    return QPixmap.fromImage(image.convertToFormat(QImage.Format.Format_RGB32))
