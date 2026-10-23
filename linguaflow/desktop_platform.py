"""Read native interaction thresholds and legacy Qt geometry without opening a window.

The short-lived helper has no audio, network or library access. Both frontends
therefore use the same OS preferences while the recording owner stays separate.
"""
import argparse
import base64
import json
import os

from PySide6.QtCore import QBuffer, QIODevice, QSettings, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from .frontend_switch import context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--material', action='store_true')
    parser.add_argument('--size', type=int, nargs=2)
    parser.add_argument('--position', type=int, nargs=2, default=(0, 0))
    parser.add_argument('--appearance', choices=('light', 'dark'), default='light')
    parser.add_argument('--signature')
    args = parser.parse_args()
    app = QApplication([])
    if args.material:
        from .ui_backdrop import desktop_wallpaper_path, render_wallpaper
        widget = QWidget()
        widget.move(*args.position)
        path = desktop_wallpaper_path(int(widget.winId()))
        width, height = args.size or (1440, 900)
        if not 1 <= width <= 16384 or not 1 <= height <= 16384:
            raise ValueError('屏幕尺寸无效。')
        previous = tuple(json.loads(args.signature)) if args.signature else None
        signature, picture = render_wallpaper(path, QSize(width, height), args.appearance, previous, QImage())
        result = dict(signature=signature, unchanged=signature == previous)
        if not result['unchanged']:
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not picture.save(buffer, 'PNG'):
                raise ValueError('无法生成窗口材质。')
            result['image'] = 'data:image/png;base64,' + base64.b64encode(bytes(buffer.data())).decode('ascii')
        print(json.dumps(result))
        widget.close()
        return 0
    saved = context()
    explicit = os.environ.get('AGENTSCRIBE_DESKTOP_PREFERENCES')
    prefs = (QSettings(explicit, QSettings.Format.IniFormat) if explicit else
             QSettings(saved['preferences'], QSettings.Format(saved.get('preferences_format', 1)))
             if saved.get('preferences') else QSettings('LinguaFlow', 'LocalCaptions'))
    result = dict(doubleClickInterval=app.doubleClickInterval(), dragDistance=app.startDragDistance())
    # restoreGeometry understands Qt's versioned, screen-aware binary format.
    # This unshown QWidget owns neither a library nor any recording resources.
    geometry = prefs.value('overlay_geometry')
    if geometry is not None:
        widget = QWidget()
        if widget.restoreGeometry(geometry):
            result['overlayBounds'] = dict(zip(('x', 'y', 'width', 'height'), widget.geometry().getRect()))
        widget.close()
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
