"""Shared desktop surfaces and short, optional interaction animations."""
from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .qt_controls import text_label


def set_download_progress(bar, event):
    total, done = event.get('total'), event.get('completed', 0)
    known = isinstance(total, (int, float)) and total > 0
    bar.setRange(0, 1000 if known else 0)
    if known:
        bar.setValue(max(0, min(1000, int(1000 * done / total))))
    bar.setTextVisible(known)
    bar.setFormat('%p%')


class ChoiceBox(QComboBox):
    """Keep the dropdown affordance visible with the dark stylesheet on every OS."""
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#b9b9c3' if self.isEnabled() else '#64646c'), 1.4))
        x, y = self.width() - 17, self.height() / 2
        painter.drawLine(QPointF(x - 3, y - 1.5), QPointF(x, y + 1.5))
        painter.drawLine(QPointF(x, y + 1.5), QPointF(x + 3, y - 1.5))


def motion_enabled():
    app = QApplication.instance()
    return bool(app and not app.property('reduceMotion'))


class PageTransition:
    """One reusable effect per stack; rapid navigation always settles at opacity 1."""
    def __init__(self, stack):
        self.effect = QGraphicsOpacityEffect(stack)
        self.effect.setOpacity(1)
        stack.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b'opacity', stack)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def start(self):
        self.animation.stop()
        if not motion_enabled():
            self.effect.setOpacity(1)
            return
        self.animation.setStartValue(.35)
        self.animation.setEndValue(1.)
        self.animation.start()


class SurfaceDialog(QDialog):
    """A keyboard-friendly dialog with a shared header, body and action footer."""
    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        self.surface = QFrame()
        self.surface.setObjectName('dialogSurface')
        outer.addWidget(self.surface)
        shell = QVBoxLayout(self.surface)
        shell.setContentsMargins(28, 24, 28, 24)
        shell.setSpacing(18)
        header = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(7)
        words.addWidget(text_label(title, 'dialogTitle'))
        words.addWidget(text_label(description, 'muted'))
        header.addLayout(words, 1)
        close = QPushButton('×')
        close.setObjectName('dialogClose')
        close.setFixedSize(30, 30)
        close.setAccessibleName('关闭' + title)
        close.setToolTip('关闭 · Esc')
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        shell.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        shell.addLayout(self.body, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        shell.addLayout(self.actions)
        self.fade = QPropertyAnimation(self, b'windowOpacity', self)
        self.fade.setDuration(140)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event):
        super().showEvent(event)
        if motion_enabled() and self.platform_supports_opacity():
            self.fade.stop()
            self.fade.setStartValue(.2)
            self.fade.setEndValue(1.)
            self.fade.start()
        else:
            self.setWindowOpacity(1.)

    @staticmethod
    def platform_supports_opacity():
        return QApplication.platformName() != 'offscreen'

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and event.position().y() < 100
                and self.windowHandle()):
            self.windowHandle().startSystemMove()
        super().mousePressEvent(event)


class NameDialog(SurfaceDialog):
    @classmethod
    def getText(cls, parent, title, label, text=''):
        dialog = cls(title, '为文件夹和录音起一个容易找到的名字。', parent)
        dialog.body.addWidget(text_label(label, 'settingsLabel'))
        field = QLineEdit(text)
        field.setMaxLength(64)
        field.setPlaceholderText('输入名称')
        dialog.body.addWidget(field)
        dialog.actions.addStretch()
        cancel = QPushButton('取消')
        cancel.clicked.connect(dialog.reject)
        confirm = QPushButton('保存' if text else '创建文件夹')
        confirm.setObjectName('primary')
        confirm.setDefault(True)
        confirm.setEnabled(bool(text.strip()))
        field.textChanged.connect(lambda value: confirm.setEnabled(bool(value.strip())))
        confirm.clicked.connect(dialog.accept)
        dialog.actions.addWidget(cancel)
        dialog.actions.addWidget(confirm)
        field.selectAll()
        field.setFocus()
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return field.text(), accepted


class Disclosure(QWidget):
    """Keep infrequent options reachable without competing with the main action."""
    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QPushButton('›  ' + title)
        self.toggle.setObjectName('navigation')
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(title)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(content)
        content.hide()
        self.toggle.toggled.connect(content.setVisible)
        self.toggle.toggled.connect(lambda expanded: self.toggle.setText(('⌄  ' if expanded else '›  ') + title))


class ActionMenu(QMenu):
    """Rounded menus with the same surface, spacing and focus treatment as dialogs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(220)
        self.setToolTipsVisible(True)
        self.setObjectName('actionMenu')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.palette().window())
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)
        painter.end()
        super().paintEvent(event)
