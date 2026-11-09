"""Shared desktop frame and icons; independent of recording and model workflows."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QPushButton

from .ui_theme import WORKSPACE_RADIUS, theme_colors


class WindowButton(QPushButton):
    """Draw window controls without depending on symbol-font fallback."""
    def __init__(self, host, kind):
        super().__init__('')
        self.host, self.kind = host, kind
        self.setObjectName('windowClose' if kind == 'close' else 'windowControl')

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme_colors(QApplication.instance().property('appearance'))
        p.setPen(QPen(QColor('#ffffff' if self.kind == 'close' and self.underMouse() else c['text']), 1.2))
        x, y = self.width() // 2, self.height() // 2
        if self.kind == 'close':
            p.drawLine(x-4, y-4, x+4, y+4)
            p.drawLine(x-4, y+4, x+4, y-4)
        elif self.kind == 'minimize':
            p.drawLine(x-5, y, x+5, y)
        elif self.host.isMaximized():
            p.drawRect(x-3, y-5, 8, 8)
            p.fillRect(x-5, y-3, 8, 8, QColor(c['glass']))
            p.drawRect(x-5, y-3, 8, 8)
        else:
            p.drawRect(x-4, y-4, 8, 8)

def is_split_layout(bounds, area):
    """Recognize a full-height edge tile, rather than any narrow window."""
    tolerance = 16
    return (area.width() > 0 and area.height() > 0
            and bounds.width() <= area.width() * .8
            and abs(bounds.y() - area.y()) <= tolerance
            and abs(bounds.height() - area.height()) <= tolerance
            and (abs(bounds.x() - area.x()) <= tolerance
                 or abs(bounds.right() - area.right()) <= tolerance))


class GlassTitleBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.host = window
        self.setObjectName("glassTopBar")
        self.setFixedHeight(36)
        bar = QHBoxLayout(self)
        # macOS owns the traffic lights on the left; Windows owns our buttons on the right.
        bar.setContentsMargins(96 if window.integrated_titlebar else 13, 0, 0, 0)
        bar.setSpacing(8)
        bar.addStretch()
        minimize = WindowButton(window, 'minimize')
        minimize.setToolTip("最小化")
        minimize.setAccessibleName('最小化')
        minimize.clicked.connect(window.showMinimized)
        self.maximize = WindowButton(window, 'maximize')
        self.maximize.setToolTip("最大化")
        self.maximize.setAccessibleName('最大化或还原')
        self.maximize.clicked.connect(self.toggle_maximized)
        close = WindowButton(window, 'close')
        close.setToolTip("关闭")
        close.setAccessibleName('关闭')
        close.clicked.connect(window.close)
        bar.addWidget(minimize)
        bar.addWidget(self.maximize)
        bar.addWidget(close)
        for button in (minimize, self.maximize, close):
            button.setVisible(not window.integrated_titlebar)

    def toggle_maximized(self):
        if self.host.isMaximized():
            self.host.showNormal()
            self.maximize.setToolTip("最大化")
        else:
            self.host.showMaximized()
            self.maximize.setToolTip("还原")
        self.maximize.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.host.windowHandle():
            self.host.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

class WorkspaceFrame(QFrame):
    """Fill and outline share one contour, including the lower content corners."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = float(WORKSPACE_RADIUS)
        path = QPainterPath()
        path.moveTo(self.width() - .5, radius)
        path.quadTo(self.width() - .5, .5, self.width() - radius, .5)
        path.lineTo(radius, 0.5)
        path.quadTo(0.5, 0.5, 0.5, radius)
        path.lineTo(0.5, self.height()-radius)
        path.quadTo(.5, self.height()-.5, radius, self.height()-.5)
        path.lineTo(self.width()-10, self.height()-.5)
        path.quadTo(self.width()-.5, self.height()-.5, self.width()-.5, self.height()-10)
        path.closeSubpath()
        colors = theme_colors(QApplication.instance().property('appearance'))
        painter.fillPath(path, QColor(colors['surface']))
        painter.setPen(QPen(QColor(colors['border']), 1))
        painter.drawPath(path)

def line_icon(kind, color="#bdbdbf"):
    pixmap = QPixmap(80, 80)
    pixmap.setDevicePixelRatio(4)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.45))
    if kind in ('sidebar-collapse', 'sidebar-expand'):
        painter.drawRoundedRect(3, 3, 14, 14, 3, 3)
        painter.drawLine(8, 3, 8, 17)
        direction = -1 if kind == 'sidebar-collapse' else 1
        painter.drawLine(12-direction, 7, 12+direction*2, 10)
        painter.drawLine(12+direction*2, 10, 12-direction, 13)
    elif kind in ('folder', 'folder-add'):
        path = QPainterPath()
        path.moveTo(3, 6)
        path.lineTo(3, 4)
        path.lineTo(8, 4)
        path.lineTo(10, 6)
        path.lineTo(17, 6)
        path.lineTo(17, 16)
        path.lineTo(3, 16)
        path.closeSubpath()
        painter.drawPath(path)
        if kind == 'folder-add':
            painter.drawLine(10, 9, 10, 14)
            painter.drawLine(8, 12, 13, 12)
        else:
            painter.drawLine(3, 8, 17, 8)
    elif kind == "new":
        painter.drawRoundedRect(3, 3, 14, 14, 3, 3)
        painter.drawLine(6, 10, 14, 10)
        painter.drawLine(10, 6, 10, 14)
    elif kind == "settings":
        for y, x in [(5, 7), (10, 13), (15, 8)]:
            painter.drawLine(3, y, 17, y)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(x, y), 2, 2)
    elif kind == 'chevron':
        painter.drawLine(6, 8, 10, 12)
        painter.drawLine(10, 12, 14, 8)
    elif kind == 'refresh':
        painter.drawArc(4, 4, 12, 12, 40*16, 280*16)
        painter.drawLine(15, 3, 15, 7)
        painter.drawLine(11, 7, 15, 7)
    elif kind == 'download':
        painter.drawLine(10, 3, 10, 13)
        painter.drawLine(6, 9, 10, 13)
        painter.drawLine(10, 13, 14, 9)
        painter.drawLine(3, 15, 3, 17)
        painter.drawLine(3, 17, 17, 17)
        painter.drawLine(17, 17, 17, 15)
    elif kind == 'check':
        painter.drawLine(4, 10, 8, 14)
        painter.drawLine(8, 14, 16, 6)
    elif kind == 'system':
        painter.drawRoundedRect(3, 3, 14, 10, 2, 2)
        painter.drawLine(10, 13, 10, 17)
        painter.drawLine(6, 17, 14, 17)
    elif kind == 'input':
        painter.drawRoundedRect(7, 2, 6, 10, 3, 3)
        painter.drawArc(4, 5, 12, 10, 180*16, 180*16)
        painter.drawLine(10, 15, 10, 18)
        painter.drawLine(7, 18, 13, 18)
    elif kind == 'trash':
        painter.drawLine(3, 5, 17, 5)
        painter.drawLine(7, 3, 13, 3)
        painter.drawLine(5, 7, 6, 17)
        painter.drawLine(6, 17, 14, 17)
        painter.drawLine(14, 17, 15, 7)
        painter.drawLine(8, 8, 8, 14)
        painter.drawLine(12, 8, 12, 14)
    elif kind == 'play':
        path = QPainterPath()
        path.moveTo(7, 4)
        path.lineTo(16, 10)
        path.lineTo(7, 16)
        path.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(path)
    elif kind == 'pause':
        painter.drawLine(7, 4, 7, 16)
        painter.drawLine(13, 4, 13, 16)
    elif kind == 'stop':
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(5, 5, 10, 10, 1, 1)
    elif kind == 'language':
        painter.drawEllipse(3, 3, 14, 14)
        painter.drawEllipse(7, 3, 6, 14)
        painter.drawLine(3, 10, 17, 10)
    elif kind == 'volume':
        path = QPainterPath()
        path.moveTo(3, 8)
        path.lineTo(6, 8)
        path.lineTo(10, 4)
        path.lineTo(10, 16)
        path.lineTo(6, 12)
        path.lineTo(3, 12)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawArc(10, 6, 6, 8, -65*16, 130*16)
        painter.drawArc(9, 3, 10, 14, -65*16, 130*16)
    else:
        painter.drawRoundedRect(5, 3, 10, 14, 2, 2)
        painter.drawLine(8, 7, 12, 7)
        painter.drawLine(8, 10, 12, 10)
    painter.end()
    return QIcon(pixmap)
