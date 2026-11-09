"""Small AppKit boundary, called only on the Cocoa GUI thread."""
import ctypes
from functools import lru_cache
from platform import mac_ver


class AppKit:
    def __init__(self):
        ctypes.CDLL('/System/Library/Frameworks/AppKit.framework/AppKit')
        self.objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        self.objc.objc_getClass.argtypes = [ctypes.c_char_p]
        self.objc.objc_getClass.restype = ctypes.c_void_p
        self.objc.sel_registerName.argtypes = [ctypes.c_char_p]
        self.objc.sel_registerName.restype = ctypes.c_void_p
        address = ctypes.cast(self.objc.objc_msgSend, ctypes.c_void_p).value
        pointer = ctypes.c_void_p
        self._send = ctypes.CFUNCTYPE(pointer, pointer, pointer)(address)
        self._argument = ctypes.CFUNCTYPE(pointer, pointer, pointer, pointer)(address)
        self._text = ctypes.CFUNCTYPE(ctypes.c_char_p, pointer, pointer)(address)
        self._set_integer = ctypes.CFUNCTYPE(None, pointer, pointer, ctypes.c_ulong)(address)

    def send(self, obj, selector):
        return self._send(obj, self.objc.sel_registerName(selector))

    def argument(self, obj, selector, value):
        return self._argument(obj, self.objc.sel_registerName(selector), value)

    def window(self, view):
        # Qt Cocoa QWidget.winId() is an NSView, not an NSWindow.
        return self.send(view, b'window') if view else None


@lru_cache(maxsize=1)
def appkit():
    return AppKit()


def wallpaper_path(native_view=0):
    api = appkit()
    window = api.window(native_view)
    screen = api.send(window, b'screen') if window else api.send(api.objc.objc_getClass(b'NSScreen'), b'mainScreen')
    workspace = api.send(api.objc.objc_getClass(b'NSWorkspace'), b'sharedWorkspace')
    url = api.argument(workspace, b'desktopImageURLForScreen:', screen) if screen else None
    path = api.send(url, b'path') if url else None
    value = api._text(path, api.objc.sel_registerName(b'UTF8String')) if path else None
    return value.decode('utf-8') if value else ''


def configure_main_window(native_view):
    api = appkit()
    window = api.window(native_view)
    if not window:
        return False
    api._set_integer(window, api.objc.sel_registerName(b'setTitleVisibility:'), 1)  # NSWindowTitleHidden
    return api.send(window, b'titleVisibility') == 1


def overlay_behavior(existing, *, all_applications):
    # These groups are mutually exclusive in NSWindow.h. Preserve other Qt flags.
    incompatible = (1 << 1) | (1 << 7) | (1 << 9) | (1 << 16) | (1 << 17)
    behavior = (existing & ~incompatible) | (1 << 0) | (1 << 8)
    return behavior | (1 << 18) if all_applications else behavior


def configure_overlay(native_view):
    api = appkit()
    window = api.window(native_view)
    if not window:
        return False
    existing = api.send(window, b'collectionBehavior') or 0
    behavior = overlay_behavior(existing, all_applications=int(mac_ver()[0].split('.')[0]) >= 13)
    api._set_integer(window, api.objc.sel_registerName(b'setCollectionBehavior:'), behavior)
    return api.send(window, b'collectionBehavior') == behavior
