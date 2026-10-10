"""Native desktop frame integration; shared layouts contain no Win32 calls."""
import os
import sys

from PySide6.QtCore import Qt


def resize_edges(point, size, *, margin=7):
    """Hit-test the shared frame boundary in logical pixels."""
    edges = Qt.Edge(0)
    if point.x() <= margin:
        edges |= Qt.Edge.LeftEdge
    elif point.x() >= size.width() - margin:
        edges |= Qt.Edge.RightEdge
    if point.y() <= margin:
        edges |= Qt.Edge.TopEdge
    elif point.y() >= size.height() - margin:
        edges |= Qt.Edge.BottomEdge
    return edges


def start_edge_resize(handle, point, size, *, maximized=False):
    """Use Windows system resizing; macOS keeps its native frame and split view."""
    if sys.platform != 'win32' or os.environ.get('QT_QPA_PLATFORM') == 'offscreen' or maximized:
        return False
    edges = resize_edges(point, size)
    return bool(edges and handle and handle.startSystemResize(edges))


def enable_system_backdrop(native_handle):
    """Enable wallpaper-only Mica behind the connected top and sidebar glass."""
    if sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class Margins(ctypes.Structure):
            _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                        ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

        hwnd = wintypes.HWND(native_handle)
        dwmapi = ctypes.windll.dwmapi
        enabled = ctypes.c_int(1)
        rounded = ctypes.c_int(2)
        backdrop = ctypes.c_int(2)  # DWMSBT_MAINWINDOW / Mica samples the wallpaper only.
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
        dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), ctypes.sizeof(rounded))
        modern_result = dwmapi.DwmSetWindowAttribute(
            hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop)
        )
        # Windows 11 21H2 exposed Mica through this earlier attribute before
        # DWMWA_SYSTEMBACKDROP_TYPE became available.
        legacy_result = dwmapi.DwmSetWindowAttribute(
            hwnd, 1029, ctypes.byref(enabled), ctypes.sizeof(enabled)
        )
        margins = Margins(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        return modern_result == 0 or legacy_result == 0
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return False


def enable_native_resize(native_handle):
    """Restore Windows resize/Snap support for our Qt frame.

    Qt removes WS_THICKFRAME for FramelessWindowHint. Keep the custom client
    drawing while letting the OS recognise a resizable, maximisable window.
    """
    if sys.platform != 'win32' or os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user = ctypes.WinDLL('user32', use_last_error=True)
        get_style = user.GetWindowLongW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = wintypes.LONG
        set_style = user.SetWindowLongW
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        set_style.restype = wintypes.LONG
        position = user.SetWindowPos
        position.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT]
        position.restype = wintypes.BOOL
        hwnd = wintypes.HWND(native_handle)
        style = get_style(hwnd, -16)
        if not style:
            return False
        set_style(hwnd, -16, style | 0x00040000 | 0x00010000)  # WS_THICKFRAME | WS_MAXIMIZEBOX
        if not position(hwnd, None, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002 | 0x0004 | 0x0010):
            return False
        return bool(get_style(hwnd, -16) & 0x00040000)
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return False
