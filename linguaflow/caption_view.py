"""Chat-style caption following; scroll position, not a preference, owns the state."""
import math
import time
from bisect import bisect_right

from PySide6.QtCore import QEvent, QPointF, Qt, QTextBoundaryFinder, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPalette, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QWidget

from .ui_components import motion_enabled
from .ui_theme import theme_colors


class CaptionText(QLabel):
    """Reveal appended text without delaying data or changing the full-text layout.

    Revisions replace old text immediately. Appends retarget one bounded reveal,
    rather than queueing animations behind ongoing recognition.
    """

    activated = Signal()
    interactionChanged = Signal(str)

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
        self._press = None
        self._pointer_hit = False
        self._interaction = ''
        self._hit_key = None
        self._hit_rects = ()
        self.activate_timer = QTimer(self)
        self.activate_timer.setSingleShot(True)
        self.activate_timer.setInterval(QApplication.doubleClickInterval())
        self.activate_timer.timeout.connect(self._activate)

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
        # Keep tracking explicit after QLabel replaces its text control,
        # including translated revisions in interactive playback captions.
        self.setMouseTracking(bool(self.property('playbackClick')))
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
        if not self.reveal.isActive() and self._visible_units == self._boundaries[-1]:
            return
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
        self.activate_timer.stop()
        self._press = (event.position(), time.monotonic(), bool(self.selectedText())) if event.button() == Qt.MouseButton.LeftButton else None
        if self._press is not None and not self._press[2] and self.property('playbackClick') and self._text_contains(event.position()):
            self._set_interaction('pressed')
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None and (event.position()-self._press[0]).manhattanLength() >= QApplication.startDragDistance():
            self._press = None
        super().mouseMoveEvent(event)
        self._update_pointer(event.position(), event.buttons())

    def enterEvent(self, event):
        super().enterEvent(event)
        if hasattr(event, 'position'):
            self._update_pointer(event.position())

    def leaveEvent(self, event):
        self._pointer_hit = False
        self.unsetCursor()
        self._set_interaction('')
        super().leaveEvent(event)

    def set_playback_clickable(self, enabled):
        if self.hasMouseTracking() != enabled:
            self.setMouseTracking(enabled)
        if bool(self.property('playbackClick')) == enabled:
            return
        self.setProperty('playbackClick', enabled)
        if not enabled:
            self.activate_timer.stop()
            self._press = None
            self._pointer_hit = False
            self.unsetCursor()
            self._set_interaction('')

    def _set_interaction(self, state):
        if self._interaction != state:
            self._interaction = state
            self.interactionChanged.emit(state)

    def _update_pointer(self, point, buttons=Qt.MouseButton.NoButton):
        hit = bool(self.property('playbackClick')) and self._text_contains(point)
        self._pointer_hit = hit
        if hit:
            if self.cursor().shape() != Qt.CursorShape.PointingHandCursor:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        state = ''
        if hit:
            if self._press is not None and not self._press[2]:
                state = 'pressed'
            elif not buttons:
                state = 'pending' if self.activate_timer.isActive() else 'hover'
        self._set_interaction(state)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        self._press = None
        self.activate_timer.stop()
        self._set_interaction('')

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._press is not None and event.button() == Qt.MouseButton.LeftButton:
            position, started, selected = self._press
            if (self.property('playbackClick') and not selected and time.monotonic()-started <= .4
                    and (event.position()-position).manhattanLength() < QApplication.startDragDistance()
                    and self._text_contains(position) and self._text_contains(event.position())):
                self.activate_timer.start()
                self._set_interaction('pending')
            else:
                self._set_interaction('hover' if self._pointer_hit else '')
        self._press = None

    def _activate(self):
        self._set_interaction('hover' if self._pointer_hit else '')
        if self.property('playbackClick') and self.isVisible():
            self.activated.emit()

    def _text_contains(self, point):
        bounds = self.contentsRect().adjusted(self.margin(), self.margin(), -self.margin(), -self.margin())
        key = (self.text(), self.font().key(), bounds.getRect())
        if key == self._hit_key:
            return any(rect.contains(point) for rect in self._hit_rects)
        layout = QTextLayout(self.text().replace('\n', '\u2028'), self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        height, lines = 0., []
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, bounds.width()))
            line.setPosition(QPointF(0, height))
            lines.append(line.naturalTextRect())
            height += line.height()
        layout.endLayout()
        origin = QPointF(bounds.x(), bounds.y()+max(0, (bounds.height()-height)/2))
        self._hit_key = key
        self._hit_rects = tuple(rect.translated(origin) for rect in lines)
        return any(rect.contains(point) for rect in self._hit_rects)

    def hideEvent(self, event):
        self.finish_reveal()
        self.activate_timer.stop()
        self._set_interaction('')
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
        self.direction = 1

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(QApplication.instance().property('appearance'))
        painter.setBrush(QColor(colors['hover'] if self.underMouse() else colors['control']))
        painter.setPen(QPen(QColor(colors['focus'] if self.hasFocus() else colors['border']), 1))
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.setPen(QPen(QColor(colors['text']), 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        def point(x, y):
            return QPointF(x, y if self.direction > 0 else 40-y)
        painter.drawLine(point(20, 12), point(20, 27))
        painter.drawLine(point(14, 21), point(20, 27))
        painter.drawLine(point(20, 27), point(26, 21))


class CaptionEdgeFade(QWidget):
    """Fade captions only where they meet the top toolbar."""
    def __init__(self, viewport):
        super().__init__(viewport)
        self.depth = 22
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        viewport.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.place()
        return False

    def place(self):
        viewport = self.parentWidget()
        self.setGeometry(0, 0, viewport.width(), self.depth)

    def paintEvent(self, event):
        color = QColor(theme_colors(QApplication.instance().property('appearance'))['surface'])
        gradient = QLinearGradient(0, 0, 0, self.height())
        transparent = QColor(color)
        transparent.setAlpha(0)
        gradient.setColorAt(0, color)
        gradient.setColorAt(1, transparent)
        painter = QPainter(self)
        painter.fillRect(self.rect(), gradient)


class CaptionScrollArea(QScrollArea):
    followingChanged = Signal(bool)
    returnRequested = Signal()

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
        self.playback_mode = False
        self.outside_direction = 0
        self.playback_card = None
        self._playback_target = None
        self._playback_offset = None
        self._last_playback_card = None
        self.latest_button = LatestButton(self.viewport())
        self.latest_button.clicked.connect(self.jump_to_latest)
        self.latest_button.hide()
        self.top_fade = CaptionEdgeFade(self.viewport())
        self.top_fade.hide()
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
        bar.valueChanged.connect(lambda value: (self.top_fade.setVisible(value > 0), self.top_fade.raise_()))
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
        visible = not self.following and (not self._at_bottom() or bool(self.outside_direction))
        if self.playback_mode:
            card = self.playback_card
            top = self.verticalScrollBar().value()
            bottom = top+viewport.height()-self._overlay_height-12
            visible = not self.following and card is not None and (card.y() < top or card.y()+min(card.height(), 80) > bottom)
            self.latest_button.direction = -1 if card is not None and card.y() < top else 1
            self.latest_button.setToolTip('返回播放位置（上方）' if self.latest_button.direction < 0 else '返回播放位置（下方）')
        else:
            self.latest_button.direction = 1
        if self.outside_direction:
            visible = True
            self.latest_button.direction = self.outside_direction
            if self.playback_mode:
                self.latest_button.setToolTip('返回播放位置（上方）' if self.outside_direction < 0 else '返回播放位置（下方）')
        self.latest_button.setVisible(visible)
        self.latest_button.update()
        self.latest_button.raise_()

    def set_overlay_height(self, height):
        self._overlay_height = height + 18
        self._update_button()

    def set_outside_target(self, direction):
        self.outside_direction = direction
        self._update_button()

    def discard_card(self, card):
        self._anchor = None
        if card in (self.playback_card, self._last_playback_card):
            self.playback_card = self._last_playback_card = None
            self._playback_target = self._playback_offset = None

    def browse_history(self):
        self._interrupt()

    def resume_latest(self):
        self._set_following(True)

    def _interrupt(self, *args):
        self.animation.stop()
        self._playback_target = None
        self._playback_offset = None
        self._anchor = None
        self._snap_next = False
        self._set_following(False)
        QTimer.singleShot(0, self._sync_position)

    def _sync_position(self):
        # A queued input check must not cancel following already restored by a
        # valueChanged signal, if new content arrived in the meantime.
        if not self.playback_mode and self._anchor is None and not self.following and not self.animation.isActive() and not self.verticalScrollBar().isSliderDown():
            self._set_following(self._at_bottom() and not self.outside_direction)

    def _position_changed(self, value):
        if not self._moving:
            self._playback_offset = None
            self._anchor = None
            self.animation.stop()
            self._set_following(False if self.playback_mode else self._at_bottom() and not self.outside_direction)

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
        if self.playback_mode:
            self._update_button()
            if self.following and self.playback_card is not None:
                self._follow_playback()
            return
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
        target = self._playback_target if self.playback_mode else self.verticalScrollBar().maximum()
        if target is None:
            self.animation.stop()
            return
        target = min(target, self.verticalScrollBar().maximum())
        # Retarget the existing motion; frequent ASR updates never restart it.
        self._position += (target-self._position) * (1-math.exp(-dt/.085))
        if abs(target-self._position) < .8 or not motion_enabled():
            self._position = target
            self.animation.stop()
        self._move(self._position)

    def jump_to_latest(self, checked=False):
        self.returnRequested.emit()
        self._anchor = None
        self._set_following(True)
        self.content_changed()

    def reveal_card(self, card):
        """Locate a search result without resuming live/playback following."""
        self.animation.stop()
        self._set_following(False)
        self._move(max(0, card.y()-24))
        # A newly loaded page may still have the previous page's scroll range.
        # Keep the intended offset so the next layout pass can finish locating it.
        self._anchor = (card, min(24, card.y()))

    def set_playback(self, enabled):
        self.animation.stop()
        self._anchor = None
        self.playback_mode = enabled
        self.playback_card = None
        self._playback_target = None
        self._playback_offset = None
        self._last_playback_card = None
        self.latest_button.setToolTip('返回播放位置' if enabled else '回到最新字幕')
        self.latest_button.setAccessibleName('返回播放位置并恢复跟随' if enabled else '回到最新字幕并恢复自动跟随')
        self._set_following(True)

    def follow_playback(self, card, *, seek=False):
        previous = self._last_playback_card
        if seek:
            self._playback_offset = None
        elif card is not None and previous is not None and card is not previous:
            top = self.verticalScrollBar().value()
            bottom = top+self.viewport().height()-self._overlay_height-12
            if not self.following and top <= previous.y() and previous.y()+min(previous.height(), 80) <= bottom:
                self._playback_offset = previous.y()-top
                self._set_following(True)
            if self.following and self._playback_offset is not None:
                seek = True
        if card is not None:
            self._last_playback_card = card
        self.playback_card = card
        if seek:
            self._set_following(True)
        if self.following and card is not None:
            self._follow_playback(force=seek)
        self._update_button()

    def _follow_playback(self, *, force=False):
        card = self.playback_card
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()-self._overlay_height-12
        if force or card.y() < top+12 or card.y()+min(card.height(), 80) > bottom:
            offset = self._playback_offset if self._playback_offset is not None else min(96, (bottom-top)*.22)
            target = min(self.verticalScrollBar().maximum(), max(0, card.y()-offset))
            if not motion_enabled():
                self.animation.stop()
                self._playback_target = None
                self._move(target)
                return
            # Keep one moving target. Position notifications must not restart
            # the easing each frame, and wheel/trackpad input cancels it at once.
            self._playback_target = target
            if not self.animation.isActive():
                self._position = float(top)
                self._last_tick = time.monotonic()
                self.animation.start()

    def reset_follow(self):
        self.animation.stop()
        self._anchor = None
        self._snap_next = True
        self._set_following(True)
        self.content_changed()
