"""One bounded, theme-aware plain-text tooltip surface for the application."""
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QApplication, QFrame, QLabel, QMenu, QVBoxLayout, QWidget

from .ui_theme import theme_colors


class TooltipBubble(QFrame):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setObjectName('tooltipBubble')
        self.setStyleSheet('QFrame#tooltipBubble { background: transparent; border: none; }')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(320)
        layout.addWidget(self.label)

    def paintEvent(self, event):
        colors = theme_colors(QApplication.instance().property('appearance'))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(colors['surface']))
        painter.setPen(QPen(QColor(colors['border']), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 9, 9)


class TooltipManager(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._closed = False
        self.bubble = TooltipBubble()
        self.bubble.destroyed.connect(self._bubble_destroyed)
        self.anchor = None
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.hide)
        app.installEventFilter(self)
        app.aboutToQuit.connect(self.shutdown)

    def _bubble_destroyed(self):
        self.bubble = None
        self.shutdown()

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.timeout.stop()
        self.anchor = None
        if not QApplication.closingDown():
            self.app.removeEventFilter(self)
            if self.bubble is not None:
                self.bubble.hide()

    def hide(self):
        self.timeout.stop()
        self.anchor = None
        if self.bubble is not None and not QApplication.closingDown():
            self.bubble.hide()

    def show(self, widget, text, position):
        if self._closed or QApplication.closingDown():
            return
        colors = theme_colors(QApplication.instance().property('appearance'))
        self.bubble.label.setStyleSheet(f'background: transparent; border: none; padding: 0; color: {colors["text"]}; font-size: 12px;')
        screen = widget.screen().availableGeometry()
        self.bubble.label.setText(text)
        self.bubble.label.ensurePolished()
        natural = max(self.bubble.label.fontMetrics().horizontalAdvance(line) for line in text.splitlines())
        self.bubble.label.setFixedWidth(min(320, screen.width()-48, natural+4))
        self.bubble.adjustSize()
        x = min(max(screen.left()+8, position.x()+12), screen.right()-self.bubble.width()-8)
        y = position.y()+18
        if y+self.bubble.height() > screen.bottom()-8:
            y = position.y()-self.bubble.height()-12
        self.bubble.move(QPoint(x, max(screen.top()+8, y)))
        self.anchor = widget
        self.bubble.show()
        self.timeout.start(8000)

    def eventFilter(self, watched, event):
        if self._closed or QApplication.closingDown():
            return False
        kind = event.type()
        if kind == QEvent.Type.ToolTip and isinstance(watched, QWidget):
            text = watched.toolTip().strip()
            view = watched.parentWidget()
            if not text and isinstance(view, QAbstractItemView):
                text = str(view.indexAt(event.pos()).data(Qt.ItemDataRole.ToolTipRole) or '')
            if not text and isinstance(watched, QMenu):
                action = watched.actionAt(event.pos())
                text = action.toolTip() if action is not None and action.toolTip() != action.text() else ''
            if text:
                self.show(watched, text, event.globalPos())
            else:
                self.hide()
            return True
        if (kind in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress)
                or (kind == QEvent.Type.WindowDeactivate and watched is not self.bubble)
                or (kind in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.Close) and watched is self.anchor)):
            self.hide()
        return False


def install_tooltips(app):
    if not hasattr(app, '_agentscribe_tooltips'):
        app._agentscribe_tooltips = TooltipManager(app)
    return app._agentscribe_tooltips
