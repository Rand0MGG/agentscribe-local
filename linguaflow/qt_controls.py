"""Small reusable Qt presentation adapters with no application dependencies."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSlider, QStyle, QStyleOptionSlider


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
