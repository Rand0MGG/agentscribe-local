"""Resizable, independently owned subtitle window; presentation only."""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .caption_view import CaptionText
from .qt_controls import text_label
from .ui_theme import theme_colors


class SubtitleBackdrop(QFrame):
    """Only the background blends with the desktop; text remains fully opaque."""
    def __init__(self):
        super().__init__()
        self.opacity = 80
        self.setObjectName('subtitleBackdrop')
        self.setStyleSheet('QFrame#subtitleBackdrop { background: transparent; border: none; }')

    def paintEvent(self, event):
        colors = theme_colors(QApplication.instance().property('appearance'))
        color = QColor(colors['surface'])
        color.setAlphaF(self.opacity / 100)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(self.rect()), 18, 18)


class WindowHandle(QWidget):
    """Manual drag/resize also works on frameless windows without system grips."""
    def __init__(self, window, *, resize=False):
        super().__init__(window)
        self.owner = window
        self.resizing = resize
        self.origin = None
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if resize else Qt.CursorShape.SizeAllCursor)
        if resize:
            self.setFixedSize(20, 20)
            self.setToolTip('拖动调整字幕窗口宽高')
            self.setAccessibleName('调整字幕窗口大小')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.globalPosition().toPoint()
            self.initial = self.owner.geometry()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.origin
            if self.resizing:
                self.owner.resize(max(self.owner.minimumWidth(), self.initial.width() + delta.x()),
                                  max(self.owner.minimumHeight(), self.initial.height() + delta.y()))
            else:
                self.owner.move(self.initial.topLeft() + delta)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.origin = None

    def paintEvent(self, event):
        if not self.resizing:
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor(theme_colors(QApplication.instance().property('appearance'))['muted']), 1.4))
        for offset in (5, 10, 15):
            painter.drawLine(19-offset, 18, 18, 19-offset)


class Overlay(QWidget):
    def __init__(self, prefs=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.prefs = prefs
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setWindowTitle('AgentScribe · 悬浮字幕')
        self.setMinimumSize(380, 160)
        self.resize(780, 220)
        if prefs is not None:
            geometry = prefs.value('overlay_geometry')
            if geometry:
                self.restoreGeometry(geometry)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        self.backdrop = SubtitleBackdrop()
        outer.addWidget(self.backdrop)
        layout = QVBoxLayout(self.backdrop)
        layout.setContentsMargins(20, 10, 14, 8)
        self.header = WindowHandle(self)
        top = QHBoxLayout(self.header)
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(text_label('字号', 'eyebrow'))
        self.font_size = QSlider(Qt.Orientation.Horizontal)
        self.font_size.setRange(12, 56)
        self.font_size.setAccessibleName('字幕字号')
        self.font_size.setToolTip('调整原文和译文字号')
        self.font_size.setMinimumWidth(40)
        try:
            size = int(prefs.value('overlay_font_size', 23)) if prefs is not None else 23
        except (ValueError, TypeError):
            size = 23
        self.font_size.setValue(size)
        top.addWidget(self.font_size, 1)
        self.font_value = text_label('', 'timestamp')
        self.font_value.setFixedWidth(26)
        top.addWidget(self.font_value)
        top.addWidget(text_label('背景', 'eyebrow'))
        self.background_opacity = QSlider(Qt.Orientation.Horizontal)
        self.background_opacity.setRange(0, 100)
        self.background_opacity.setMinimumWidth(40)
        self.background_opacity.setAccessibleName('字幕背景不透明度')
        self.background_opacity.setToolTip('0% 完全透明，100% 不透明；文字亮度不变')
        try:
            opacity = int(prefs.value('overlay_background_opacity', 80)) if prefs is not None else 80
        except (ValueError, TypeError):
            opacity = 80
        self.background_opacity.setValue(opacity)
        top.addWidget(self.background_opacity, 1)
        self.opacity_value = text_label('', 'timestamp')
        self.opacity_value.setFixedWidth(34)
        top.addWidget(self.opacity_value)
        close = QPushButton('×')
        close.setObjectName('quiet')
        close.setFixedSize(32, 32)
        close.setAccessibleName('关闭悬浮字幕')
        close.clicked.connect(self.hide)
        top.addWidget(close)
        layout.addWidget(self.header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        words = QVBoxLayout(content)
        words.setContentsMargins(0, 4, 6, 0)
        self.source = CaptionText()
        self.source.setText('等待语音…')
        self.source.setObjectName('captionDraft')
        self.target = CaptionText()
        self.target.setObjectName('captionTranslation')
        for widget in (self.source, self.target):
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            words.addWidget(widget)
        words.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.resize_handle = WindowHandle(self, resize=True)
        layout.addWidget(self.resize_handle, 0, Qt.AlignmentFlag.AlignRight)
        self.font_size.valueChanged.connect(self.set_font_size)
        self.background_opacity.valueChanged.connect(self.set_background_opacity)
        self.set_font_size(self.font_size.value())
        self.set_background_opacity(self.background_opacity.value())
        self.hide_controls = QTimer(self)
        self.hide_controls.setSingleShot(True)
        self.hide_controls.setInterval(400)
        self.hide_controls.timeout.connect(lambda: self.set_controls_visible(False))
        for control in (self.header, self.resize_handle):
            policy = control.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            control.setSizePolicy(policy)
        self.set_controls_visible(False)

    def set_font_size(self, size):
        self.font_value.setText(str(size))
        for label in (self.source, self.target):
            label.setStyleSheet(f'font-size: {size}px; font-weight: 400;')
        if self.prefs is not None:
            self.prefs.setValue('overlay_font_size', size)

    def set_background_opacity(self, opacity):
        self.opacity_value.setText(str(opacity) + '%')
        self.backdrop.opacity = opacity
        self.backdrop.update()
        if self.prefs is not None:
            self.prefs.setValue('overlay_background_opacity', opacity)

    def set_controls_visible(self, visible):
        self.header.setVisible(visible)
        self.resize_handle.setVisible(visible)

    def enterEvent(self, event):
        self.hide_controls.stop()
        self.set_controls_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hide_controls.start()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.hide_controls.stop()
        self.set_controls_visible(False)
        if self.prefs is not None:
            self.prefs.setValue('overlay_geometry', self.saveGeometry())
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # A Tool stays above application windows and does not add a second taskbar entry.
        self.raise_()

    def update_caption(self, caption, translating=True, *, animate=True):
        animate = animate and self.isVisible()
        self.source.set_caption_text(caption.source, animate=animate)
        self.source.setObjectName('captionFinal' if caption.final else 'captionDraft')
        self.source.style().unpolish(self.source)
        self.source.style().polish(self.source)
        stale = caption.translation_source and caption.translation_source != caption.source
        prefix = '译文更新失败 · ' if stale and caption.error else ('正在更新译文 · ' if stale else
                  ('初译 · ' if caption.translation_phase == 'initial' else ''))
        self.target.set_caption_text(prefix + caption.translation if translating and caption.translation else '',
                                     animate=animate)
        self.target.setVisible(bool(self.target.text()))
