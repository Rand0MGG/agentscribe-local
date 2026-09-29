"""Chat-style caption following; scroll position, not a preference, owns the state."""
import math
import time

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QScrollArea

from .ui_components import motion_enabled


class LatestButton(QPushButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('回到最新字幕')
        self.setAccessibleName('回到最新字幕并恢复自动跟随')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor('#454549' if self.underMouse() else '#303034'))
        painter.setPen(QPen(QColor('#d6d6dc' if self.hasFocus() else '#626269'), 1))
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.setPen(QPen(QColor('#f0f0f3'), 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(20, 12), QPointF(20, 27))
        painter.drawLine(QPointF(14, 21), QPointF(20, 27))
        painter.drawLine(QPointF(20, 27), QPointF(26, 21))


class CaptionScrollArea(QScrollArea):
    followingChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.following = True
        self._moving = False
        self._snap_next = False
        self._anchor = None
        self._position = 0.
        self._last_tick = 0.
        self.latest_button = LatestButton(self.viewport())
        self.latest_button.clicked.connect(self.jump_to_latest)
        self.latest_button.hide()
        self.animation = QTimer(self)
        self.animation.setTimerType(Qt.TimerType.PreciseTimer)
        self.animation.setInterval(16)
        self.animation.timeout.connect(self._tick)
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self._settle_layout)
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(self.content_changed)
        bar.valueChanged.connect(self._position_changed)
        bar.sliderPressed.connect(self._interrupt)
        bar.sliderReleased.connect(self._sync_position)
        bar.actionTriggered.connect(self._interrupt)
        self.viewport().installEventFilter(self)
        self.installEventFilter(self)

    def _at_bottom(self):
        bar = self.verticalScrollBar()
        return bar.maximum() - bar.value() <= 2

    def _set_following(self, value):
        if value:
            self._anchor = None
        if self.following != value:
            self.following = value
            self.followingChanged.emit(value)
        self._update_button()

    def _update_button(self):
        viewport = self.viewport()
        self.latest_button.move((viewport.width()-40)//2, max(0, viewport.height()-56))
        self.latest_button.setVisible(not self.following and not self._at_bottom())
        self.latest_button.raise_()

    def _interrupt(self, *args):
        self.animation.stop()
        self._anchor = None
        self._snap_next = False
        self._set_following(False)
        QTimer.singleShot(0, self._sync_position)

    def _sync_position(self):
        # A queued input check must not cancel following already restored by a
        # valueChanged signal, if new content arrived in the meantime.
        if not self.following and not self.animation.isActive() and not self.verticalScrollBar().isSliderDown():
            self._set_following(self._at_bottom())

    def _position_changed(self, value):
        if not self._moving:
            self._anchor = None
            self.animation.stop()
            self._set_following(self._at_bottom())

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.Resize and watched is self.viewport():
            self._update_button()
            self.content_changed()
        elif kind == QEvent.Type.Wheel:
            # macOS sends zero-delta begin/end events, including after the user
            # clicks back to latest. Only actual vertical motion interrupts.
            # Leave direction, pixel deltas and momentum scrolling to Qt.
            if event.pixelDelta().y() or event.angleDelta().y():
                self._interrupt()
        elif kind == QEvent.Type.TouchBegin:
            self._interrupt()
        elif kind == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Space):
            self._interrupt()
        return super().eventFilter(watched, event)

    def prepare_update(self):
        """Anchor the currently read card when earlier cards resize or disappear."""
        if self.following or self._anchor is not None or not self.widget():
            return
        top = self.verticalScrollBar().value()
        layout = self.widget().layout()
        if layout:
            for i in range(layout.count()):
                card = layout.itemAt(i).widget()
                if card and card.isVisible() and card.y()+card.height() > top:
                    self._anchor = (card, card.y()-top)
                    break

    def content_changed(self, *args):
        self.layout_timer.start(0)

    def _settle_layout(self):
        if self._anchor is not None:
            card, offset = self._anchor
            # Keep the reading anchor through subsequent layout passes. Qt can
            # resize wrapping labels again after a newly inserted card is shown.
            try:
                if not card.isHidden():
                    self._move(card.y()-offset)
                else:
                    self._anchor = None
            except RuntimeError:  # A pruned card's Qt object has already been deleted.
                self._anchor = None
        self._update_button()
        if not self.following:
            self._sync_position()
            return
        if self._snap_next or not motion_enabled():
            self.animation.stop()
            self._move(self.verticalScrollBar().maximum())
            self._snap_next = False
        elif not self.animation.isActive() and not self._at_bottom():
            self._position = float(self.verticalScrollBar().value())
            self._last_tick = time.monotonic()
            self.animation.start()

    def _move(self, value):
        self._moving = True
        try:
            self.verticalScrollBar().setValue(round(value))
        finally:
            self._moving = False

    def _tick(self):
        if not self.following:
            self.animation.stop()
            return
        now = time.monotonic()
        dt = min(now-self._last_tick, .05)
        self._last_tick = now
        target = self.verticalScrollBar().maximum()
        # Retarget the existing motion; frequent ASR updates never restart it.
        self._position += (target-self._position) * (1-math.exp(-dt/.085))
        if abs(target-self._position) < .8 or not motion_enabled():
            self._position = target
            self.animation.stop()
        self._move(self._position)

    def jump_to_latest(self, checked=False):
        self._anchor = None
        self._set_following(True)
        self.content_changed()

    def reset_follow(self):
        self.animation.stop()
        self._anchor = None
        self._snap_next = True
        self._set_following(True)
        self.content_changed()
