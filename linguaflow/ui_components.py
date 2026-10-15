"""Shared desktop surfaces and short, optional interaction animations."""
import math

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from .qt_controls import text_label
from .ui_theme import theme_colors


def apply_floating_shadow(widget):
    """Use the control island's quiet depth for floating companion surfaces."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(24)
    effect.setOffset(0, 4)
    effect.setColor(QColor(0, 0, 0, 30))
    widget.setGraphicsEffect(effect)


def paint_floating_surface(painter, rect, radius=12):
    """A bounded soft shadow inside transparent popup margins; no OS shadow."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for spread in range(12, 0, -1):
        alpha = round(15 * math.exp(-.5 * (spread/5.)**2))
        painter.setPen(QPen(QColor(0, 0, 0, alpha), 2))
        shadow = QRectF(rect).adjusted(-spread, -spread, spread, spread).translated(0, 4)
        painter.drawRoundedRect(shadow, radius+spread, radius+spread)
    colors = theme_colors(QApplication.instance().property('appearance'))
    painter.setBrush(QColor(colors['surface']))
    painter.setPen(QPen(QColor(colors['border']), 1))
    painter.drawRoundedRect(QRectF(rect), radius, radius)


class PopupSurface(QObject):
    def __init__(self, popup):
        super().__init__(popup)
        configure_popup_surface(popup)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            painter = QPainter(watched)
            paint_floating_surface(painter, watched.rect().adjusted(12, 8, -12, -16))
            painter.end()
            return True
        return False


def configure_popup_surface(popup):
    """Let the shared island painter own the surface, without a second styled panel."""
    popup.setWindowFlags(popup.windowFlags() | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
    popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    popup.setAutoFillBackground(False)
    popup.setProperty('floatingPopup', True)
    popup.setStyleSheet('QWidget[floatingPopup="true"] { background: transparent; border: none; padding: 0; }')


class NavigationButton(QPushButton):
    """Align visible icon ink and text with root folders, without a blank arrow column."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.setFixedHeight(38)
        self.setStyleSheet('QPushButton { min-height: 38px; max-height: 38px; border: none; padding: 0; }')

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 40, 38)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())
        colors = theme_colors(QApplication.instance().property('appearance'))
        if self.isEnabled() and (self.underMouse() or self.isDown()):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors['selected' if self.isDown() else 'hover']))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 8, 8)
        # Keep the icon's visible stroke inside the same inset as the hover surface.
        self.icon().paint(painter, 9, (self.height()-18)//2, 18, 18,
            Qt.AlignmentFlag.AlignCenter, self.icon().Mode.Normal if self.isEnabled() else self.icon().Mode.Disabled)
        painter.setPen(QColor(colors['text'] if self.isEnabled() else colors['disabled']))
        painter.setFont(self.font())
        painter.drawText(self.rect().adjusted(41, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, self.text())


class ElidedLabel(QLabel):
    """Keep full plain text for accessibility; paint a bounded single line."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def display_text(self):
        return self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawText(self.contentsRect(), self.alignment(),
                         self.display_text())


class RecordingTitle(QStackedWidget):
    """Click the title to edit in place; persistence belongs to the window."""
    editRequested = Signal()
    submitted = Signal(str)

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.label = ElidedLabel(text)
        self.label.setWordWrap(False)
        self.label.setObjectName('recordingTitle')
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.setToolTip('点击修改录音名称')
        self.label.installEventFilter(self)
        self.editor = QLineEdit()
        self.editor.setMaxLength(64)
        self.editor.setAccessibleName('录音名称')
        self.editor.installEventFilter(self)
        self.editor.setStyleSheet('QLineEdit { padding: 2px 4px; min-height: 22px; }')
        self.editor.editingFinished.connect(lambda: self.submitted.emit(self.editor.text()))
        self.addWidget(self.label)
        self.addWidget(self.editor)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def text(self):
        return self.label.text()

    def setText(self, text):
        self.label.setText(text)
        self.label.setToolTip(text + '\n点击修改录音名称')
        self.editor.setText(text)
        self.setCurrentIndex(0)

    def begin_edit(self):
        self.editor.setText(self.text())
        self.setCurrentIndex(1)
        self.editor.setFocus()
        self.editor.selectAll()

    def eventFilter(self, watched, event):
        if watched is self.editor and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.setText(self.text())
            return True
        if watched is self.label and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self.editRequested.emit()
                return True
        return super().eventFilter(watched, event)


class AudioLevelMeter(QProgressBar):
    """A quiet continuous input rail; RMS maps to a useful quiet-to-loud range.

    This is presentation only: it neither changes PCM nor opens audio devices.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(16)
        self.setStyleSheet('min-height: 16px; max-height: 16px; padding: 0;')
        self.setMinimumWidth(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName('音频输入音量')
        self.display_level = 0.
        self.motion = QVariantAnimation(self)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self.paint_level)
        super().setValue(0)

    def sizeHint(self):
        return QSize(120, 16)

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
        rail = QRectF(1, (self.height()-4)/2, self.width()-2, 4)
        painter.setBrush(QColor(colors['border']))
        painter.drawRoundedRect(rail, 2, 2)
        if self.display_level > 0:
            rail.setWidth(max(4., rail.width()*self.display_level/100))
            painter.setBrush(QColor(colors['warning'] if self.value() > 96 else colors['focus']))
            painter.drawRoundedRect(rail, 2, 2)


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
        if self.choice.property('wrapChoices'):
            width = max(80, self.choice.view().viewport().width() - 84)
            height = option.fontMetrics.boundingRect(QRect(0, 0, width, 10000),
                int(Qt.TextFlag.TextWordWrap), str(index.data())).height()
            return QSize(width + 84, max(34, height + 16))
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
        if self.choice.property('wrapChoices'):
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, str(index.data()))
        else:
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
    def __init__(self, parent=None, *, island=False):
        super().__init__(parent)
        self.island = island
        self.choice_popup = QFrame(self, Qt.WindowType.Popup)
        self.choice_popup.setObjectName('choicePopup')
        self.choice_popup._soft_surface = PopupSurface(self.choice_popup)
        self.choice_popup.installEventFilter(self.choice_popup._soft_surface)
        layout = QVBoxLayout(self.choice_popup)
        layout.setContentsMargins(16, 12, 16, 20)
        layout.setSpacing(6)
        view = self._choice_view = QListView(self.choice_popup)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setStyleSheet('QListView { background: transparent; border: none; padding: 0; outline: none; }')
        layout.addWidget(view)
        view.setItemDelegate(ChoiceDelegate(self))
        view.clicked.connect(self.choose_index)
        view.installEventFilter(self)
        view.setMouseTracking(True)
        view.setUniformItemSizes(True)
        view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMaxVisibleItems(8)
        self.currentTextChanged.connect(self.setToolTip)
        view.entered.connect(lambda index: view.viewport().setToolTip(str(index.data() or '')))
        if island:
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
            self.setProperty('islandChoice', True)
            self.setProperty('wrapChoices', True)
            self.setProperty('iconOnly', True)
            self.setFixedSize(40, 40)
            self.setStyleSheet('QComboBox { min-height: 40px; max-height: 40px; min-width: 40px; max-width: 40px; border: none; padding: 0; }')
            self.setMinimumContentsLength(12)
            self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            view.setUniformItemSizes(False)
            view.setWordWrap(True)
            self.currentTextChanged.connect(self.setAccessibleDescription)
            self.refresh_button = QPushButton('刷新音频来源', self)
            self.refresh_button.setObjectName('quiet')
            self.refresh_button.setFixedHeight(36)
            self.refresh_button.setStyleSheet('QPushButton { min-height: 36px; max-height: 36px; border: none; padding: 0 8px; }')
            self.refresh_button.hide()

    def mousePressEvent(self, event):
        if self.island and not self.count() and event.button() == Qt.MouseButton.LeftButton:
            self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)

    def view(self):
        return self._choice_view

    def choose_index(self, index):
        if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.setCurrentIndex(index.row())
            self.hidePopup()
            self.activated.emit(index.row())
            self.textActivated.emit(self.itemText(index.row()))

    def eventFilter(self, watched, event):
        if watched is self._choice_view and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.choose_index(watched.currentIndex())
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.hidePopup()
                return True
        return super().eventFilter(watched, event)

    def hidePopup(self):
        self.choice_popup.hide()
        super().hidePopup()

    def showPopup(self):
        if not self.count() and not self.island:
            return
        view, popup = self.view(), self.choice_popup
        view.setModel(self.model())
        view.setModelColumn(self.modelColumn())
        view.setRootIndex(self.rootModelIndex())
        view.setCurrentIndex(self.model().index(self.currentIndex(), self.modelColumn(), self.rootModelIndex()))
        if self.island:
            if self.refresh_button.parentWidget() is not popup:
                popup.layout().addWidget(self.refresh_button)
            self.refresh_button.show()
        view.setVisible(bool(self.count()))
        bounds = self.screen().availableGeometry()
        longest = max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        width = min(max(self.width(), min(520, longest+116)), bounds.width()-24)
        view.setFixedWidth(max(1, width-32))
        view.doItemsLayout()
        rows = sum(view.sizeHintForRow(i) for i in range(min(self.count(), 8)))
        extra = self.refresh_button.height()+6 if self.island else 0
        height = min(rows+extra+32, bounds.height()-24)
        view.setFixedHeight(max(0, height-extra-32))
        point = self.mapToGlobal(QPoint(0, self.height()+5))
        x = min(max(bounds.left()+12, point.x()), bounds.right()-width-11)
        y = point.y() if point.y()+height <= bounds.bottom()-12 else self.mapToGlobal(QPoint(0, 0)).y()-height-5
        y = min(max(bounds.top()+12, y), bounds.bottom()-height-11)
        popup.setGeometry(x, y, width, height)
        popup.show()
        popup.layout().activate()
        view.scrollTo(view.currentIndex())
        (view if self.count() else self.refresh_button).setFocus(Qt.FocusReason.PopupFocusReason)

    def paintEvent(self, event):
        if self.island:
            text = self.currentText() or self.placeholderText()
            category, separator, name = text.partition(' · ')
            if separator and category in ('系统音频', '外部输入'):
                text = name
            icon = self.itemIcon(self.currentIndex())
            paint_island_choice(self, text, icon if not icon.isNull() else self.property('fallbackIcon'))
            return
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme_colors(QApplication.instance().property('appearance'))
        painter.setPen(QPen(QColor(c['muted'] if self.isEnabled() else c['disabled']), 1.4))
        x, y = self.width() - 17, self.height() / 2
        painter.drawLine(QPointF(x - 3, y - 1.5), QPointF(x, y + 1.5))
        painter.drawLine(QPointF(x, y + 1.5), QPointF(x + 3, y - 1.5))


def paint_island_choice(widget, text, icon):
    """One visual centre for the device choice and the language menu button."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    colors = theme_colors(QApplication.instance().property('appearance'))
    painter.setClipRect(widget.rect())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colors['hover']) if widget.underMouse() and widget.isEnabled()
                     else Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(widget.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)
    if widget.property('iconOnly'):
        if icon is not None:
            icon.paint(painter, (widget.width()-18)//2, (widget.height()-18)//2, 18, 18)
        return
    left = 10
    if not icon.isNull():
        icon.paint(painter, left, (widget.height()-18)//2, 18, 18)
        left += 26
    text_rect = widget.rect().adjusted(left, 0, -28, 0)
    painter.setPen(QColor(colors['text'] if widget.isEnabled() else colors['disabled']))
    painter.setFont(widget.font())
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter,
        widget.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width()))
    painter.setPen(QPen(QColor(colors['muted'] if widget.isEnabled() else colors['disabled']), 1.4))
    x, y = widget.width()-15, widget.height()/2
    painter.drawLine(QPointF(x-3, y-1.5), QPointF(x, y+1.5))
    painter.drawLine(QPointF(x, y+1.5), QPointF(x+3, y-1.5))


class IslandButton(QPushButton):
    """Keep native button actions, labels and accessibility with compact paint."""
    def __init__(self, text, *, icon_only=False, parent=None):
        super().__init__(text, parent)
        self.icon_only = icon_only
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.setFixedHeight(40)
        self.setStyleSheet('QPushButton { min-height: 40px; max-height: 40px; border: none; padding: 0; }')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(text)
        self.setIconSize(QSize(18, 18))
        if icon_only:
            self.setProperty('transportControl', True)
            self.setFixedSize(40, 40)
        else:
            self.setProperty('islandChoice', True)
            self.setMinimumWidth(100)
            self.setMaximumWidth(210)

    def sizeHint(self):
        return QSize(40 if self.icon_only else min(210, self.fontMetrics().horizontalAdvance(self.text())+64), 40)

    def minimumSizeHint(self):
        return QSize(40 if self.icon_only else 100, 40)

    def paintEvent(self, event):
        if self.icon_only:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipRect(self.rect())
            colors = theme_colors(QApplication.instance().property('appearance'))
            primary = self.objectName() == 'primary' and self.isEnabled()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors['primary'] if primary else colors['hover']) if primary or self.underMouse() or self.isDown() else Qt.BrushStyle.NoBrush)
            circle = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
            painter.drawEllipse(circle)
            if self.isEnabled() and (self.underMouse() or self.isDown()):
                painter.setBrush(QColor(colors['selected' if self.isDown() else 'hover']))
                painter.drawEllipse(circle)
            self.icon().paint(painter, (self.width()-18)//2, (self.height()-18)//2, 18, 18,
                              Qt.AlignmentFlag.AlignCenter,
                              self.icon().Mode.Normal if self.isEnabled() else self.icon().Mode.Disabled)
        else:
            paint_island_choice(self, self.text(), self.icon())


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
        self.compact = False  # The constructor already installs the wide layout.
        self.playback_mode = False
        self.companion = None
        self.reveal_row = None
        self._placed_height = 0
        self._placed_recording = False
        self._placed_playback = False
        self._target_geometry = QRect()
        self.content = QWidget(self)
        self.resize_motion = QVariantAnimation(self)
        self.resize_motion.setDuration(200)
        self.resize_motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.resize_motion.valueChanged.connect(self._advance_geometry)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.placement = QTimer(self)
        self.placement.setSingleShot(True)
        self.placement.timeout.connect(self.place)
        viewport.installEventFilter(self)
        apply_floating_shadow(self)

    def eventFilter(self, widget, event):
        if event.type() == QEvent.Type.Resize:
            self.placement.start(0)
        return False

    def event(self, event):
        if event.type() == QEvent.Type.LayoutRequest and hasattr(self, 'placement'):
            self.placement.start(0)
        return super().event(event)

    def sizeHint(self):
        return self.content.sizeHint() + QSize(2, 2) if hasattr(self, 'content') else QSize(1, 1)

    def _advance_geometry(self, rect):
        self.setGeometry(rect)
        self.content.move((self.width()-self.content.width())//2, self.height()-self.content.height()-1)
        if self.reveal_row is not None:
            row = self.reveal_row
            rect = row.rect().translated(row.mapTo(self, QPoint(0, 0)))
            if self.rect().adjusted(4, 4, -4, -4).contains(rect):
                row.clearMask()
            else:
                # Keep partial glyphs off the border while the new row is revealed.
                row.setMask(QRegion(QRect(-2, -2, 1, 1)))
        if self.height() != self._placed_height:
            self._placed_height = self.height()
            self.heightChanged.emit(self.height())
        self.raise_()
        if self.companion is not None and self.companion.isVisible():
            self.companion.raise_()

    def place(self):
        viewport = self.parentWidget()
        available = max(1, viewport.width()-32)
        compact = available < 360
        if compact != self.compact:
            self.compact = compact
            self.compactChanged.emit(compact)
        layout = self.content.layout()
        layout.activate()
        diameter = layout.sizeHint().height()+2
        reserve = diameter+10 if self.playback_mode else 0
        preferred = layout.sizeHint().width()+2
        if self.property('recording'):
            preferred = 288
        width = min(max(1, available-reserve), 640 if self.playback_mode else preferred)
        self.content.setFixedWidth(max(1, width-2))
        layout.activate()
        height = layout.sizeHint().height()+2
        self.content.setFixedHeight(max(1, height-2))
        left = (viewport.width()-width-reserve)//2
        bottom = viewport.height()-18
        target = QRect(left, max(12, bottom-height), width, height)
        if (target == self._target_geometry and motion_enabled()
                and self.resize_motion.state() != self.resize_motion.State.Stopped):
            return
        recording = bool(self.property('recording'))
        animate = (self._placed_height and self.isVisible() and motion_enabled()
                   and recording != self._placed_recording and not self.playback_mode and not self._placed_playback)
        self._placed_recording, self._placed_playback = recording, self.playback_mode
        self._target_geometry = target
        self.resize_motion.stop()
        if animate:
            self.resize_motion.setStartValue(self.geometry())
            self.resize_motion.setEndValue(target)
            self.resize_motion.start()
        else:
            self._advance_geometry(target)
        if self.companion is not None and self.playback_mode:
            self.companion.set_metrics(height, max(height, bottom-12))
            self.companion.move(left+self.width()+10, max(12, bottom-self.companion.height()))
            self.companion.raise_()


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
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 20)
        self.surface = QFrame()
        self.surface.setObjectName('dialogSurface')
        apply_floating_shadow(self.surface)
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
        close.setStyleSheet('QPushButton { min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; border: none; padding: 0; }')
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
        configure_popup_surface(self)
        self.setStyleSheet(self.styleSheet() + ' QMenu#actionMenu { padding: 16px; }')
        self.setMinimumWidth(220)
        self.setToolTipsVisible(True)
        self.setObjectName('actionMenu')

    def paintEvent(self, event):
        painter = QPainter(self)
        paint_floating_surface(painter, self.rect().adjusted(12, 8, -12, -16))
        painter.end()
        super().paintEvent(event)
