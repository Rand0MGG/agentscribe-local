"""Small system preference and wallpaper adapter; no Qt or audio dependencies."""
import argparse
import base64
import ctypes
import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

from .frontend_switch import context
from .settings_store import SettingsStore


def interaction_hints():
    if sys.platform == 'darwin':
        from AppKit import NSEvent
        return dict(doubleClickInterval=round(NSEvent.doubleClickInterval()*1000), dragDistance=10)
    if sys.platform == 'win32':
        user = ctypes.windll.user32
        return dict(doubleClickInterval=user.GetDoubleClickTime(), dragDistance=max(4, user.GetSystemMetrics(68)))
    return dict(doubleClickInterval=500, dragDistance=10)


def wallpaper_path(position):
    if sys.platform == 'darwin':
        from AppKit import NSScreen, NSWorkspace
        screens = NSScreen.screens()
        screen = NSScreen.mainScreen()
        if screens:
            top = screens[0].frame().size.height
            for candidate in screens:
                frame = candidate.frame()
                if frame.origin.x <= position[0] < frame.origin.x+frame.size.width and top-frame.origin.y-frame.size.height <= position[1] < top-frame.origin.y:
                    screen = candidate
                    break
        url = NSWorkspace.sharedWorkspace().desktopImageURLForScreen_(screen) if screen else None
        return str(url.path()) if url else ''
    if sys.platform == 'win32':
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.user32.SystemParametersInfoW(0x0073, len(buffer), buffer, 0):
            return buffer.value
    return ''


def legacy_geometry(value):
    """Read Qt's documented saveGeometry layout without instantiating a widget."""
    if not isinstance(value, bytes) or len(value) < 40 or value[:4] != bytes.fromhex('01d9d0cb'):
        return None
    major, minor = struct.unpack_from('>HH', value, 4)
    if major not in (1, 2, 3):
        return None
    left, top, right, bottom = struct.unpack_from('>iiii', value, 24)
    width, height = right-left+1, bottom-top+1
    if not 1 <= width <= 16384 or not 1 <= height <= 16384:
        return None
    return dict(x=left, y=top, width=width, height=height)


def png_rgba(pixels):
    height, width, _ = pixels.shape
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
    data = b''.join(b'\0'+row.tobytes() for row in pixels)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))+chunk(b'IDAT', zlib.compress(data))+chunk(b'IEND', b'')


def wallpaper_source(path, directory):
    """Decode macOS wallpaper formats with the existing native image framework.

    Electron cannot decode the HEIC images shipped as macOS wallpapers. Keep
    the original file intact and give the shared rasterizer a temporary PNG.
    """
    if sys.platform != 'darwin':
        return path
    from AppKit import NSBitmapImageFileTypePNG, NSBitmapImageRep, NSImage
    image = NSImage.alloc().initWithContentsOfFile_(str(path))
    tiff = image.TIFFRepresentation() if image is not None else None
    bitmap = NSBitmapImageRep.imageRepWithData_(tiff) if tiff is not None else None
    png = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {}) if bitmap is not None else None
    if png is None:
        raise ValueError('macOS 无法读取桌面背景图像。')
    target = Path(directory) / 'wallpaper.png'
    target.write_bytes(bytes(png))
    return str(target)


def material(path, size, appearance, previous):
    import numpy as np
    from scipy.ndimage import gaussian_filter, zoom

    from .electron_tools import run_tool
    from .ui_theme import GLASS_BLUR_RADIUS, GLASS_WALLPAPER_OPACITY, theme_colors
    width, height = size
    stamp = Path(path).stat().st_mtime_ns if path and Path(path).is_file() else 0
    signature = [path, stamp, width, height, appearance]
    if signature == previous:
        return dict(signature=signature, unchanged=True)
    base = theme_colors(appearance)['glass']
    color = tuple(int(base.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    canvas = np.empty((height, width, 4), dtype=np.uint8)
    canvas[:, :, :3] = color
    canvas[:, :, 3] = 255
    if stamp:
        small_width, small_height = max(1, width//4), max(1, height//4)
        with tempfile.TemporaryDirectory(prefix='agentscribe-material-') as directory:
            source = wallpaper_source(path, directory)
            request = Path(directory) / 'request.json'
            request.write_text(json.dumps(dict(source=source, width=small_width, height=small_height)), encoding='utf-8')
            decoded = run_tool('image-tool.cjs', request, timeout=15)
        pixels = np.frombuffer(base64.b64decode(decoded), dtype=np.uint8).reshape(small_height, small_width, 4)
        blurred = gaussian_filter(pixels, sigma=(GLASS_BLUR_RADIUS/8, GLASS_BLUR_RADIUS/8, 0), mode='nearest', output=np.float32)
        expanded = zoom(blurred[:, :, :3], (height/small_height, width/small_width, 1), order=1)
        canvas[:, :, :3] = np.rint(canvas[:, :, :3]*(1-GLASS_WALLPAPER_OPACITY)+expanded*GLASS_WALLPAPER_OPACITY).clip(0,255).astype(np.uint8)
    y, x = np.indices((height, width), dtype=np.uint64)
    value = (((x % 32)+(y % 32)*32+1)*2654435761) & 0xffffffff
    value ^= value >> 13
    alpha = ((value >> 1) % 3).astype(np.float32)[:, :, None]/255
    shade = ((value & 1)*255).astype(np.float32)[:, :, None]
    canvas[:, :, :3] = np.rint(canvas[:, :, :3]*(1-alpha)+shade*alpha).astype(np.uint8)
    return dict(signature=signature, unchanged=False, image='data:image/png;base64,'+base64.b64encode(png_rgba(canvas)).decode('ascii'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--material', action='store_true')
    parser.add_argument('--size', type=int, nargs=2)
    parser.add_argument('--position', type=int, nargs=2, default=(0, 0))
    parser.add_argument('--appearance', choices=('light', 'dark'), default='light')
    parser.add_argument('--signature')
    args = parser.parse_args()
    if args.material:
        size = args.size or (1440, 900)
        if any(not 1 <= n <= 16384 for n in size) or size[0]*size[1] > 64*1024**2:
            raise ValueError('屏幕尺寸无效。')
        print(json.dumps(material(wallpaper_path(args.position), size, args.appearance,
                                 json.loads(args.signature) if args.signature else None)))
        return 0
    saved = context()
    explicit = os.environ.get('AGENTSCRIBE_DESKTOP_PREFERENCES') or saved.get('preferences')
    prefs = SettingsStore(explicit, SettingsStore.Format.IniFormat) if explicit else SettingsStore()
    result = interaction_hints()
    geometry = legacy_geometry(prefs.value('overlay_geometry'))
    if geometry:
        result['overlayBounds'] = geometry
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
