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
from PySide6.QtGui import QAction, QColor, QPainter, QPalette, QPen, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
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
    QScrollArea,
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
from .ui_theme import WINDOW_RADIUS, interaction_color, theme_colors


def apply_floating_shadow(widget):
    """Use the control island's quiet depth for floating companion surfaces."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(24)
    effect.setOffset(0, 4)
    effect.setColor(QColor(0, 0, 0, 30))
    widget.setGraphicsEffect(effect)


class ResponsiveRow(QFrame):
    """Reflow a setting from two columns to a readable label/control stack."""
    def __init__(self, title, description, control, parent=None):
        super().__init__(parent)
        self.setObjectName('settingsRow')
        self.control = control
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0, 16, 0, 16)
        self.box.setSpacing(16)
        words = QWidget()
        words.setMinimumWidth(0)
        words.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        labels = QVBoxLayout(words)
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(6)
        labels.addWidget(text_label(title, 'settingsLabel'))
        labels.addWidget(description if isinstance(description, QWidget) else text_label(description, 'muted'))
        self.box.addWidget(words, 1)
        self.box.addWidget(control)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        natural = min(self.control.maximumWidth(), self.control.sizeHint().width())
        stacked = self.width() < 240 + natural + self.box.spacing()
        self.box.setDirection(QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight)


def paint_window_shadow(painter, rect, radius=WINDOW_RADIUS):
    """Soft desktop shadow, slightly stronger than transient popup elevation."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    for spread in range(12, -1, -1):
        alpha = round(6 * math.exp(-.5 * (spread / 5.) ** 2))
        painter.setBrush(QColor(0, 0, 0, alpha))
        shadow = QRectF(rect).adjusted(-spread, -spread, spread, spread).translated(0, 4)
        painter.drawRoundedRect(shadow, radius + spread, radius + spread)


def paint_floating_surface(painter, rect, radius=12):
    """A bounded soft shadow inside transparent popup margins; no OS shadow."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    for spread in range(12, -1, -1):
        # Filled layers connect the offset shadow to the surface. Outlined
        # rings leave a transparent gap beneath its lower edge.
        alpha = round(4 * math.exp(-.5 * (spread/5.)**2))
        painter.setBrush(QColor(0, 0, 0, alpha))
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
        self.setFixedHeight(36)
        self.setStyleSheet('QPushButton { min-height: 36px; max-height: 36px; border: none; padding: 0; }')

    def sizeHint(self):
        if self.property('iconOnly'):
            return QSize(self.height(), self.height())
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 40, 36)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())
        colors = theme_colors(QApplication.instance().property('appearance'))
        if self.isEnabled() and (self.underMouse() or self.isDown()):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*interaction_color(QApplication.instance().property('appearance'), 'row_hover')))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)
        # Keep the icon's visible stroke inside the same inset as the hover surface.
        compact = self.property('iconOnly')
        self.icon().paint(painter, (self.width()-20)//2 if compact else 9, (self.height()-20)//2, 20, 20,
            Qt.AlignmentFlag.AlignCenter, self.icon().Mode.Normal if self.isEnabled() else self.icon().Mode.Disabled)
        if compact:
            return
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
    # The shared progress rail is only six pixels high. Percentages belong to
    # the accompanying status label, never clipped inside the rail.
    bar.setTextVisible(False)


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
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c['selected_hover' if selected and hovered else 'selected' if selected else 'hover']))
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
        self.setProperty('keyboardFocus', False)
        self.setProperty('popupOpen', False)
        layout = QVBoxLayout(self.choice_popup)
        # Surface and item insets leave 8 px at each visible panel edge.
        layout.setContentsMargins(16, 14, 16, 22)
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
        view.entered.connect(self.update_item_tooltip)
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
        self.choice_popup.installEventFilter(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_keyboard_focus(False)
            if self.choice_popup.isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)

    def set_keyboard_focus(self, enabled):
        if self.property('keyboardFocus') != enabled:
            self.setProperty('keyboardFocus', enabled)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def focusInEvent(self, event):
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.set_keyboard_focus(event.reason() in (
                Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                Qt.FocusReason.ShortcutFocusReason))
        super().focusInEvent(event)

    def update_item_tooltip(self, index):
        text = str(index.data() or '')
        fits = self.fontMetrics().horizontalAdvance(text) <= self.view().viewport().width()-50
        self.view().viewport().setToolTip('' if fits else text)

    def view(self):
        return self._choice_view

    def choose_index(self, index):
        if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.setCurrentIndex(index.row())
            self.hidePopup()
            self.activated.emit(index.row())
            self.textActivated.emit(self.itemText(index.row()))

    def eventFilter(self, watched, event):
        if watched is self.window() and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self.hidePopup()
        if watched is self.choice_popup:
            if event.type() == QEvent.Type.MouseButtonPress and not watched.rect().contains(event.position().toPoint()):
                # Qt resets this attribute at the start of a popup press. Set
                # it on the closing event so the click cannot reopen its anchor.
                watched.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, True)
                self.hidePopup()
                event.accept()
                return True
            if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
                self.setProperty('popupOpen', event.type() == QEvent.Type.Show)
                self.update()
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
        if popup.isVisible():
            return
        view.setModel(self.model())
        view.setModelColumn(self.modelColumn())
        view.setRootIndex(self.rootModelIndex())
        view.setCurrentIndex(self.model().index(self.currentIndex(), self.modelColumn(), self.rootModelIndex()))
        if self.island:
            if self.refresh_button.parentWidget() is not popup:
                popup.layout().addWidget(self.refresh_button)
            self.refresh_button.show()
        view.setVisible(bool(self.count()))
        owner = self.window()
        bounds = self.screen().availableGeometry()
        if owner is not self:
            bounds = bounds.intersected(QRect(owner.mapToGlobal(QPoint()), owner.size()))
        bounds = bounds.adjusted(8, 8, -8, -8)
        longest = max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        width = min(max(self.width(), min(520, longest+116)), bounds.width())
        view.setFixedWidth(max(1, width-32))
        view.doItemsLayout()
        rows = sum(view.sizeHintForRow(i) for i in range(min(self.count(), 8)))
        extra = self.refresh_button.height()+6 if self.island else 0
        anchor = self.mapToGlobal(QPoint())
        below = max(0, bounds.bottom()+1-(anchor.y()+self.height()+5))
        above = max(0, anchor.y()-5-bounds.top())
        desired = rows+extra+36
        down = desired <= below or below >= above
        height = min(desired, below if down else above)
        view.setFixedHeight(max(0, height-extra-36))
        x = max(bounds.left(), min(anchor.x(), bounds.right()+1-width))
        y = anchor.y()+self.height()+5 if down else anchor.y()-height-5
        # Drop the previous opening's minimum size before shrinking/repositioning.
        popup.layout().activate()
        popup.setGeometry(x, y, width, height)
        popup.show()
        popup.layout().activate()
        view.scrollTo(view.currentIndex())
        (view if self.count() else self.refresh_button).setFocus(Qt.FocusReason.PopupFocusReason)
        if owner is not self:
            owner.installEventFilter(self)

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
        direction = -1 if self.choice_popup.isVisible() else 1
        painter.drawLine(QPointF(x-4, y-2*direction), QPointF(x, y+2*direction))
        painter.drawLine(QPointF(x, y+2*direction), QPointF(x+4, y-2*direction))


def paint_island_choice(widget, text, icon):
    """One visual centre for the device choice and the language menu button."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    colors = theme_colors(QApplication.instance().property('appearance'))
    painter.setClipRect(widget.rect())
    painter.setPen(Qt.PenStyle.NoPen)
    pressed = bool(widget.property('popupOpen')) or (isinstance(widget, QPushButton) and widget.isDown())
    painter.setBrush(QColor(*interaction_color(QApplication.instance().property('appearance'), 'ghost_hover'))
                     if widget.isEnabled() and (pressed or widget.underMouse()) else Qt.BrushStyle.NoBrush)
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
    direction = -1 if widget.property('popupOpen') else 1
    painter.drawLine(QPointF(x-3, y-1.5*direction), QPointF(x, y+1.5*direction))
    painter.drawLine(QPointF(x, y+1.5*direction), QPointF(x+3, y-1.5*direction))


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
            appearance = QApplication.instance().property('appearance')
            fill = (QColor(*interaction_color(appearance, 'primary_hover')) if self.isDown() or self.underMouse()
                    else QColor(colors['primary'])) if primary else QColor(*interaction_color(appearance, 'ghost_hover'))
            painter.setBrush(fill if self.isEnabled() and (primary or self.underMouse() or self.isDown()) else Qt.BrushStyle.NoBrush)
            circle = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
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
        self.resize_motion.setDuration(280)
        self.resize_motion.setEasingCurve(QEasingCurve.Type.InOutCubic)
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
        if self.companion is not None and self.playback_mode:
            self.companion.move(self.x()+self.width()+10,
                                max(12, self.y()+self.height()-self.companion.height()))
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
                   and (recording != self._placed_recording or self.playback_mode != self._placed_playback
                        or self.resize_motion.state() != self.resize_motion.State.Stopped))
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

    def hideEvent(self, event):
        self.fade.stop()
        super().hideEvent(event)

    @staticmethod
    def platform_supports_opacity():
        return QApplication.platformName() != 'offscreen'

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and event.position().y() < 100
                and self.windowHandle()):
            self.windowHandle().startSystemMove()
        super().mousePressEvent(event)


class NameDialog(SurfaceDialog):
    def __init__(self, title, description, parent=None, *, text='', label='名称', confirm_text='保存'):
        super().__init__(title, description, parent)
        self.composing = False
        self.body.addWidget(text_label(label, 'settingsLabel'))
        self.field = QLineEdit(text)
        self.field.setAccessibleName(label)
        self.field.setMaxLength(64)
        self.field.setPlaceholderText('输入名称')
        self.field.installEventFilter(self)
        self.error = text_label('', 'muted')
        self.error.setProperty('validationError', True)
        self.body.addWidget(self.field)
        self.body.addWidget(self.error)
        self.actions.addStretch()
        self.cancel = QPushButton('取消')
        self.cancel.clicked.connect(self.reject)
        self.save = QPushButton(confirm_text)
        self.save.setObjectName('primary')
        self.save.clicked.connect(self.validate)
        for button in (self.cancel, self.save):
            button.setAutoDefault(False)
            self.actions.addWidget(button)
        self.field.textChanged.connect(self.clear_error)

    def eventFilter(self, watched, event):
        if watched is self.field and event.type() == QEvent.Type.InputMethod:
            self.composing = bool(event.preeditString())
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or (
                self.composing and event.key() == Qt.Key.Key_Escape):
            event.accept()
            return
        super().keyPressEvent(event)

    def clear_error(self):
        self.error.clear()
        if self.field.property('invalid'):
            self.field.setProperty('invalid', False)
            self.field.style().unpolish(self.field)
            self.field.style().polish(self.field)

    def validate(self):
        if self.composing:
            return
        if not self.field.text().strip():
            self.error.setText('名称不能为空。请填写后重试。')
            self.field.setProperty('invalid', True)
            self.field.style().unpolish(self.field)
            self.field.style().polish(self.field)
            self.field.setFocus()
            return
        self.accept()

    @classmethod
    def getText(cls, parent, title, label, text=''):
        dialog = cls(title, '为文件夹和录音起一个容易找到的名字。', parent,
                     text=text, label=label, confirm_text='保存' if text else '创建文件夹')
        dialog.field.selectAll()
        dialog.field.setFocus()
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.field.text(), accepted


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


class MenuActions(QMenu):
    """Native menu layout with one scale-safe, inset check mark."""
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(QApplication.instance().property('appearance'))
        for action in self.actions():
            if not (action.isVisible() and action.isCheckable() and action.isChecked()):
                continue
            rect = self.actionGeometry(action)
            pen = QPen(QColor(colors['text' if action.isEnabled() else 'disabled']), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            x, y = rect.left()+13, rect.center().y()
            painter.drawLine(QPointF(x-4, y), QPointF(x-1, y+3))
            painter.drawLine(QPointF(x-1, y+3), QPointF(x+5, y-4))


class ActionMenu(MenuActions):
    """Native actions, with an actual scroll viewport when the owner is too small."""
    def __init__(self, parent=None):
        super().__init__(parent)
        configure_popup_surface(self)
        self.setMinimumWidth(220)
        self.setToolTipsVisible(True)
        self.setObjectName('actionMenu')
        self.setStyleSheet('QMenu#actionMenu { padding: 16px; menu-scrollable: 1; }')
        self._scroll = None
        self._inner = None
        self._original_actions = None
        self._menu_size = QSize()
        self._projections = {}

    def available_bounds(self):
        bounds = self.screen().availableGeometry()
        owner = self.parentWidget()
        while owner is not None and isinstance(owner.window(), QMenu):
            owner = owner.window().parentWidget()
        if owner is not None:
            owner = owner.window()
            bounds = bounds.intersected(QRect(owner.mapToGlobal(QPoint()), owner.size()))
        return bounds.adjusted(8, 8, -8, -8)

    def actions(self):
        return list(self._original_actions) if self._original_actions is not None else super().actions()

    def activeAction(self):
        return next((action for action, projected in self._projections.items()
                     if projected is self._inner.activeAction()), None) if self._inner else super().activeAction()

    def setActiveAction(self, action):
        if self._inner:
            projected = self._projections.get(action)
            self._inner.setActiveAction(projected)
            if projected:
                rect = self._inner.actionGeometry(projected)
                self._scroll.ensureVisible(rect.center().x(), rect.center().y(), 0, rect.height()//2+4)
        else:
            super().setActiveAction(action)

    def actionGeometry(self, action):
        if self._inner:
            rect = self._inner.actionGeometry(self._projections.get(action))
            rect.moveTopLeft(self._inner.mapTo(self, rect.topLeft()))
            return rect
        return super().actionGeometry(action)

    def _activate(self, action):
        menu = self
        while isinstance(menu, QMenu):
            menu.hide()
            menu = menu.parentWidget()

    def _scroll_to_active(self):
        if self._inner and self._inner.activeAction():
            rect = self._inner.actionGeometry(self._inner.activeAction())
            self._scroll.ensureVisible(rect.center().x(), rect.center().y(), 0, rect.height()//2+4)

    def _make_scrollable(self, bounds):
        natural = super().sizeHint()
        if natural.height() <= bounds.height() and natural.width() <= bounds.width():
            return
        self._original_actions = super().actions()
        self._inner = MenuActions()
        self._inner.setObjectName('scrollActions')
        self._inner.setStyleSheet(QApplication.instance().styleSheet() + '\nQMenu#scrollActions { background: transparent; border: none; padding: 0; menu-scrollable: 1; }')
        # Keep native actions owned solely by their original menu. Temporary
        # viewport actions must not transfer PySide ownership of active actions.
        for action in self._original_actions:
            projected = QAction(self._inner)
            projected.setText(action.text())
            projected.setIcon(action.icon())
            projected.setToolTip(action.toolTip())
            projected.setSeparator(action.isSeparator())
            projected.setCheckable(action.isCheckable())
            projected.setChecked(action.isChecked())
            projected.setEnabled(action.isEnabled())
            projected.setVisible(action.isVisible())
            projected.setMenu(action.menu())
            projected.triggered.connect(lambda checked=False, original=action: original.trigger())
            projected.triggered.connect(lambda checked=False, original=action: self._activate(original))
            self._projections[action] = projected
            self._inner.addAction(projected)
        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._inner)
        self._inner.setWindowFlags(Qt.WindowType.Widget)
        self._inner.ensurePolished()
        self._menu_size = QSize(min(natural.width(), bounds.width()), min(natural.height(), bounds.height()))
        self._inner.setFixedSize(max(1,self._menu_size.width()-44), self._inner.sizeHint().height())
        self._scroll.setParent(self)
        self._scroll.show()
        self._inner.show()
        self._inner.installEventFilter(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._scroll:
            self._scroll.setGeometry(self.rect().adjusted(20,16,-20,-24))

    def eventFilter(self, watched, event):
        if watched is self._inner and event.type() == QEvent.Type.KeyRelease:
            self._scroll_to_active()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if self._inner:
            if event.key() == Qt.Key.Key_Escape:
                self.hide()
            else:
                self._inner.keyPressEvent(event)
                self._scroll_to_active()
            event.accept()
            return
        super().keyPressEvent(event)

    def constrain(self):
        bounds = self.available_bounds()
        self.setMaximumSize(bounds.size())
        size = self._menu_size if self._scroll else super().sizeHint()
        self.resize(min(size.width(), bounds.width()), min(size.height(), bounds.height()))
        self.move(max(bounds.left(), min(self.x(), bounds.right()+1-self.width())),
                  max(bounds.top(), min(self.y(), bounds.bottom()+1-self.height())))

    def showEvent(self, event):
        self._projections = {}
        self._make_scrollable(self.available_bounds())
        super().showEvent(event)
        self.constrain()
        QTimer.singleShot(0, self.constrain)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._original_actions is not None:
            self._original_actions = None
            self._projections = {}
            self._scroll.hide()
            self._scroll.deleteLater()
            self._inner = self._scroll = None
        self.setMaximumSize(16777215,16777215)

    def paintEvent(self, event):
        painter = QPainter(self)
        paint_floating_surface(painter, self.rect().adjusted(12, 8, -12, -16))
        painter.end()
        if self._scroll is None:
            super().paintEvent(event)
