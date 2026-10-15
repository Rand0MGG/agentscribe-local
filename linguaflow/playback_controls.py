"""Playback-only volume surface; changing it never touches system volume."""
from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton

from .qt_controls import ClickSlider as QSlider
from .ui_components import apply_floating_shadow, motion_enabled
from .ui_theme import theme_colors


class PlaybackVolume(QFrame):
    """A same-height circle unfolds upwards, preserving the seek bar's width."""
    valueChanged = Signal(int)
    extentChanged = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        apply_floating_shadow(self)
        self.diameter = 64
        self.extra = 112
        self.progress = 0.
        self.button = QPushButton(self)
        self.button.setObjectName('playbackVolumeButton')
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.button.setCheckable(True)
        self.button.setAccessibleName('回放音量')
        self.button.setToolTip('调整回放音量')
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setStyleSheet('background: transparent; border: none; padding: 0;')
        self.slider = QSlider(Qt.Orientation.Vertical, self)
        self.slider.setObjectName('playbackVolumeSlider')
        self.slider.setRange(0, 300)
        self.slider.setValue(100)
        self.slider.setAccessibleName('回放音量百分比')
        self.value = QLabel('100%', self)
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value.setStyleSheet('background: transparent; border: none; font-size: 11px;')
        self.slider.valueChanged.connect(self._value_changed)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._advance)
        self.button.toggled.connect(self.set_expanded)
        self._advance(0.)
        self.hide()

    def _value_changed(self, value):
        self.value.setText(f'{value}%')
        self.button.setToolTip(f'回放音量 {value}% · 点击展开或收起')
        self.slider.setToolTip(f'{value}%')
        self.valueChanged.emit(value)

    def set_expanded(self, expanded):
        self.animation.stop()
        self.button.setChecked(expanded)
        target = float(expanded)
        if not motion_enabled() or not self.isVisible():
            self._advance(target)
            return
        self.animation.setStartValue(self.progress)
        self.animation.setEndValue(target)
        self.animation.start()

    def set_metrics(self, diameter, available_height):
        extra = min(112, max(0, available_height-diameter))
        if (self.diameter, self.extra) != (diameter, extra):
            self.diameter, self.extra = diameter, extra
            self._advance(self.progress)

    def _advance(self, value):
        self.progress = float(value)
        self.setFixedSize(self.diameter, self.diameter+round(self.extra*self.progress))
        self.button.setGeometry(0, self.height()-self.diameter, self.diameter, self.diameter)
        track = max(0, self.height()-self.diameter-40)
        self.slider.setGeometry((self.width()-24)//2, 12, 24, track)
        self.slider.setVisible(track >= 24)
        self.value.setGeometry(0, self.height()-self.diameter-22, self.width(), 16)
        self.value.setVisible(track >= 24)
        self.extentChanged.emit()
        self.update()

    def hideEvent(self, event):
        self.animation.stop()
        self.button.setChecked(False)
        self._advance(0.)
        super().hideEvent(event)

    def paintEvent(self, event):
        colors = theme_colors(QApplication.instance().property('appearance'))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(colors['surface']))
        painter.setPen(QPen(QColor(colors['border']), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), self.diameter/2, self.diameter/2)
