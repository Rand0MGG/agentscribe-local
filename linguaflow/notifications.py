"""One quiet feedback overlay; never reserve space in the workspace layout."""
import time
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy


@dataclass
class Notice:
    text: str
    kind: str = 'info'
    action: object = None
    action_text: str = ''
    progress: float | None = None
    details: str = ''
    expires: float = 0.


class FeedbackLabel(QLabel):
    """Compatibility for existing status callers; the label itself stays hidden."""
    def __init__(self, center, parent=None):
        super().__init__(parent)
        self.center = center
        self.hide()

    def setText(self, text):
        if text == self.text():
            return
        super().setText(text)
        if text:
            self.center.post('status', text)

    def setVisible(self, visible):
        super().setVisible(False)

    def set_state_text(self, text):
        super().setText(text)


class NotificationCenter(QFrame):
    """Quiet, non-modal notices with retained task state and a short display time.

    Percentage updates do not extend the popup lifetime or reopen it. Errors
    retain retry actions until cleared, without permanently covering UI.
    """
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName('feedbackPopup')
        # A rounded frameless window needs an alpha surface as well as QSS;
        # otherwise its unpainted corners become an opaque native rectangle.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.anchor = None
        self.owner = None
        if parent:
            parent.installEventFilter(self)
        self.notices = {}
        self.suppressed = set()
        self.current_key = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.surface = QFrame()
        self.surface.setObjectName('feedbackToast')
        self.surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        outer.addWidget(self.surface)
        layout = QHBoxLayout(self.surface)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(8)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.message.setObjectName('feedbackText')
        self.message.setAccessibleName('操作反馈')
        layout.addWidget(self.message, 1)
        self.progress = QProgressBar()
        self.progress.setFixedSize(64, 4)
        self.progress.setObjectName('downloadProgress')
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.action_button = QPushButton()
        self.action_button.setObjectName('quiet')
        self.action_button.clicked.connect(self._act)
        layout.addWidget(self.action_button)
        self.dismiss = QPushButton('×')
        self.dismiss.setObjectName('quiet')
        self.dismiss.setFixedWidth(28)
        self.dismiss.setAccessibleName('收起当前通知')
        self.dismiss.clicked.connect(self._dismiss)
        layout.addWidget(self.dismiss)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._refresh)
        self.timer.start()
        self._refresh()

    def post(self, key, text, *, kind='info', action=None, action_text='', progress=None, details=''):
        previous = self.notices.get(key)
        # Only the owning operation can explicitly clear its unresolved error.
        # A generic status/attention message is not evidence that it succeeded.
        if key == 'operation' and previous and previous.kind == 'error' and kind != 'error':
            return
        if previous and (previous.text, previous.kind, previous.progress, previous.details,
                         previous.action_text, previous.action is not None) == (
                         text, kind, progress, details, action_text, action is not None):
            # Periodic state refreshes must not perpetually extend a success.
            previous.action = action
            return
        # Stage and percentage changes preserve dismissal for the entire task.
        # Preparation remains visible until dismissed or completed.
        expires = (previous.expires if previous and previous.kind == kind == 'progress'
                   else float('inf') if (key in ('preparation', 'update') and kind == 'progress')
                   or (key == 'update' and (kind == 'error' or kind == 'attention' and action is not None))
                   else time.monotonic() + (8 if kind == 'error' else 5))
        self.notices.pop(key, None)
        self.notices[key] = Notice(text, kind, action, action_text, progress, details,
                                  expires)
        self._refresh()

    def clear(self, key):
        self.notices.pop(key, None)
        self._refresh()

    def set_suppressed(self, key, suppressed):
        if suppressed:
            self.suppressed.add(key)
        else:
            self.suppressed.discard(key)
        self._refresh()

    def _refresh(self):
        now = time.monotonic()
        self.notices = {key: value for key, value in self.notices.items()
                        if value.kind not in ('info', 'success') or value.expires > now}
        visible = [key for key in reversed(self.notices)
                   if key not in self.suppressed and self.notices[key].expires > now]
        # Reverse insertion order gives equal-priority notices the latest task,
        # including across info/success/attention kinds.
        if visible:
            key = max(visible, key=lambda key: (self.notices[key].kind == 'error',
                      self.notices[key].kind == 'progress'))
            notice = self.notices[key]
            self.current_key = key
            text = notice.text
            if notice.kind == 'progress' and notice.progress is not None:
                text += f'  {notice.progress:.0f}%'
            self.message.setToolTip(notice.text)
            self.message.setText(text)
            self.message.setProperty('error', notice.kind == 'error')
            self.message.style().unpolish(self.message)
            self.message.style().polish(self.message)
            self.action_button.setText(notice.action_text)
            self.action_button.setVisible(notice.action is not None)
            self.progress.setVisible(notice.kind == 'progress')
            self.dismiss.setVisible(True)
            if notice.progress is None:
                self.progress.setRange(0, 0)
            else:
                self.progress.setRange(0, 100)
                self.progress.setValue(round(notice.progress))
        else:
            self.current_key = None
            self.message.clear()
            for widget in (self.progress, self.action_button, self.dismiss):
                widget.hide()
        if visible:
            self.place()
        else:
            self.hide()

    def set_anchor(self, anchor):
        self.anchor = anchor
        anchor.installEventFilter(self)
        self.place()

    def place(self):
        parent = self.parentWidget()
        if parent is None:
            return
        area = self.anchor or parent
        if area is not parent and not parent.isAncestorOf(area):
            return  # Assembly has not attached the reading surface yet.
        owner = parent.window()
        if self.owner is not owner:
            self.owner = owner
            owner.installEventFilter(self)
        if (not self.current_key or self.notices[self.current_key].expires <= time.monotonic()
                or not owner.isVisible() or owner.isMinimized()):
            self.hide()
            return
        origin = area.mapToGlobal(area.rect().topLeft())
        self.ensurePolished()
        controls = [widget for widget in (self.progress, self.action_button, self.dismiss) if not widget.isHidden()]
        reserved = 20 + sum(widget.width() if widget.minimumWidth() == widget.maximumWidth()
                            else widget.sizeHint().width() for widget in controls) + 8*len(controls)
        metrics = self.message.fontMetrics()
        # Reserve the widest percentage, so 9% -> 100% cannot jiggle the popup.
        notice = self.notices[self.current_key]
        measure = notice.text + ('  100%' if notice.kind == 'progress' else '')
        natural = max(metrics.horizontalAdvance(line) for line in measure.splitlines() or [''])
        width = min(max(180, reserved+natural), 480, max(180, area.width()-32))
        text_width = max(1, width-reserved)
        self.message.setFixedWidth(text_width)
        text_height = metrics.boundingRect(QRect(0, 0, text_width, 10000),
            int(Qt.TextFlag.TextWordWrap), self.message.text()).height()
        height = max(44, min(text_height+16, max(44, owner.height()//2)))
        self.setFixedSize(width, height)
        self.move(origin.x()+area.width()-width-16, origin.y()+16)
        self.show()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            QTimer.singleShot(0, self.place)
        elif watched is self.owner and event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.hide()
        return False

    def _act(self):
        notice = self.notices.get(self.current_key)
        if notice and notice.action:
            notice.action()

    def _dismiss(self):
        notice = self.notices.get(self.current_key)
        if notice:
            notice.expires = time.monotonic()
        self._refresh()
