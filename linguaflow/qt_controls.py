"""Small reusable Qt presentation adapters with no application dependencies."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractItemView, QLabel, QPushButton, QSlider, QStyle, QStyleOptionSlider


class ClickSlider(QSlider):
    """Click anywhere on the track to seek, then continue dragging normally."""
    def _position_at(self, point):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                             QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                             QStyle.SubControl.SC_SliderHandle, self)
        if self.orientation() == Qt.Orientation.Horizontal:
            start, span, position = groove.x(), groove.width()-handle.width(), point.x()-handle.width()/2
        else:
            start, span, position = groove.y(), groove.height()-handle.height(), point.y()-handle.height()/2
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), round(position-start),
                                              max(1, span), option.upsideDown)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setSliderDown(True)
            self.setSliderPosition(self._position_at(event.position()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown() and event.buttons() & Qt.MouseButton.LeftButton:
            self.setSliderPosition(self._position_at(event.position()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderPosition(self._position_at(event.position()))
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


def text_label(text, name=None):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        label.setObjectName(name)
    return label


def data_index(combo, value):
    """Python equality also handles tuple item data (QVariant matching does not)."""
    return next((i for i in range(combo.count()) if combo.itemData(i) == value), -1)


class FocusVisibility(QObject):
    """Keep keyboard focus visible without leaving mouse-click borders behind."""
    def eventFilter(self, widget, event):
        if (event.type() == QEvent.Type.MouseButtonPress
                and isinstance(getattr(widget, 'parentWidget', lambda: None)(), QAbstractItemView)):
            widget = widget.parentWidget()
        if isinstance(widget, (QPushButton, QAbstractItemView)):
            kind = event.type()
            visible = None
            if kind == QEvent.Type.FocusIn:
                visible = event.reason() in (Qt.FocusReason.TabFocusReason,
                                              Qt.FocusReason.BacktabFocusReason,
                                              Qt.FocusReason.ShortcutFocusReason)
            elif kind == QEvent.Type.MouseButtonPress:
                visible = False
            if visible is not None and widget.property('keyboardFocus') != visible:
                widget.setProperty('keyboardFocus', visible)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
        return False


def install_focus_visibility(app):
    if not hasattr(app, '_agentscribe_focus_visibility'):
        app._agentscribe_focus_visibility = FocusVisibility(app)
        app.installEventFilter(app._agentscribe_focus_visibility)
