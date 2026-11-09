"""Bounded transcript presentation and navigation, independent of session orchestration."""
from bisect import bisect_left

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QVBoxLayout, QWidget

from .caption_view import CaptionScrollArea, CaptionText
from .core import Caption
from .qt_controls import text_label as label
from .transcript import Transcript
from .ui_theme import theme_colors
from .workspace_widgets import RecordingHint


class CaptionCard(QFrame):
    def __init__(self, caption, translating, *, animate=False):
        super().__init__()
        self.setObjectName("captionRow")
        self.interaction = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 14, 4, 18)
        layout.setSpacing(9)
        self.meta = label("", "timestamp")
        self.source = CaptionText()
        self.target = CaptionText()
        self.source.interactionChanged.connect(self.set_interaction)
        self.target.interactionChanged.connect(self.set_interaction)
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target.setObjectName("captionTranslation")
        self.pending = label('', 'translationPending')
        layout.addWidget(self.meta)
        layout.addWidget(self.source)
        layout.addWidget(self.target)
        layout.addWidget(self.pending)
        self.translating = translating
        self.update_caption(caption, animate=animate)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.property('playing') or self.interaction:
            colors = theme_colors(QApplication.instance().property('appearance'))
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            if self.property('playing'):
                painter.setBrush(QColor(colors['playback']))
                painter.drawRoundedRect(self.rect().adjusted(0, 2, 0, -2), 9, 9)
            if self.interaction:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(colors['selected']))
                painter.drawRoundedRect(self.rect().adjusted(0, 2, 0, -2), 9, 9)

    def set_interaction(self, state):
        states = (self.source._interaction, self.target._interaction)
        state = next((value for value in ('pressed', 'pending') if value in states), '')
        if self.interaction != state:
            self.interaction = state
            self.update()

    def update_caption(self, caption, *, animate=True):
        self.source.set_caption_text(caption.source, animate=animate)
        source_style = "font-size: 16px;"
        name = "captionFinal" if caption.final else "captionDraft"
        if self.source.objectName() != name:
            self.source.setObjectName(name)
            self.source.style().unpolish(self.source)
            self.source.style().polish(self.source)
        if self.source.styleSheet() != source_style:
            self.source.setStyleSheet(source_style)
        self.meta.setText(f"{int(caption.start) // 60:02}:{int(caption.start) % 60:02}" +
                          (' · 已定稿' if caption.final else ' · 优化中'))
        self.meta.setToolTip('原文已定稿' if caption.final else '原文正在优化，内容可能继续修订')
        self.target.set_caption_text(caption.translation or ("翻译暂不可用" if caption.error else ""),
                                     animate=animate)
        self.target.setToolTip(caption.error or ('初译依据：' + caption.translation_source
                               if caption.translation_phase == 'initial' else ''))
        self.target.setVisible(bool(self.target.text()))
        stale = bool(caption.translation and caption.translation_source
                     and caption.translation_source != caption.source)
        self.pending.setText(('译文更新失败' if caption.error else '原文已更新，正在更新译文…')
                             if stale else '')
        self.pending.setToolTip(caption.error)
        self.pending.setVisible(self.translating and stale)


class CaptionFeed(CaptionScrollArea):
    activated = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = Transcript()
        self.cards = {}
        self.page_start = None
        self.preview = None
        self.preview_card = None
        self.translating = True
        self.recording_active = self.loading = False
        self.playing_id = None
        self.feed = QWidget()
        self.feed.setObjectName('feed')
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(12, 24, 12, 16)
        self.feed_layout.setSpacing(4)
        self.older = QPushButton('查看更早的字幕')
        self.newer = QPushButton('查看较新的字幕')
        self.older.clicked.connect(lambda: self.change_page(-1))
        self.newer.clicked.connect(lambda: self.change_page(1))
        for button in (self.older, self.newer):
            button.setObjectName('quiet')
            button.hide()
            self.feed_layout.addWidget(button)
        self.empty = RecordingHint(self.viewport())
        self.empty.setObjectName('recordingHint')
        self.empty.setText('')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(220)
        self.empty.setStyleSheet('QLabel#recordingHint { font-size: 16px; }')
        self.feed_layout.addStretch()
        self.setWidget(self.feed)
        self.returnRequested.connect(self.return_to_target)

    def set_context(self, *, translating, active, loading):
        self.translating, self.recording_active, self.loading = translating, active, loading

    def set_caption(self, caption):
        self.prepare_update()
        previous = self.rows.get(caption.id)
        if not caption.source:
            self.rows.pop(caption.id, None)
            self.render()
        else:
            self.rows[caption.id] = caption
            if caption.id in self.cards:
                self.cards[caption.id].update_caption(caption, animate=not self.loading)
            if previous is None:
                self.render()
        self.empty.setVisible(not self.rows)
        self.apply_preview()
        self.content_changed()

    def render(self):
        identifiers = self.rows.ordered_ids
        complete = self.loading or self.playback_mode
        if complete:
            self.page_start = None
        if not complete and self.page_start is None and len(self.cards) >= 200 and not self.following and not self.loading:
            self.page_start = min(self.cards)
        start = (max(0, len(identifiers) - 200) if self.page_start is None else
                 min(bisect_left(identifiers, self.page_start), max(0, len(identifiers) - 200)))
        visible = identifiers if complete else identifiers[start:start + 200]
        if self.page_start is not None and visible:
            self.page_start = visible[0]
        for identifier in self.cards.keys() - set(visible):
            card = self.cards.pop(identifier)
            self.discard_card(card)
            card.hide()
            self.feed_layout.removeWidget(card)
            card.deleteLater()
        for offset, identifier in enumerate(visible):
            if identifier in self.cards:
                continue
            card = CaptionCard(self.rows[identifier], self.translating,
                animate=not self.loading and self.page_start is None)
            for text in (card.source, card.target):
                text.set_playback_clickable(self.playback_mode and not self.recording_active)
                text.activated.connect(lambda identifier=identifier, card=card: self.activated.emit(identifier, card))
            card.setProperty('playing', self.playing_id == identifier)
            self.cards[identifier] = card
            self.feed_layout.insertWidget(offset + 1, card)
            card.show()
        self.update_page_controls()
        self.feed_layout.activate()

    def update_page_controls(self):
        identifiers = self.rows.ordered_ids
        first, last = min(self.cards, default=0), max(self.cards, default=0)
        self.older.setVisible(not (self.loading or self.playback_mode) and bool(identifiers and first > identifiers[0]))
        self.newer.setVisible(not (self.loading or self.playback_mode) and bool(identifiers and last < identifiers[-1]))
        target = self.playing_id if self.playback_mode else (identifiers[-1] if identifiers else None)
        self.set_outside_target(-1 if target is not None and target < first else
                               1 if target is not None and target > last else 0)

    def set_playback(self, enabled):
        super().set_playback(enabled)
        if enabled:
            self.render()
            self.verticalScrollBar().setValue(0)

    def ensure_card(self, identifier):
        if identifier in self.rows and identifier not in self.cards:
            identifiers = self.rows.ordered_ids
            self.page_start = identifiers[max(0, bisect_left(identifiers, identifier) - 80)]
            self.render()

    def change_page(self, direction):
        identifiers = self.rows.ordered_ids
        if not identifiers:
            return
        start = bisect_left(identifiers, min(self.cards, default=identifiers[0]))
        start = min(max(0, start + direction * 180), max(0, len(identifiers) - 200))
        self.browse_history()
        self.page_start = identifiers[start]
        self.render()
        self.apply_preview()
        self.reveal_card(self.cards[identifiers[start]])

    def return_to_target(self):
        if self.playback_mode:
            if self.playing_id is not None:
                self.ensure_card(self.playing_id)
                self.follow_playback(self.cards.get(self.playing_id), seek=True)
        else:
            self.page_start = None
            self.resume_latest()
            self.render()
            self.apply_preview()

    def set_preview(self, event):
        self.preview = event
        self.prepare_update()
        caption = Caption(0, event['start'], event['end'], event['source'], event['language'], final=False)
        if self.preview_card is None:
            self.preview_card = CaptionCard(caption, False, animate=False)
            self.feed_layout.insertWidget(self.feed_layout.indexOf(self.newer), self.preview_card)
        else:
            self.preview_card.update_caption(caption, animate=False)
        self.preview_card.setVisible(bool(caption.source))
        self.apply_preview()
        self.empty.setVisible(not caption.source and not event['keep_ids'])
        self.content_changed()

    def apply_preview(self):
        if self.preview is None:
            return
        keep = set(self.preview['keep_ids'])
        for identifier, card in self.cards.items():
            card.setVisible(identifier in keep)
        self.empty.setVisible(not self.preview['source'] and not any(i in keep for i in self.rows))
        if self.preview_card is not None and self.feed_layout.indexOf(self.preview_card) != self.feed_layout.indexOf(self.newer)-1:
            self.feed_layout.removeWidget(self.preview_card)
            self.feed_layout.insertWidget(self.feed_layout.indexOf(self.newer), self.preview_card)

    def clear_preview(self):
        self.preview = None
        if self.preview_card is not None:
            self.preview_card.hide()
        for card in self.cards.values():
            card.source.finish_reveal()
            card.target.finish_reveal()
            card.show()
        self.empty.setVisible(not self.rows)
        self.content_changed()

    def clear(self):
        self.clear_preview()
        if self.preview_card is not None:
            self.feed_layout.removeWidget(self.preview_card)
            self.preview_card.deleteLater()
            self.preview_card = None
        self.playing_id = None
        self.reset_follow()
        for card in self.cards.values():
            card.hide()
            self.feed_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        self.rows.clear()
        self.page_start = None
        self.update_page_controls()
        self.empty.show()
