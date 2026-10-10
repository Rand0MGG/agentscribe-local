"""Shared desktop surfaces and short, optional interaction animations."""
import math

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QMenu,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from .qt_controls import text_label
from .ui_theme import CONTROL_RADIUS, theme_colors


class AudioLevelMeter(QProgressBar):
    """Visible input segments; RMS is mapped to a useful quiet-to-loud range.

    This is presentation only: it neither changes PCM nor opens audio devices.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(22)
        self.setStyleSheet('min-height: 22px; max-height: 22px; padding: 0;')
        self.setMinimumWidth(72)
        self.setMaximumWidth(144)
        self.setAccessibleName('音频输入音量')
        self.display_level = 0.
        self.motion = QVariantAnimation(self)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self.paint_level)
        super().setValue(0)

    def sizeHint(self):
        return QSize(144, 22)

    def paint_level(self, value):
        self.display_level = float(value)
        self.update()

    def setValue(self, value):
        value = max(0, min(100, int(value)))
        super().setValue(value)
        self.motion.stop()
        if value == 0 or not self.isVisible() or not motion_enabled():
            self.paint_level(value)
            return
        self.motion.setDuration(80 if value >= self.display_level else 180)
        self.motion.setStartValue(self.display_level)
        self.motion.setEndValue(float(value))
        self.motion.start()

    def set_rms(self, value):
        """Display linear full-scale RMS; zero/non-finite input clears the bars."""
        value = float(value)
        level = (max(0., min(100., (20 * math.log10(value) + 72) / 72 * 100))
                 if math.isfinite(value) and value > 0 else 0.)
        self.setValue(round(level))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(QApplication.instance().property('appearance'))
        painter.setPen(Qt.PenStyle.NoPen)
        count, spacing = 16, 3
        width = max(1., (self.width() - spacing * (count-1)) / count)
        active = math.ceil(count * self.display_level / 100)
        for index in range(count):
            height = 5 + 16 * index / (count-1)
            painter.setOpacity(1. if index < active else .25)
            painter.setBrush(QColor(colors['text'] if index < active else colors['muted']))
            painter.drawRoundedRect(QRectF(index * (width + spacing), (self.height()-height)/2,
                                          width, height), min(1.8, width/2), min(1.8, width/2))


def set_download_progress(bar, event):
    total, done = event.get('total'), event.get('completed', 0)
    known = isinstance(total, (int, float)) and total > 0
    bar.setRange(0, 1000 if known else 0)
    if known:
        bar.setValue(max(0, min(1000, int(1000 * done / total))))
    bar.setTextVisible(known)
    bar.setFormat('%p%')


class ChoiceDelegate(QStyledItemDelegate):
    def __init__(self, choice):
        super().__init__(choice)
        self.choice = choice

    def sizeHint(self, option, index):
        return QSize(option.fontMetrics.horizontalAdvance(str(index.data()))+52,
                     max(34, option.fontMetrics.height()+16))

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme_colors(QApplication.instance().property('appearance'))
        rect = option.rect.adjusted(4, 2, -4, -2)
        selected = bool(option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c['selected' if option.state & QStyle.StateFlag.State_Selected else 'hover']))
            painter.drawRoundedRect(rect, 6, 6)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        painter.setPen(QColor(c['text'] if enabled else c['disabled']))
        painter.setFont(option.font)
        text_rect = rect.adjusted(30, 0, -12, 0)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None and not icon.isNull():
            icon.paint(painter, text_rect.x(), rect.center().y()-8, 16, 16)
            text_rect.adjust(24, 0, 0, 0)
        text = option.fontMetrics.elidedText(str(index.data()), Qt.TextElideMode.ElideMiddle, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, text)
        if index.row() == self.choice.currentIndex():
            painter.setPen(QPen(QColor(c['text']), 1.6))
            x, y = rect.x()+15, rect.center().y()
            painter.drawLine(QPointF(x-4, y), QPointF(x-1, y+3))
            painter.drawLine(QPointF(x-1, y+3), QPointF(x+5, y-4))
        painter.restore()


class ChoiceBox(QComboBox):
    """Shared keyboard-native choices with bounded popups and painted symbols."""
    def __init__(self, parent=None):
        super().__init__(parent)
        view = QListView()
        view.setItemDelegate(ChoiceDelegate(self))
        view.setMouseTracking(True)
        view.setUniformItemSizes(True)
        view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setView(view)
        self.setMaxVisibleItems(8)
        self.currentTextChanged.connect(self.setToolTip)
        view.entered.connect(lambda index: view.viewport().setToolTip(str(index.data() or '')))

    def showPopup(self):
        if not self.count():
            return
        c = theme_colors(QApplication.instance().property('appearance'))
        view = self.view()
        popup = view.window()
        popup.setObjectName('choicePopup')
        popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup.setStyleSheet(f'QFrame#choicePopup {{ background: {c["surface"]}; border: 1px solid {c["border"]};'
                           f' border-radius: 12px; padding: 6px; }} '
                           'QListView { background: transparent; border: none; padding: 0; outline: none; }')
        bounds = self.screen().availableGeometry()
        width = min(max(self.width(), min(520, max(self.fontMetrics().horizontalAdvance(self.itemText(i))
                     for i in range(self.count()))+60)), bounds.width()-24)
        view.setFixedWidth(max(1, width-14))
        super().showPopup()
        point = self.mapToGlobal(QPoint(0, self.height()+5))
        height = min(popup.height(), 8*max(34, self.fontMetrics().height()+16)+14, bounds.height()-24)
        x = min(max(bounds.left()+12, point.x()), bounds.right()-width-11)
        y = point.y() if point.y()+height <= bounds.bottom()-12 else self.mapToGlobal(QPoint(0, 0)).y()-height-5
        y = min(max(bounds.top()+12, y), bounds.bottom()-height-11)
        popup.setGeometry(x, y, width, height)
        view.scrollTo(view.currentIndex())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme_colors(QApplication.instance().property('appearance'))
        painter.setPen(QPen(QColor(c['muted'] if self.isEnabled() else c['disabled']), 1.4))
        x, y = self.width() - 17, self.height() / 2
        painter.drawLine(QPointF(x - 3, y - 1.5), QPointF(x, y + 1.5))
        painter.drawLine(QPointF(x, y + 1.5), QPointF(x + 3, y - 1.5))


class SpinSymbols:
    """Paint scale-safe arrows at the native hit rectangles, without font glyphs."""
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(QApplication.instance().property('appearance'))
        painter.setPen(QPen(QColor(colors['muted'] if self.isEnabled() else colors['disabled']), 1.4))
        for control, direction in ((QStyle.SubControl.SC_SpinBoxUp, -1), (QStyle.SubControl.SC_SpinBoxDown, 1)):
            rect = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, control, self)
            if not rect.isEmpty():
                x, y = rect.center().x(), rect.center().y()
                painter.drawLine(QPointF(x-3, y-direction), QPointF(x, y+direction))
                painter.drawLine(QPointF(x, y+direction), QPointF(x+3, y-direction))


class SpinBox(SpinSymbols, QSpinBox):
    pass


class DoubleSpinBox(SpinSymbols, QDoubleSpinBox):
    pass


def motion_enabled():
    app = QApplication.instance()
    return bool(app and not app.property('reduceMotion'))


class FloatingIsland(QFrame):
    """Overlay controls without reserving a horizontal strip in the scroll area."""
    heightChanged = Signal(int)
    compactChanged = Signal(bool)

    def __init__(self, viewport):
        super().__init__(viewport)
        self.setObjectName('controlIsland')
        self.compact = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.placement = QTimer(self)
        self.placement.setSingleShot(True)
        self.placement.timeout.connect(self.place)
        viewport.installEventFilter(self)
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(24)
        effect.setOffset(0, 4)
        effect.setColor(QColor(0, 0, 0, 30))
        self.setGraphicsEffect(effect)

    def eventFilter(self, widget, event):
        if event.type() == QEvent.Type.Resize:
            self.placement.start(0)
        return False

    def event(self, event):
        if event.type() == QEvent.Type.LayoutRequest and hasattr(self, 'placement'):
            self.placement.start(0)
        return super().event(event)

    def place(self):
        viewport = self.parentWidget()
        old_height = self.height()
        self.setFixedWidth(min(680, max(1, viewport.width()-48)))
        compact = self.width() < 500
        if compact != self.compact:
            self.compact = compact
            self.compactChanged.emit(compact)
        self.layout().activate()
        height = self.sizeHint().height()
        self.setGeometry((viewport.width()-self.width())//2, max(12, viewport.height()-height-18), self.width(), height)
        self.raise_()
        if height != old_height:
            self.heightChanged.emit(height)


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
        close.setToolTip('关闭')
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


class DisclosureButton(QPushButton):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme_colors(QApplication.instance().property('appearance'))
        painter.setPen(QPen(QColor(c['muted']), 1.4))
        x, y = 13, self.height() / 2
        points = [(x-3, y-1.5), (x, y+1.5), (x+3, y-1.5)] if self.isChecked() else [
            (x-1.5, y-3), (x+1.5, y), (x-1.5, y+3)]
        painter.drawLine(QPointF(*points[0]), QPointF(*points[1]))
        painter.drawLine(QPointF(*points[1]), QPointF(*points[2]))


class Disclosure(QWidget):
    """Keep infrequent options reachable without competing with the main action."""
    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = DisclosureButton(title)
        self.toggle.setStyleSheet('text-align: left; padding-left: 26px;')
        self.toggle.setObjectName('navigation')
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(title)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(content)
        content.hide()
        self.toggle.toggled.connect(content.setVisible)


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
        c = theme_colors(QApplication.instance().property('appearance'))
        painter.setBrush(QColor(c['surface']))
        painter.setPen(QPen(QColor(c['border']), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), CONTROL_RADIUS, CONTROL_RADIUS)
        painter.end()
        super().paintEvent(event)
