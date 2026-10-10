"""Chat-style caption following; scroll position, not a preference, owns the state."""
import math
import time
from bisect import bisect_right

from PySide6.QtCore import QEvent, QPointF, Qt, QTextBoundaryFinder, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea

from .ui_components import motion_enabled
from .ui_theme import theme_colors


class CaptionText(QLabel):
    """Reveal appended text without delaying data or changing the full-text layout.

    Revisions replace old text immediately. Appends retarget one bounded reveal,
    rather than queueing animations behind ongoing recognition.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._visible_units = 0
        self._boundaries = [0]
        self._start_units = 0
        self._started = 0.
        self._duration = .32
        self.reveal = QTimer(self)
        self.reveal.setTimerType(Qt.TimerType.PreciseTimer)
        self.reveal.setInterval(16)
        self.reveal.timeout.connect(self._advance)

    def setText(self, text):
        self.set_caption_text(text, animate=False)

    def set_caption_text(self, text, *, animate=True):
        old = self.text()
        if text == old:
            if not animate or not motion_enabled():
                self.finish_reveal()
            return
        was_revealing = self.reveal.isActive()
        super().setText(text)
        finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
        self._boundaries = [0]
        while (boundary := finder.toNextBoundary()) >= 0:
            self._boundaries.append(boundary)
        if not animate or not motion_enabled() or not text.startswith(old):
            self.finish_reveal()
            return
        # Full QLabel text and size hints are available from the first frame.
        # An existing reveal keeps its deadline when newer text arrives.
        if not was_revealing:
            self._visible_units = len(old.encode('utf-16-le')) // 2
            self._start_units = self._visible_units
            self._started = time.monotonic()
            self._duration = min(.32, max(.08, (len(text)-len(old)) * .016))
        # Appended combining marks / emoji joiners can extend the last grapheme.
        self._visible_units = self._boundaries[bisect_right(self._boundaries, self._visible_units)-1]
        self.reveal.start()
        self.update()

    def finish_reveal(self):
        self.reveal.stop()
        self._visible_units = self._boundaries[-1]
        self.update()

    def _advance(self):
        progress = min(1., (time.monotonic()-self._started) / self._duration)
        if progress >= 1 or not motion_enabled() or not self.isVisible():
            self.finish_reveal()
            return
        target = self._start_units + (self._boundaries[-1]-self._start_units) * progress
        self._visible_units = max(self._visible_units, self._boundaries[bisect_right(self._boundaries, target)-1])
        self.update()

    def mousePressEvent(self, event):
        # Selection and copying use Qt's complete text immediately.
        self.finish_reveal()
        super().mousePressEvent(event)

    def hideEvent(self, event):
        self.finish_reveal()
        super().hideEvent(event)

    def paintEvent(self, event):
        if not self.reveal.isActive():
            super().paintEvent(event)
            return
        layout = QTextLayout(self.text().replace('\n', '\u2028'), self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        hidden = QTextLayout.FormatRange()
        hidden.start = self._visible_units
        hidden.length = self._boundaries[-1]-hidden.start
        hidden.format.setForeground(QColor(0, 0, 0, 0))
        layout.setFormats([hidden])
        bounds = self.contentsRect().adjusted(self.margin(), self.margin(), -self.margin(), -self.margin())
        height = 0.
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, bounds.width()))
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.setClipRect(bounds)
        layout.draw(painter, QPointF(bounds.x(), bounds.y()+max(0, (bounds.height()-height)/2)))


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
        colors = theme_colors(self.window().property('appearance'))
        painter.setBrush(QColor(colors['hover'] if self.underMouse() else colors['control']))
        painter.setPen(QPen(QColor(colors['focus'] if self.hasFocus() else colors['border']), 1))
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.setPen(QPen(QColor(colors['text']), 1.8, Qt.PenStyle.SolidLine,
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
        self._overlay_height = 0
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
        self.latest_button.move((viewport.width()-40)//2, max(0, viewport.height()-56-self._overlay_height))
        self.latest_button.setVisible(not self.following and not self._at_bottom())
        self.latest_button.raise_()

    def set_overlay_height(self, height):
        self._overlay_height = height + 18
        self._update_button()

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
