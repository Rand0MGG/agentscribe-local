import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .audio import list_devices
from .caption_view import CaptionScrollArea
from .core import LANGUAGES, export_srt, translation_status
from .deleted_dialog import DeletedDialog
from .library import Library
from .library_access import acquire_recording_lock, check_library_access
from .library_startup import LibrarySelectionCancelled, open_library
from .management import ModelManager
from .preferences import PREFERENCES, read_audio_device, read_preferences, write_preferences
from .qt_controls import data_index
from .qt_controls import text_label as label
from .recording_state import RecordingState
from .settings_binding import SettingsBinding
from .ui_components import ActionMenu, Disclosure, NameDialog
from .ui_components import ChoiceBox as QComboBox
from .ui_theme import PLATFORM_STYLE, SURFACE_STYLE
from .wlk_session import Session
from .workspace_widgets import LibraryTree, RecordingDialog, SettingsWorkspace, Switch

STYLE = """
QWidget { background: transparent; color: #f1f1f1; font-family: 'Microsoft YaHei UI', 'PingFang SC', sans-serif; font-size: 13px; }
QMainWindow, QWidget#appRoot { background: transparent; }
QLabel { background: transparent; }
QLabel#title { font-size: 23px; font-weight: 700; letter-spacing: 0.3px; }
QLabel#brand { font-size: 19px; font-weight: 700; letter-spacing: -0.2px; }
QLabel#muted { color: #a8a8a8; }
QLabel#section { color: #a6a6a6; font-size: 11px; font-weight: 700; letter-spacing: 1.1px; }
QLabel#eyebrow { color: #b8b8b8; font-size: 11px; font-weight: 700; letter-spacing: 0.6px; }
QLabel#pill { color: #d8d8d8; background: rgba(74, 74, 74, 120); border: 1px solid rgba(145, 145, 145, 90); border-radius: 9px; padding: 5px 9px; font-size: 11px; font-weight: 700; }
QFrame#glassTopBar, QFrame#sidebar { background: rgba(28, 28, 28, 195); border: none; }
QFrame#sidebar { border-right: 1px solid rgba(125, 125, 125, 80); }
QFrame#workspace { background: transparent; border: none; }
QFrame#workspaceHeader { background: #171717; border: none; border-bottom: 1px solid #343434; border-top-left-radius: 13px; }
QWidget#workspaceContent { background: #171717; }
QFrame#footer { background: #252525; border: 1px solid #454545; border-radius: 12px; }
QWidget#settingsPanel { background: transparent; }
QWidget#feed { background: transparent; }
QWidget#overlay { background: rgba(20, 20, 20, 235); }
QFrame#panel { background: #292929; border: 1px solid #454545; border-radius: 10px; }
QFrame#panel:hover { background: #2d2d2d; border-color: #565656; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #2d2d2d; border: 1px solid #4d4d4d;
    padding: 8px 10px; border-radius: 7px; min-height: 18px; selection-background-color: #494949; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { background: #323232; border-color: #626262; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #888888; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #292929; color: #f1f1f1; border: 1px solid #515151; outline: none; selection-background-color: #454545; }
QPushButton { background: #2d2d2d; border: 1px solid #484848; border-radius: 7px; padding: 8px 13px; color: #ededed; }
QPushButton:hover { background: #383838; border-color: #626262; }
QPushButton:focus { border-color: #787878; }
QPushButton:pressed { background: #242424; border-color: #505050; }
QPushButton:checked { background: #404040; border-color: #6a6a6a; color: #ffffff; }
QPushButton:checked:hover { background: #464646; }
QPushButton#primary { background: #eeeeee; color: #171717; font-weight: 700; border: 1px solid #ffffff; padding: 10px 22px; }
QPushButton#primary:hover { background: #ffffff; border-color: #ffffff; }
QPushButton#primary:pressed { background: #d2d2d2; border-color: #d2d2d2; }
QPushButton#secondary { background: #323232; color: #f0f0f0; border-color: #535353; }
QPushButton#secondary:hover { background: #3d3d3d; border-color: #696969; }
QPushButton:disabled { color: #707070; background: #232323; border-color: #333333; }
QPushButton#windowControl { background: transparent; border: none; border-radius: 0; padding: 0; min-width: 46px; min-height: 44px; font-size: 16px; }
QPushButton#windowControl:hover { background: rgba(255, 255, 255, 24); }
QPushButton#windowControl:pressed { background: rgba(255, 255, 255, 14); }
QPushButton#windowClose { background: transparent; border: none; border-radius: 0; padding: 0; min-width: 48px; min-height: 44px; font-size: 18px; }
QPushButton#windowClose:hover { background: #c42b1c; color: #ffffff; }
QPushButton#windowClose:pressed { background: #a52117; }
QProgressBar { background: #2d2d2d; border: none; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #d8d8d8; border-radius: 3px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 3px; }
QScrollBar::handle:vertical { background: #454545; min-height: 30px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #626262; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QSplitter::handle { background: rgba(110, 110, 110, 55); width: 1px; }
QSplitter::handle:hover { background: rgba(160, 160, 160, 100); }
QCheckBox { spacing: 8px; padding: 4px 0; }
QCheckBox:hover { color: #ffffff; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #626262; border-radius: 4px; background: #292929; }
QCheckBox::indicator:hover { border-color: #8a8a8a; background: #333333; }
QCheckBox::indicator:checked { background: #e3e3e3; border-color: #f2f2f2; }
QPlainTextEdit { background: #1c1c1c; border: 1px solid #404040; border-radius: 7px; padding: 8px; selection-background-color: #4a4a4a; }
QTabWidget::pane { border: 1px solid #404040; border-radius: 8px; top: -1px; }
QTabBar::tab { background: #252525; color: #aaaaaa; border: 1px solid transparent; border-bottom: none; border-radius: 7px 7px 0 0; padding: 9px 12px; margin-right: 3px; }
QTabBar::tab:selected { background: #393939; color: #f2f2f2; border-color: #555555; }
QTabBar::tab:hover:!selected { background: #303030; color: #e4e4e4; }
QDialog { background: #1d1d1d; }
QDialog QWidget { background-color: transparent; }
QDialog QComboBox, QDialog QSpinBox, QDialog QDoubleSpinBox { background: #2d2d2d; }
QDialog QPushButton { background: #2d2d2d; }
QDialog QPushButton:hover { background: #383838; }
QDialog QPlainTextEdit { background: #1c1c1c; }
QToolTip { background: #303030; color: #f5f5f5; border: 1px solid #707070; padding: 5px; }
"""


STYLE += """
QWidget { font-family: 'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC'; font-size: 13px; color: #e4e4e7; }
QLabel#brand { font-size: 19px; font-weight: 600; }
QLabel#title { font-size: 21px; font-weight: 600; }
QLabel#section { color: #838389; font-size: 12px; font-weight: 500; letter-spacing: 0; }
QLabel#timestamp { color: #77777e; font-size: 11px; }
QFrame#glassTopBar, QFrame#sidebar { background: rgba(25, 25, 27, 105); border: none; }
QFrame#workspaceHeader { background: transparent; border: none; border-bottom: 1px solid #303032; }
QSplitter::handle { background: transparent; }
QTreeWidget::branch:selected { background: transparent; }
QWidget#workspaceContent { background: #191919; }
QFrame#captionRow { background: transparent; border: none; }
QFrame#footer { background: #242425; border: 1px solid #353537; border-radius: 18px; }
QPushButton { background: #2a2a2c; border: 1px solid #3b3b3e; border-radius: 8px; padding: 8px 12px; }
QPushButton#quiet, QPushButton#navigation { background: transparent; border: 1px solid transparent; font-weight: 400; }
QPushButton#navigation { text-align: left; padding: 10px 8px; }
QPushButton#quiet:hover, QPushButton#navigation:hover { background: rgba(255,255,255,14); }
QPushButton#quiet { padding: 6px; }
QPushButton#quiet::menu-indicator { image: none; width: 0; }
QPushButton#primary { background: #e9e9eb; color: #1c1c1e; border: none; border-radius: 12px; font-weight: 600; padding: 10px 18px; }
QTreeWidget { background: transparent; border: none; outline: none; color: #c8c8cd; }
QTreeWidget::item { height: 36px; padding: 0 5px; border: none; border-radius: 7px; }
QTreeWidget::item:selected { background: rgba(255,255,255,22); color: #f4f4f5; }
QTreeWidget::item:hover:!selected { background: rgba(255,255,255,10); }
QTreeWidget::branch { background: transparent; }
QMenu { background: #262628; border: 1px solid #404044; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 9px 24px; border-radius: 5px; }
QMenu::item:selected { background: #3a3a3d; }
QLineEdit { background: #29292c; border: 1px solid #444448; border-radius: 6px; padding: 9px; }
QFrame#overlayShell { background: rgba(25,25,28,242); border: 1px solid rgba(180,180,190,40); border-radius: 18px; }
QSlider::groove:horizontal { background: #38383c; height: 3px; border-radius: 1px; }
QSlider::sub-page:horizontal { background: #a9a9af; }
QSlider::handle:horizontal { background: #e1e1e4; width: 10px; margin: -4px 0; border-radius: 5px; }
QProgressBar { background: transparent; }
QProgressBar::chunk { background: #74777b; }
QLabel#settingsTitle { font-size: 27px; font-weight: 600; color: #e8e8eb; }
QLabel#settingsSection { font-size: 15px; font-weight: 600; color: #d5d5d9; }
QLabel#settingsLabel { font-size: 14px; font-weight: 600; }
QFrame#settingsGroup { background: #242425; border: 1px solid #333335; border-radius: 15px; }
QWidget#modelSettingsGroup { background: #242425; border: 1px solid #333335; border-radius: 15px; }
QFrame#settingsRow { border: none; border-bottom: 1px solid #343436; }
QListWidget#settingsNavigation { background: transparent; border: none; outline: none; }
QListWidget#settingsNavigation::item { padding: 12px 14px; border-radius: 8px; margin-bottom: 3px; }
QListWidget#settingsNavigation::item:selected { background: #353033; color: #f3f3f5; }
QListWidget#settingsNavigation::item:hover:!selected { background: rgba(255,255,255,10); }
"""
STYLE += SURFACE_STYLE + PLATFORM_STYLE


def enable_system_backdrop(window):
    """Enable wallpaper-only Mica behind the connected top and sidebar glass."""
    if sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class Margins(ctypes.Structure):
            _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                        ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

        hwnd = wintypes.HWND(int(window.winId()))
        dwmapi = ctypes.windll.dwmapi
        enabled = ctypes.c_int(1)
        rounded = ctypes.c_int(2)
        backdrop = ctypes.c_int(2)  # DWMSBT_MAINWINDOW / Mica samples the wallpaper only.
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
        dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), ctypes.sizeof(rounded))
        modern_result = dwmapi.DwmSetWindowAttribute(
            hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop)
        )
        # Windows 11 21H2 exposed Mica through this earlier attribute before
        # DWMWA_SYSTEMBACKDROP_TYPE became available.
        legacy_result = dwmapi.DwmSetWindowAttribute(
            hwnd, 1029, ctypes.byref(enabled), ctypes.sizeof(enabled)
        )
        margins = Margins(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        return modern_result == 0 or legacy_result == 0
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return False


def desktop_wallpaper_path():
    if sys.platform != "win32":
        return ""
    try:
        import ctypes

        path = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.user32.SystemParametersInfoW(0x0073, len(path), path, 0):
            return path.value
    except (AttributeError, OSError, ValueError):
        pass
    return ""


class WallpaperBackdrop(QWidget):
    """Paint a blurred, screen-aligned wallpaper beneath the L-shaped glass."""

    def __init__(self):
        super().__init__()
        self.setObjectName("appRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._wallpaper_path = ""
        self._wallpaper_stamp = 0
        self._source = QPixmap()
        self._blurred = QPixmap()
        self._blurred_size = None
        self.refresh_wallpaper()
        self.wallpaper_timer = QTimer(self)
        self.wallpaper_timer.timeout.connect(self.refresh_wallpaper)
        self.wallpaper_timer.start(30000)

    def refresh_wallpaper(self):
        path = desktop_wallpaper_path()
        try:
            stamp = Path(path).stat().st_mtime_ns if path else 0
        except OSError:
            stamp = 0
        if path == self._wallpaper_path and stamp == self._wallpaper_stamp:
            return
        wallpaper = QPixmap(path) if path else QPixmap()
        if wallpaper.isNull():
            return
        self._wallpaper_path = path
        self._wallpaper_stamp = stamp
        self._source = wallpaper
        self._blurred = QPixmap()
        self._blurred_size = None
        self.update()

    def _build_blurred_wallpaper(self, size):
        if self._source.isNull() or size.isEmpty():
            return
        scaled = self._source.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = max(0, (scaled.width() - size.width()) // 2)
        top = max(0, (scaled.height() - size.height()) // 2)
        cropped = scaled.copy(left, top, size.width(), size.height())
        small = cropped.scaled(
            max(1, size.width() // 64),
            max(1, size.height() // 64),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._blurred = small.scaled(
            size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._blurred_size = size

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(30, 30, 30))
        screen = self.window().screen() or QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            if self._blurred_size != geometry.size():
                self._build_blurred_wallpaper(geometry.size())
            if not self._blurred.isNull():
                origin = self.mapToGlobal(QPoint(0, 0))
                source = QRect(
                    origin.x() - geometry.x(),
                    origin.y() - geometry.y(),
                    self.width(),
                    self.height(),
                )
                painter.setOpacity(0.30)
                painter.drawPixmap(self.rect(), self._blurred, source)
                painter.setOpacity(1.0)
        painter.fillRect(self.rect(), QColor(25, 25, 27, 125))
        painter.end()


def panel(title, subtitle=None):
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(9)
    layout.addWidget(label(title, "section"))
    if subtitle:
        layout.addWidget(label(subtitle, "muted"))
    return frame, layout


class GlassTitleBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.host = window
        self.setObjectName("glassTopBar")
        self.setFixedHeight(44)
        bar = QHBoxLayout(self)
        bar.setContentsMargins(13, 0, 0, 0)
        bar.setSpacing(8)
        bar.addWidget(label("▣", "muted"))
        title = label("AgentScribe · 本地同声字幕")
        title.setWordWrap(False)
        bar.addWidget(title)
        bar.addStretch()
        minimize = QPushButton("—")
        minimize.setObjectName("windowControl")
        minimize.setToolTip("最小化")
        minimize.clicked.connect(window.showMinimized)
        self.maximize = QPushButton("□")
        self.maximize.setObjectName("windowControl")
        self.maximize.setToolTip("最大化")
        self.maximize.clicked.connect(self.toggle_maximized)
        close = QPushButton("×")
        close.setObjectName("windowClose")
        close.setToolTip("关闭")
        close.clicked.connect(window.close)
        bar.addWidget(minimize)
        bar.addWidget(self.maximize)
        bar.addWidget(close)

    def toggle_maximized(self):
        if self.host.isMaximized():
            self.host.showNormal()
            self.maximize.setText("□")
            self.maximize.setToolTip("最大化")
        else:
            self.host.showMaximized()
            self.maximize.setText("❐")
            self.maximize.setToolTip("还原")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.host.windowHandle():
            self.host.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class WorkspaceFrame(QFrame):
    """One continuous antialiased edge around the top-left content corner."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = 18.0
        path = QPainterPath()
        path.moveTo(self.width(), 0.5)
        path.lineTo(radius, 0.5)
        path.quadTo(0.5, 0.5, 0.5, radius)
        path.lineTo(0.5, self.height())
        path.lineTo(self.width(), self.height())
        path.closeSubpath()
        painter.fillPath(path, QColor("#191919"))
        edge = QPainterPath()
        edge.moveTo(self.width(), 0.5)
        edge.lineTo(radius, 0.5)
        edge.quadTo(0.5, 0.5, 0.5, radius)
        edge.lineTo(0.5, self.height())
        painter.setPen(QPen(QColor("#343436"), 1))
        painter.drawPath(edge)


def line_icon(kind, color="#bdbdbf"):
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.45))
    if kind == "folder":
        path = QPainterPath()
        path.moveTo(3, 6)
        path.lineTo(3, 4)
        path.lineTo(8, 4)
        path.lineTo(10, 6)
        path.lineTo(17, 6)
        path.lineTo(17, 16)
        path.lineTo(3, 16)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(3, 8, 17, 8)
    elif kind == "new":
        painter.drawRoundedRect(3, 3, 14, 14, 3, 3)
        painter.drawLine(6, 10, 14, 10)
        painter.drawLine(10, 6, 10, 14)
    elif kind == "settings":
        for y, x in [(5, 7), (10, 13), (15, 8)]:
            painter.drawLine(3, y, 17, y)
            painter.setBrush(QColor("#252527"))
            painter.drawEllipse(QPoint(x, y), 2, 2)
    else:
        painter.drawRoundedRect(5, 3, 10, 14, 2, 2)
        painter.drawLine(8, 7, 12, 7)
        painter.drawLine(8, 10, 12, 10)
    painter.end()
    return QIcon(pixmap)


class Overlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("AgentScribe · 悬浮字幕")
        self.resize(780, 180)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        shell = QFrame()
        shell.setObjectName("overlayShell")
        outer.addWidget(shell)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(28, 12, 24, 24)
        top = QHBoxLayout()
        top.addWidget(label("实时字幕", "eyebrow"))
        top.addStretch()
        close = QPushButton("×")
        close.setObjectName("quiet")
        close.setFixedSize(28, 26)
        close.clicked.connect(self.hide)
        top.addWidget(close)
        layout.addLayout(top)
        self.source = label("等待语音…")
        self.source.setStyleSheet("font-size: 19px; color: #e5e5e7;")
        self.target = label("")
        self.target.setStyleSheet("font-size: 23px; color: #fafafa; font-weight: 500;")
        layout.addWidget(self.source)
        layout.addWidget(self.target)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()

    def update_caption(self, caption, translating=True):
        self.source.setText(caption.source)
        self.source.setStyleSheet("font-size: 19px; color: " +
                                 ("#e5e5e7;" if caption.final else "#a8a8ae;"))
        prefix = '初译 · ' if caption.translation_phase == 'initial' else ''
        self.target.setText(prefix + caption.translation if translating and caption.translation else "")
        self.target.setVisible(bool(self.target.text()))
        self.adjustSize()


class CaptionCard(QFrame):
    def __init__(self, caption, translating):
        super().__init__()
        self.setObjectName("captionRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 14, 4, 18)
        layout.setSpacing(9)
        self.meta = label("", "timestamp")
        self.source = label("")
        self.target = label("")
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target.setStyleSheet("font-size: 15px; color: #bababe;")
        layout.addWidget(self.meta)
        layout.addWidget(self.source)
        layout.addWidget(self.target)
        self.translating = translating
        self.update_caption(caption)

    def update_caption(self, caption):
        if self.source.text() != caption.source:
            self.source.setText(caption.source)
        source_style = "font-size: 16px; color: " + ("#efeff1;" if caption.final else "#98989f;")
        if self.source.styleSheet() != source_style:
            self.source.setStyleSheet(source_style)
        self.meta.setText(f"{int(caption.start) // 60:02}:{int(caption.start) % 60:02}" +
                          (' · 原文已定稿' if caption.final else (' · 已提交，可修订' if caption.ready else ' · 识别中')) +
                          (' · ' + translation_status(caption) if self.translating else ''))
        self.meta.setToolTip(translation_status(caption) if self.translating else '识别独立决定提交与定稿')
        self.target.setText(caption.translation or ("翻译暂不可用" if caption.error else ""))
        self.target.setToolTip(caption.error or ('初译依据：' + caption.translation_source
                               if caption.translation_phase == 'initial' else ''))
        self.target.setVisible(bool(self.target.text()))


class Window(QMainWindow):
    def __init__(self, discover=True, library_root=None, prefs=None, library=None):
        super().__init__()
        self._backdrop_applied = False
        self._backdrop_attempted = False
        if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("AgentScribe · 本地同声字幕")
        self.resize(1280, 840)
        self.setMinimumSize(900, 650)
        self.session = None
        self.recording_lock = None
        self.last_error = ""
        self.recording_state = RecordingState.IDLE
        self.phase_started = time.monotonic()
        self.pipeline_state = {"音频": "未开始", "识别": "未加载", "翻译": "未加载"}
        self.captions = {}
        self.cards = {}
        self.closing = False
        self.overlay = Overlay()
        self.prefs = prefs if prefs is not None else QSettings("LinguaFlow", "LocalCaptions")
        self.library = library if library is not None else self.open_recording_library(library_root)
        self.session_dirty = False
        self.current_item = None
        self.folder_id = self.library.index["folders"][0]["id"]
        self.loading_saved = False
        self.caption_translation = True
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.timeout.connect(self.persist_session)
        root = WallpaperBackdrop()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.title_bar = GlassTitleBar(self)
        self.title_bar.setVisible(sys.platform == "win32")
        layout.addWidget(self.title_bar)
        split = QSplitter()
        split.setHandleWidth(1)
        self.pages = QStackedWidget()
        self.pages.addWidget(split)
        layout.addWidget(self.pages, 1)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(420)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 20, 14, 14)
        sidebar_layout.setSpacing(10)
        sidebar_header = QHBoxLayout()
        sidebar_header.addWidget(label("AgentScribe", "brand"))
        sidebar_header.addStretch()

        sidebar_layout.addLayout(sidebar_header)
        sidebar_layout.addSpacing(20)
        self.new_button = QPushButton("  新录音")
        self.new_button.setIcon(line_icon("new"))
        self.new_button.setObjectName("navigation")
        self.new_button.clicked.connect(self.new_recording)
        sidebar_layout.addWidget(self.new_button)
        sidebar_layout.addSpacing(22)
        folders_heading = QHBoxLayout()
        folders_heading.addWidget(label("文件夹", "section"))
        folders_heading.addStretch()
        self.folder_button = QPushButton("＋")
        self.folder_button.setToolTip("新建文件夹")
        self.folder_button.setObjectName("quiet")
        self.folder_button.setFixedSize(28, 28)
        self.folder_button.clicked.connect(self.create_folder)
        folders_heading.addWidget(self.folder_button)
        sidebar_layout.addLayout(folders_heading)
        self.library_tree = LibraryTree()
        self.library_tree.setHeaderHidden(True)
        self.library_tree.setRootIsDecorated(False)
        self.library_tree.setIndentation(0)
        self.library_tree.setIconSize(QSize(18, 18))
        self.library_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library_tree.itemClicked.connect(self.open_library_item)
        self.library_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library_tree.customContextMenuRequested.connect(self.library_menu)
        self.library_tree.newRequested.connect(lambda folder: self.new_recording(folder_id=folder))
        self.library_tree.menuRequested.connect(self.show_library_menu)
        sidebar_layout.addWidget(self.library_tree, 1)
        settings_button = QPushButton("  设置")
        settings_button.setObjectName("navigation")
        settings_button.setIcon(line_icon("settings"))
        settings_button.clicked.connect(self.open_settings)
        deleted_button = QPushButton("最近删除")
        deleted_button.setObjectName("navigation")
        deleted_button.clicked.connect(self.show_deleted)
        sidebar_layout.addWidget(deleted_button)
        guide_button = QPushButton('使用指南')
        guide_button.setObjectName('navigation')
        guide_button.clicked.connect(lambda: self.open_settings('使用指南'))
        sidebar_layout.addWidget(guide_button)
        sidebar_layout.addWidget(settings_button)
        sidebar_layout.addWidget(label("  本地工作空间", "timestamp"))
        self.settings_panel = QWidget()
        self.settings_panel.setObjectName("settingsPanel")
        form_outer = QVBoxLayout(self.settings_panel)
        form_outer.setContentsMargins(0, 8, 4, 0)
        form_outer.addWidget(label("聆听设置", "section"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setSpacing(10)
        self.device = QComboBox()
        self.device.setMinimumWidth(270)
        self.device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device.setMinimumContentsLength(20)
        form.addRow("音频来源", self.device)
        refresh = QPushButton("刷新设备")
        refresh.clicked.connect(self.refresh_devices)
        form.addRow(refresh)
        hint = "Windows：选择“系统声音”录制电脑播放内容。"
        if sys.platform == "darwin":
            hint = "Mac：系统声音请选择 BlackHole 输入，并在音频 MIDI 设置中配置多输出设备。"
        form.addRow(label(hint, "muted"))
        self.source = QComboBox()
        self.source.addItem("自动检测", (None, None))
        self.target = QComboBox()
        for name, whisper, nllb in LANGUAGES:
            self.source.addItem(name, (whisper, nllb))
            self.target.addItem(name, nllb)
        form.addRow("原文语言", self.source)
        form.addRow("翻译为", self.target)
        form_outer.addLayout(form)
        self.model_manager = ModelManager(self, compute_device=lambda: self.compute.currentData())
        models = self.model_manager.whisper_form
        self.asr = QComboBox()
        self.asr.setEditable(True)
        self.asr.setMinimumContentsLength(18)
        self.asr.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.asr.addItems(["tiny", "base", "small", "medium", "large-v3", "turbo"])
        self.asr.setCurrentText("small")
        models.addRow("识别模型 · Whisper", self.asr)
        choose_asr = QPushButton("选择模型目录…")
        choose_asr.clicked.connect(lambda: self.choose_model(self.asr))
        choose_checkpoint = QPushButton("选择 .pt 文件…")
        choose_checkpoint.clicked.connect(self.choose_checkpoint)
        local_models = QWidget()
        local_buttons = QHBoxLayout(local_models)
        local_buttons.setContentsMargins(0, 0, 0, 0)
        local_buttons.addWidget(choose_asr)
        local_buttons.addWidget(choose_checkpoint)
        local_buttons.addStretch()
        models.addRow(Disclosure('使用已下载的本地权重', local_models))
        self.compute = QComboBox()
        self.compute.addItem("CPU（通用）", "cpu")
        if sys.platform == 'darwin':
            self.compute.addItem('Apple GPU · Metal / MLX', 'mlx')
        if sys.platform != "darwin":
            self.compute.addItem("NVIDIA GPU · 半精度", "cuda")
        self.model_manager.asr_form.insertRow(2, "识别计算设备", self.compute)
        models = self.model_manager.translation_form
        self.translation = QComboBox()
        self.translation.setEditable(True)
        self.translation.setMinimumContentsLength(18)
        self.translation.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.translation.addItems(["facebook/nllb-200-distilled-600M", "tencent/Hy-MT2-1.8B", "facebook/nllb-200-distilled-1.3B"])
        models.addRow("翻译模型", self.translation)
        choose_translation = QPushButton("选择翻译模型目录…")
        choose_translation.clicked.connect(lambda: self.choose_model(self.translation))
        models.addRow(choose_translation)
        self.model_manager.choose_translation = choose_translation
        self.translate = Switch("同时显示翻译")
        self.translate.setChecked(True)
        self.offline = QCheckBox("严格离线 · 只使用已下载模型")
        form_outer.addWidget(self.translate)
        self.model_manager.advanced_form.addRow(self.offline)
        models.addRow(
            label(
                "建议先在这里下载模型，再启用严格离线。音频和字幕只在本机处理。",
                "muted",
            )
        )
        self.model_manager.finish_setup(asr=self.asr, translation=self.translation)
        form_outer.addWidget(label("当前引擎", "section"))
        self.model_summary = label("", "muted")
        form_outer.addWidget(self.model_summary)
        manage = QPushButton("打开模型管理")
        manage.setObjectName("secondary")
        manage.clicked.connect(self.manage_models)
        form_outer.addWidget(manage)
        audio_lab = QPushButton("音频实验室 · 增强与回听")
        audio_lab.clicked.connect(self.manage_audio)
        form_outer.addWidget(audio_lab)
        self.audio_summary = label("音频：原声直通", "muted")
        self.audio_summary.setWordWrap(True)
        form_outer.addWidget(self.audio_summary)
        form_outer.addWidget(label("原文提交后先显示初译。\n识别定稿后，再生成最终译文。", "muted"))
        form_outer.addStretch()
        self.legacy_settings_panel = self.settings_panel
        self.legacy_settings_panel.setParent(self)
        self.legacy_settings_panel.hide()
        split.addWidget(sidebar)
        right = WorkspaceFrame()
        right.setObjectName("workspace")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(1, 1, 0, 0)
        right_layout.setSpacing(0)
        workspace_header = QFrame()
        workspace_header.setObjectName("workspaceHeader")
        toolbar = QHBoxLayout(workspace_header)
        toolbar.setContentsMargins(20, 13, 18, 13)
        self.workspace_title = label("新录音")
        self.workspace_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        toolbar.addWidget(self.workspace_title, 1)
        overlay_button = QPushButton("悬浮字幕")
        overlay_button.setObjectName("quiet")
        overlay_button.clicked.connect(self.toggle_overlay)
        toolbar.addWidget(overlay_button)
        self.export_button = QPushButton("导出定稿")
        self.export_button.setObjectName("quiet")
        self.export_button.clicked.connect(self.export)
        self.export_button.setEnabled(False)
        toolbar.addWidget(self.export_button)
        more = QPushButton("···")
        more.setObjectName("quiet")
        more.setToolTip("更多操作")
        menu = ActionMenu(more)
        menu.addAction("复制最新字幕", self.copy_latest)
        menu.addSeparator()
        menu.addAction("重命名录音", self.rename_current)
        menu.addAction("打开保存位置", self.reveal_recording)
        menu.addAction("刷新文件列表", self.rescan_library)
        menu.addSeparator()
        diagnostics_button = menu.addAction("诊断记录")
        diagnostics_button.setCheckable(True)
        more.setMenu(menu)
        toolbar.addWidget(more)
        right_layout.addWidget(workspace_header)
        content = QWidget()
        content.setObjectName("workspaceContent")
        content_layout = QVBoxLayout(content)
        self.workspace_content = content
        self.workspace_content_layout = content_layout
        content.installEventFilter(self)
        content_layout.setContentsMargins(32, 12, 32, 24)
        content_layout.setSpacing(10)
        self.scroll = CaptionScrollArea()
        self.feed = QWidget()
        self.feed.setObjectName("feed")
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(12, 24, 12, 16)
        self.feed_layout.setSpacing(4)
        self.empty = label(
            "让每一次聆听，都有所留存。\n\n开始录音，原文与译文将在这里自然呈现。",
            "muted",
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(300)
        self.empty.setStyleSheet("font-size: 16px; color: #89898f;")
        self.feed_layout.addWidget(self.empty)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)
        content_layout.addWidget(self.scroll, 1)
        self.reduce_motion = Switch('减少动态效果')
        self.reduce_motion.toggled.connect(lambda value: QApplication.instance().setProperty('reduceMotion', value))
        self.reduce_motion.toggled.connect(self.scroll.content_changed)
        menu.addSeparator()
        menu.addAction('移到最近删除…', self.delete_current)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(500)
        self.diagnostics.setMaximumHeight(160)
        self.diagnostics.hide()
        diagnostics_button.toggled.connect(self.diagnostics.setVisible)
        content_layout.addWidget(self.diagnostics)
        self.meter = QProgressBar()
        self.pipeline = label("音频：未开始   /   识别：未加载   /   翻译：未加载", "muted")
        self.pipeline.hide()
        diagnostics_button.toggled.connect(self.pipeline.setVisible)
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(2)
        content_layout.addWidget(self.meter)
        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(13, 12, 12, 10)
        footer_layout.setSpacing(12)
        input_row = QHBoxLayout()
        input_row.addWidget(label('音频来源', 'muted'))
        self.quick_device = QComboBox()
        self.quick_device.setAccessibleName('音频来源')
        self.quick_device.setPlaceholderText('选择麦克风或系统声音')
        self.quick_device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.quick_device.setMinimumContentsLength(12)
        self.quick_device.setMinimumWidth(0)
        self.quick_device.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.quick_device.setModel(self.device.model())
        self.quick_device.setCurrentIndex(self.device.currentIndex())
        self.quick_device.currentIndexChanged.connect(self.device.setCurrentIndex)
        self.device.currentIndexChanged.connect(self.quick_device.setCurrentIndex)
        self.quick_device.currentTextChanged.connect(self.quick_device.setToolTip)
        input_row.addWidget(self.quick_device, 1)
        self.refresh_source = QPushButton('刷新')
        self.refresh_source.setObjectName('quiet')
        self.refresh_source.setToolTip('刷新音频设备列表')
        self.refresh_source.clicked.connect(self.refresh_devices)
        input_row.addWidget(self.refresh_source)
        footer_layout.addLayout(input_row)
        bottom = QHBoxLayout()
        footer_layout.addLayout(bottom)
        self.status = label("准备开始", "muted")
        bottom.addWidget(self.status, 1)
        self.start_button = QPushButton("开始聆听")
        self.start_button.setFixedWidth(122)
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.stop_button.clicked.connect(self.stop)
        self.pause_button = QPushButton("暂停")
        self.pause_button.setToolTip("暂停收音；已有字幕继续处理，继续后接着录")
        self.pause_button.setEnabled(False)
        self.pause_button.hide()
        self.pause_button.clicked.connect(self.toggle_pause)
        bottom.addWidget(self.start_button)
        bottom.addWidget(self.pause_button)
        bottom.addWidget(self.stop_button)
        self.playback = QFrame()
        playback_layout = QHBoxLayout(self.playback)
        playback_layout.setContentsMargins(8, 4, 8, 4)
        self.play_button = QPushButton("播放录音")
        self.play_button.setObjectName("quiet")
        self.play_button.clicked.connect(self.toggle_playback)
        playback_layout.addWidget(self.play_button)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        playback_layout.addWidget(self.seek, 1)
        self.play_time = label("00:00", "timestamp")
        playback_layout.addWidget(self.play_time)
        self.playback.hide()
        self.player = None
        content_layout.addWidget(self.playback)
        quick = QHBoxLayout()
        self.quick_language = QPushButton('输入与语言')
        self.quick_language.setObjectName('quiet')
        self.quick_language.setToolTip('更改原文和目标语言')
        self.quick_language.clicked.connect(lambda: self.open_settings('聆听'))
        quick.addWidget(self.quick_language)
        self.quick_model = QPushButton('识别模型')
        self.quick_model.setObjectName('quiet')
        self.quick_model.setToolTip('选择和准备本地识别模型')
        self.quick_model.clicked.connect(lambda: self.open_settings('识别模型'))
        quick.addWidget(self.quick_model)
        quick.addStretch()
        content_layout.addLayout(quick)
        content_layout.addWidget(footer)
        right_layout.addWidget(content, 1)
        split.addWidget(right)
        split.setSizes([250, 1030])
        self.refresh_library()
        for widget_type in (QPushButton, QComboBox, QCheckBox):
            for interactive in self.findChildren(widget_type):
                interactive.setCursor(Qt.CursorShape.PointingHandCursor)
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            child.installEventFilter(self)
        self.settings_binding = SettingsBinding({
            pref.key: getattr(self, pref.key) if hasattr(self, pref.key) else getattr(self.model_manager, pref.key)
            for pref in PREFERENCES})
        self.restore()
        QApplication.instance().setProperty('reduceMotion', self.reduce_motion.isChecked())
        self.model_manager.backend.currentIndexChanged.connect(self.sync_asr_device)
        self.compute.currentIndexChanged.connect(self.select_asr_device)
        if sys.platform == 'darwin':
            mac_profile = QPushButton('试用 Mac 4-bit 设置 · Apple GPU')
            mac_profile.clicked.connect(self.use_mac_profile)
            self.model_manager.asr_form.addRow(mac_profile)
        self.update_model_summary()
        self.settings_workspace = SettingsWorkspace(WorkspaceFrame,
            storage_root=self.library.root, manager=self.model_manager,
            controls={key: getattr(self, key) for key in
                      ('device', 'source', 'target', 'translate', 'audio_summary', 'reduce_motion')})
        self.settings_panel = self.settings_workspace.listening_page
        for signal, action in (
                (self.settings_workspace.back_requested, self.leave_settings),
                (self.settings_workspace.open_storage_requested, self.reveal_library),
                (self.settings_workspace.choose_storage_requested, self.choose_library),
                (self.settings_workspace.deleted_requested, self.show_deleted),
                (self.settings_workspace.refresh_devices_requested, self.refresh_devices),
                (self.settings_workspace.audio_requested, self.manage_audio)):
            signal.connect(action)
        self.pages.addWidget(self.settings_workspace)
        self.source.currentTextChanged.connect(self.update_quick_settings)
        self.target.currentTextChanged.connect(self.update_quick_settings)
        self.translate.toggled.connect(self.update_quick_settings)
        self.model_manager.backend.currentIndexChanged.connect(self.update_quick_settings)
        self.update_quick_settings()
        for sequence, action in [('Ctrl+,', self.open_settings), ('Ctrl+N', self.new_recording),
                                 ('Escape', self.return_to_recording), ('Ctrl+F', self.focus_settings_search)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(action)
        self.translate.setText("")
        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self.update_activity)
        self.activity_timer.start(1000)
        if discover:
            QTimer.singleShot(0, self.refresh_devices)

    def open_settings(self, category="常规"):
        category = category if isinstance(category, str) else "常规"
        self.settings_workspace.search.clear()
        self.settings_workspace.navigation.setCurrentRow(self.settings_workspace.categories.index(category))
        self.pages.setCurrentIndex(1)

    def leave_settings(self):
        self.save()
        self.update_model_summary()
        self.pages.setCurrentIndex(0)

    def return_to_recording(self):
        if self.pages.currentIndex() == 1 and QApplication.activeModalWidget() is None:
            self.leave_settings()

    def focus_settings_search(self):
        if self.pages.currentIndex() == 1:
            self.settings_workspace.search.setFocus()
            self.settings_workspace.search.selectAll()

    def update_quick_settings(self):
        language = self.source.currentText()
        self.quick_language.setText(language + (' → ' + self.target.currentText()
                                    if self.translate.isChecked() else ' · 仅原文') + '  ⌄')
        backend = self.model_manager.backend.currentData()
        self.quick_model.setText({'wlk-whisper': 'Whisper', 'qwen3-streaming': 'Qwen3-ASR',
                                 'qwen3-mlx': 'Qwen · Apple GPU'}.get(backend, '识别模型') + '  ⌄')

    def open_recording_library(self, explicit_root):
        def choose_directory(root, error):
            QMessageBox.warning(self, "请选择录音保存位置",
                f"默认目录无法使用：{root}\n{error}\n请选择一个可写目录。")
            return QFileDialog.getExistingDirectory(self, "选择录音保存目录")

        def migration_failed(root, error):
            QMessageBox.warning(self, "旧录音仍保留在原位置",
                f"迁移未完成，可稍后重试。\n{root}\n{error}")

        install_root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        legacy_root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / "AgentScribe" / "library"
        try:
            return open_library(self.prefs, install_root,
                explicit_root=explicit_root or os.environ.get("AGENTSCRIBE_LIBRARY"), legacy_root=legacy_root,
                choose_directory=choose_directory, migration_failed=migration_failed)
        except LibrarySelectionCancelled:
            raise SystemExit(0) from None

    def refresh_library(self):
        expanded = {identifier: row.isExpanded() for identifier, row in getattr(self, "library_rows", {}).items()}
        self.library_tree.clear()
        self.library_rows = {}
        folders = {}
        for folder in self.library.index["folders"]:
            row = QTreeWidgetItem([folder["name"]])
            row.setData(0, Qt.ItemDataRole.UserRole, ("folder", folder["id"]))
            row.setToolTip(0, "点击选中文件夹 · ＋ 新建录音 · 双击折叠/展开 · 右键更多操作")
            parent = folders.get(folder.get("parent"))
            if parent:
                parent.addChild(row)
            else:
                self.library_tree.addTopLevelItem(row)
            folders[folder["id"]] = row
            self.library_rows[folder["id"]] = row
            row.setExpanded(expanded.get(folder["id"], True))
        for item in self.library.index["sessions"]:
            parent = folders.get(item["folder"])
            if parent is None:
                continue
            row = QTreeWidgetItem([item["name"]])
            row.setToolTip(0, item["name"] + "\n右键可重命名、移动或删除")
            row.setData(0, Qt.ItemDataRole.UserRole, ("session", item["id"]))
            parent.addChild(row)
            self.library_rows[item["id"]] = row
            if self.current_item and item["id"] == self.current_item["id"]:
                self.current_item = item
                self.library_tree.setCurrentItem(row)
                self.workspace_title.setText(item["name"])
        if not self.current_item and self.folder_id in folders:
            self.library_tree.setCurrentItem(folders[self.folder_id])

    def rescan_library(self):
        if not self.can_edit_library():
            return
        self.library.refresh()
        if self.current_item and self.current_item["id"] not in self.library.paths:
            self.reset_recording_view()
        if self.folder_id not in self.library.paths:
            self.folder_id = self.library.index["folders"][0]["id"] if self.library.index["folders"] else None
        self.refresh_library()
        if self.current_item and self.current_item["id"] in self.library_rows:
            self.open_library_item(self.library_rows[self.current_item["id"]], 0)
        if self.library.warnings:
            QMessageBox.warning(self, "部分文件未载入", "\n".join(self.library.warnings[:8]))

    def create_folder(self, checked=False, parent_id=None):
        if self.session:
            return
        name, ok = NameDialog.getText(self, "新建文件夹", "文件夹名称")
        if ok:
            try:
                self.folder_id = self.library.folder(name, parent=parent_id)["id"]
                self.refresh_library()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "无法创建文件夹", str(exc))

    def persist_session(self, state=None):
        self.autosave.stop()
        if not self.current_item or self.loading_saved or (not self.session_dirty and state is None):
            return True
        try:
            self.library.save(self.current_item, self.captions.values(), state)
            self.session_dirty = False
            return True
        except (OSError, ValueError) as exc:
            self.status.setText("自动保存失败，请导出字幕备份")
            self.status.setToolTip(str(exc))
            return False

    def release_playback(self):
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.playback.hide()

    def reset_recording_view(self):
        self.release_playback()
        self.autosave.stop()
        self.current_item = None
        self.session_dirty = False
        self.clear_captions()
        self.workspace_title.setText("新录音")
        self.empty.setText("选择文件夹，创建你的第一段录音。\n\n点击文件夹旁的 ＋，为这次聆听起个名字。")
        self.export_button.setEnabled(False)

    def new_recording(self, checked=False, *, folder_id=None, name=None):
        if not self.can_edit_library():
            return False
        self.library.refresh()
        if not self.library.index["folders"]:
            self.create_folder()
            if not self.library.index["folders"]:
                return False
        folder_id = folder_id or self.folder_id or self.library.index["folders"][0]["id"]
        if name is None:
            dialog = RecordingDialog(self.library, folder_id, self)
            if not dialog.exec():
                return False
            name, folder_id = dialog.name.text(), dialog.folder.currentData()
        try:
            item = self.library.create(folder_id, {}, name=name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法创建录音", str(exc))
            return False
        self.reset_recording_view()
        self.folder_id, self.current_item = folder_id, item
        self.workspace_title.setText(item["name"])
        self.empty.setText("准备好时，开始聆听。\n\n录音与定稿会自动保存在这个文件夹。")
        self.status.setText("待开始 · " + self.library.folder_label(folder_id))
        self.refresh_library()
        self.pages.setCurrentIndex(0)
        return True

    def open_library_item(self, row, column):
        if not self.can_edit_library():
            return
        kind, identifier = row.data(0, Qt.ItemDataRole.UserRole)
        if kind == "folder":
            self.reset_recording_view()
            self.folder_id = identifier
            self.workspace_title.setText(row.text(0))
            self.status.setText("点击文件夹旁的 ＋ 新建录音")
            return
        item = next((i for i in self.library.index["sessions"] if i["id"] == identifier), None)
        if item is None:
            return
        try:
            data, captions = self.library.load(item)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "无法打开录音", str(exc))
            return
        self.release_playback()
        self.loading_saved = True
        self.clear_captions()
        self.current_item = item
        self.folder_id = item["folder"]
        self.caption_translation = data["settings"].get("translate", True)
        for caption in captions:
            self.on_caption(caption)
        self.loading_saved = False
        self.session_dirty = False
        self.workspace_title.setText(item["name"])
        states = {"complete": "已保存在本机", "draft": "待开始 · 点击开始聆听"}
        self.status.setText(states.get(item["state"], "未完整结束 · 已保留录音与草稿"))
        self.empty.setText("准备好时，开始聆听。" if item["state"] == "draft" else "这段录音还没有字幕")
        self.export_button.setEnabled(any(c.final and c.source for c in captions))
        self.prepare_playback()

    def rename_current(self):
        if self.current_item:
            self.rename_item(self.current_item)

    def rename_item(self, item):
        if not self.can_edit_library(item):
            return
        name, ok = NameDialog.getText(self, "重命名", "名称", text=item["name"])
        if ok:
            self.release_playback()
            try:
                self.library.rename(item, name)
                self.refresh_library()
                self.prepare_playback()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "重命名失败", str(exc))

    def library_menu(self, point):
        row = self.library_tree.itemAt(point)
        if row:
            self.show_library_menu(row, self.library_tree.viewport().mapToGlobal(point))

    def show_library_menu(self, row, position):
        if self.session:
            return
        kind, identifier = row.data(0, Qt.ItemDataRole.UserRole)
        collection = self.library.index["folders" if kind == "folder" else "sessions"]
        item = next((i for i in collection if i["id"] == identifier), None)
        if item is None:
            return
        menu = ActionMenu(self)
        if kind == "folder":
            menu.addAction("在此文件夹中新建录音…", lambda: self.new_recording(folder_id=identifier))
            menu.addAction("新建子文件夹…", lambda: self.create_folder(parent_id=identifier))
            menu.addSeparator()
        menu.addAction("重命名…", lambda: self.rename_item(item))
        menu.addAction("在资源管理器中打开", lambda: self.open_path(self.library.directory(identifier)))
        move = ActionMenu(menu)
        move.setTitle('移动到文件夹')
        menu.addMenu(move)
        for folder in self.library.index["folders"]:
            if folder["id"] != identifier:
                move.addAction(self.library.folder_label(folder["id"]), lambda f=folder: self.move_recording(item, f["id"]))
        menu.addSeparator()
        menu.addAction("移到最近删除…", lambda: self.delete_item(item))
        menu.exec(position)

    def move_recording(self, item, folder_id):
        if not self.can_edit_library(item):
            return
        self.release_playback()
        try:
            self.library.move(item, folder_id)
            if self.current_item and self.current_item["id"] == item["id"]:
                self.folder_id = folder_id
            self.refresh_library()
            self.prepare_playback()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "移动失败", str(exc))

    def delete_current(self):
        if self.current_item:
            self.delete_item(self.current_item)

    def delete_item(self, item):
        if not self.can_edit_library(item):
            return
        detail = "其中的子文件夹、录音与定稿都会一起移入最近删除。" if "parent" in item else "录音、字幕与定稿将一起移入最近删除。"
        answer = QMessageBox.question(self, "移到最近删除？", f"{item['name']}\n\n{detail}你可以稍后恢复。",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.release_playback()
        try:
            self.library.trash(item)
            if self.current_item and self.current_item["id"] not in self.library.paths:
                self.reset_recording_view()
            if self.folder_id not in self.library.paths:
                self.folder_id = self.library.index["folders"][0]["id"] if self.library.index["folders"] else None
            self.refresh_library()
            self.status.setText("已移到最近删除 · 可从左下角恢复")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "删除失败，原文件保留", str(exc))

    def show_deleted(self):
        if self.session:
            self.status.setText("请先停止录音，再管理最近删除")
            return
        dialog = DeletedDialog(self.library, self)
        dialog.changed.connect(self.refresh_library)
        dialog.exec()
        dialog.deleteLater()

    def can_edit_library(self, item=None):
        if self.session is not None or not self.persist_session():
            return False
        return item is None or self.file_operation_ready(item)

    def file_operation_ready(self, item):
        try:
            check_library_access(self.library, item)
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "暂时无法操作", str(exc))
            return False

    def open_path(self, path):
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def reveal_recording(self):
        try:
            self.open_path(self.library.directory(self.current_item["id"]) if self.current_item else self.library.root)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法打开", str(exc))

    def reveal_library(self):
        self.open_path(self.library.root)

    def choose_library(self):
        if not self.can_edit_library():
            self.status.setText("请先停止录音，再更改保存位置")
            return
        path = QFileDialog.getExistingDirectory(self, "选择录音保存目录（旧文件保留原位）", str(self.library.root))
        if not path:
            return
        try:
            library = Library(path)
            probe = library.root / (".write-check-" + str(time.time_ns()))
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法使用此目录", str(exc))
            return
        self.reset_recording_view()
        self.library = library
        self.folder_id = library.index["folders"][0]["id"]
        self.prefs.setValue("library_directory", str(library.root))
        self.settings_workspace.storage_path.setText(str(library.root))
        self.refresh_library()
        self.status.setText("已切换保存目录 · 旧录音仍保留在原目录，可切换回去查看")

    def prepare_playback(self):
        if self.player:
            self.player.stop()
        path = self.library.directory(self.current_item["id"]) / "录音.wav" if self.current_item else None
        self.playback.setVisible(bool(path and path.exists() and path.stat().st_size > 44))
        if not self.playback.isHidden():
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            if self.player is None:
                self.player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.player.setAudioOutput(self.audio_output)
                self.player.durationChanged.connect(lambda n: self.seek.setRange(0, n))
                self.player.positionChanged.connect(self.playback_position)
                self.seek.sliderMoved.connect(self.player.setPosition)
                self.player.playbackStateChanged.connect(lambda state: self.play_button.setText(
                    "暂停" if state == QMediaPlayer.PlaybackState.PlayingState else "播放录音"))
                self.player.errorOccurred.connect(lambda *_: self.status.setText("录音无法播放：" + self.player.errorString()))
            self.player.setSource(QUrl.fromLocalFile(str(path)))

    def playback_position(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        seconds = position // 1000
        self.play_time.setText(f"{seconds // 60:02}:{seconds % 60:02}")

    def toggle_playback(self):
        if self.player:
            from PySide6.QtMultimedia import QMediaPlayer
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    def restore(self):
        values = read_preferences(self.prefs)
        self.settings_binding.restore(values)
        self.sync_asr_device()
        self.audio_config = values['audio_processing']
        self.update_audio_summary()

    def sync_asr_device(self):
        manager = self.model_manager
        mlx = manager.backend.currentData() == 'qwen3-mlx'
        if mlx:
            self.compute.setCurrentIndex(data_index(self.compute, 'mlx'))
            if manager.qwen_model.currentText().startswith('Qwen/'):
                manager.qwen_model.setCurrentText('mlx-community/Qwen3-ASR-1.7B-4bit')
        elif self.compute.currentData() == 'mlx':
            self.compute.setCurrentIndex(data_index(self.compute, 'cpu'))
        if not mlx and manager.qwen_model.currentText() == 'mlx-community/Qwen3-ASR-1.7B-4bit':
            manager.qwen_model.setCurrentText('Qwen/Qwen3-ASR-0.6B')
        self.compute.setEnabled(not mlx)

    def select_asr_device(self):
        if self.compute.currentData() == 'mlx':
            manager = self.model_manager
            manager.backend.setCurrentIndex(data_index(manager.backend, 'qwen3-mlx'))

    def use_mac_profile(self):
        manager = self.model_manager
        manager.backend.setCurrentIndex(data_index(manager.backend, 'qwen3-mlx'))
        manager.qwen_model.setCurrentText('mlx-community/Qwen3-ASR-1.7B-4bit')
        self.sync_asr_device()
        manager.draft_seconds.setValue(1.)
        manager.endpoint_seconds.setValue(1.)
        self.translate.setChecked(False)
        manager.status.setText('已选择 Apple GPU、4-bit 识别和 SaT 分句，并关闭翻译。准备识别与 SaT 模型后可开始；翻译可在设置中单独开启。')

    def manage_models(self):
        self.open_settings("识别模型")

    def manage_audio(self):
        from .audio_processing.lab import AudioLab
        dialog = AudioLab(self.audio_config, self.device.currentData(), self, discover=True)
        if dialog.exec():
            self.audio_config = dialog.result_config
            index = data_index(self.device, dialog.device)
            if index < 0 and dialog.device is not None:
                self.device.addItem(dialog.source.currentText(), dialog.device)
                index = self.device.count() - 1
            if index >= 0:
                self.device.setCurrentIndex(index)
            self.save()
            self.update_audio_summary()
        dialog.deleteLater()

    def update_audio_summary(self):
        enabled = [name for key, name in [("apm", "APM"), ("highpass", "低频清理"),
                                          ("wpe", "WPE"), ("deepfilter", "DF3"),
                                          ("gain", "响度"), ("eq", "均衡"), ("limiter", "峰值保护")]
                   if self.audio_config.get(key)]
        self.audio_summary.setText("音频：" + (" / ".join(enabled) if enabled else "原声直通")
                                   + (" · 输出增益已调整" if self.audio_config.get("output_db") else ""))

    def update_model_summary(self):
        manager = self.model_manager
        if manager.backend.currentData() == "wlk-whisper":
            text = f"WhisperLiveKit · {self.asr.currentText()}\nAlignAtt · {self.compute.currentText()}"
        else:
            text = f"WhisperLiveKit · {manager.qwen_model.currentText()}\nQwen 窗口式流式 · {self.compute.currentText()}"
        if manager.backend.currentData() == 'qwen3-mlx':
            text += '\n试验后端 · 8GB Mac 建议先关闭翻译'
        self.model_summary.setText(text)

    def save(self):
        values = self.settings_binding.snapshot()
        values.update(audio_processing=self.audio_config, audio_device=self.device.currentData())
        write_preferences(self.prefs, values)

    def choose_model(self, combo):
        path = QFileDialog.getExistingDirectory(self, "选择完整模型目录")
        if path:
            combo.setCurrentText(path)

    def choose_checkpoint(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Whisper 权重", "", "Whisper (*.pt)")
        if path:
            self.asr.setCurrentText(path)

    def refresh_devices(self):
        previous = self.device.currentData()
        if previous is None:
            previous = read_audio_device(self.prefs)
        try:
            devices = list_devices()
            self.device.clear()
            for device in devices:
                self.device.addItem(device.name, (device.id, device.loopback))
            if previous:
                index = data_index(self.device, previous)
                if index >= 0:
                    self.device.setCurrentIndex(index)
                else:
                    self.device.setCurrentIndex(-1)
                    self.status.setText("上次的音频设备不可用，请在设置中重新选择来源。")
                    return
            self.status.setText("就绪" if devices else "未发现录音设备，请连接设备并检查麦克风权限。")
        except Exception as exc:
            self.status.setText(f"无法读取音频设备：{exc}")

    def start(self):
        if self.session is not None:
            return
        if self.model_manager.worker is not None:
            QMessageBox.information(self, "模型准备中", "请等待模型准备完成，或在设置中取消准备。")
            return
        if self.device.currentData() is None:
            QMessageBox.warning(self, "没有音频来源", "请连接录音设备并刷新列表。")
            return
        if self.translate.isChecked() and self.model_manager.translation_engine.currentData() == 'llama':
            from .llama_assets import resolve_assets
            try:
                resolve_assets(self.settings_binding.session_settings(self.device.currentData(), self.audio_config))
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "翻译模型尚未准备好", str(exc))
                return
        if self.model_manager.backend.currentData() in ('qwen3-streaming', 'qwen3-mlx') and self.source.currentData()[0] is None:
            QMessageBox.warning(self, "请选择原文语言", "Qwen 流式模式需要明确原文语言，例如 English 或简体中文。")
            return
        if self.model_manager.backend.currentData() in ('qwen3-streaming', 'qwen3-mlx'):
            from .model_cache import resolve_qwen_cached, validate_mlx_model
            try:
                path = resolve_qwen_cached(self.model_manager.qwen_model.currentText().strip())
                if self.model_manager.backend.currentData() == 'qwen3-mlx':
                    from .runtime_paths import mlx_python
                    validate_mlx_model(path)
                    if not mlx_python().is_file():
                        raise ValueError('请先到运行环境页安装 Apple GPU / MLX 识别环境。')
            except ValueError as exc:
                QMessageBox.warning(self, "模型尚未准备好", str(exc))
                return
        if ((self.model_manager.backend.currentData() == "wlk-whisper" and not self.asr.currentText().strip())
                or (self.translate.isChecked() and self.model_manager.translation_engine.currentData() == 'pytorch'
                    and not self.translation.currentText().strip())):
            QMessageBox.warning(self, "模型为空", "请选择模型名称或本地模型目录。")
            return
        if not self.current_item or self.current_item["state"] != "draft":
            if not self.new_recording():
                return
        self.clear_captions()
        self.last_error = ""
        self.pipeline_state = {
            "音频": "等待识别就绪",
            "识别": "准备中",
            "翻译": "等待" if self.translate.isChecked() else "关闭",
        }
        self.on_stage("会话", "启动中")
        self.diagnostics.clear()
        self.on_status("正在启动本地推理环境…可点击停止取消加载。")
        self.empty.setText("正在准备模型和验证推理环境…\n准备好后自动开始录音，加载进度显示在下方。")
        settings = self.settings_binding.session_settings(self.device.currentData(), self.audio_config)
        self.save()
        self.set_recording_state(RecordingState.STARTING)
        try:
            self.recording_lock = acquire_recording_lock(self.library.directory(self.current_item["id"]))
            self.library.begin(self.current_item, asdict(settings))
        except (OSError, ValueError) as exc:
            if self.recording_lock:
                self.recording_lock.unlock()
                self.recording_lock = None
            self.set_recording_state(RecordingState.IDLE)
            self.on_failure(f"无法保存录音：{exc}")
            return
        self.caption_translation = settings.translate
        self.workspace_title.setText(self.current_item["name"])
        self.refresh_library()
        try:
            self.launch_session(settings)
        except (OSError, RuntimeError) as exc:
            self.on_failure(f"无法启动录音：{exc}")
            if self.session is not None:
                self.on_finished()
            else:
                self.persist_session('incomplete')
                self.recording_lock.unlock()
                self.recording_lock = None
                self.set_recording_state(RecordingState.IDLE)

    def set_recording_state(self, state):
        self.recording_state = state
        for control in (self.settings_panel, self.model_manager, self.settings_workspace.audio_page,
                        self.library_tree, self.new_button, self.folder_button, self.quick_device, self.refresh_source):
            control.setEnabled(not state.active)
        self.start_button.setEnabled(not state.active)
        self.start_button.setText(state.value)
        self.stop_button.setEnabled(state.can_stop)
        self.stop_button.setVisible(state.active)
        self.pause_button.setVisible(state.active)
        self.pause_button.setEnabled(state.can_pause and not self.last_error)
        self.pause_button.setText("继续录音" if state is RecordingState.PAUSED else "暂停")
        self.export_button.setEnabled(not state.active and any(c.final and c.source for c in self.captions.values()))

    def launch_session(self, settings):
        self.session = Session(settings, self, recording_path=
                               self.library.directory(self.current_item["id"]) / "录音.wav")
        self.session.status.connect(self.on_status)
        self.session.stage.connect(self.on_stage)
        self.session.ready.connect(self.on_ready)
        self.session.paused.connect(self.on_paused)
        self.session.caption.connect(self.on_caption)
        self.session.level.connect(lambda value: self.meter.setValue(min(100, int(value * 500))))
        self.session.failure.connect(self.on_failure)
        self.session.finished.connect(self.on_finished)
        self.session.start()

    def on_stage(self, name, state):
        self.pipeline_state[name] = state
        self.pipeline.setText(
            "   /   ".join(f"{name}：{value}" for name, value in self.pipeline_state.items())
        )

    def on_status(self, message):
        self.diagnostics.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)
        if self.last_error:
            return
        self.phase_started = time.monotonic()
        self.status.setToolTip(message)
        self.update_activity()

    def update_activity(self):
        if self.recording_state.active and not self.last_error:
            elapsed = int(time.monotonic() - self.phase_started)
            self.status.setText(self.recording_state.status(elapsed))

    def on_ready(self):
        if self.last_error:
            return
        if self.recording_state is not RecordingState.STARTING:
            return
        self.set_recording_state(RecordingState.LISTENING)
        self.on_stage("会话", "聆听中")
        self.on_status("识别已就绪，正在聆听；翻译模型独立加载。" if self.translate.isChecked()
                       else "识别已就绪，正在聆听。")
        self.empty.setText("正在聆听…")

    def clear_captions(self):
        self.scroll.reset_follow()
        for card in self.cards.values():
            card.hide()
            self.feed_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        self.captions.clear()
        self.empty.show()
        self.overlay.source.setText("等待语音…")
        self.overlay.target.setText("")

    def stop(self):
        if self.session:
            self.set_recording_state(RecordingState.STOPPING)
            self.on_status("正在停止并处理剩余字幕；模型加载或当前推理结束后完成…")
            self.session.stop()

    def toggle_pause(self):
        if self.session is None or self.last_error:
            return
        if self.recording_state is RecordingState.LISTENING:
            if self.session.pause():
                self.set_recording_state(RecordingState.PAUSING)
                self.on_status("正在暂停收音；已有音频继续识别和翻译。")
        elif self.recording_state is RecordingState.PAUSED:
            if self.session.resume():
                self.set_recording_state(RecordingState.RESUMING)
                self.on_status("正在继续当前录音。")

    def on_paused(self, paused):
        if self.last_error or self.recording_state is RecordingState.STOPPING or self.session is None:
            return
        expected = RecordingState.PAUSING if paused else RecordingState.RESUMING
        if self.recording_state is not expected:
            return
        self.set_recording_state(RecordingState.PAUSED if paused else RecordingState.LISTENING)
        self.on_stage("会话", "已暂停" if paused else "聆听中")
        self.on_status("已暂停收音；点击继续录音可接着录，暂停时间不计入录音。" if paused else "已继续录音。")
        if paused:
            self.meter.setValue(0)
        if not self.captions:
            self.empty.setText("已暂停收音" if paused else "正在聆听…")

    def on_failure(self, message):
        self.last_error = message
        self.pause_button.setEnabled(False)
        self.status.setText(message)
        self.diagnostics.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)
        self.diagnostics.show()
        if not self.captions:
            self.empty.setText(message)

    def on_finished(self):
        if self.caption_translation:
            for caption in list(self.captions.values()):
                if caption.final and (not caption.translation or caption.translation_phase == 'initial') and not caption.error:
                    self.on_caption(replace(caption, error="会话已结束，此条翻译未完成"))
        self.session.deleteLater()
        self.session = None
        self.set_recording_state(RecordingState.IDLE)
        translation_incomplete = self.caption_translation and any(
            c.source and (c.error or not c.translation or c.translation_phase == 'initial') for c in self.captions.values())
        state = "incomplete" if self.last_error or translation_incomplete else "complete"
        if self.current_item and not self.last_error and not self.captions:
            try:
                if not (self.library.directory(self.current_item["id"]) / "录音.wav").exists():
                    state = "draft"
            except (OSError, ValueError):
                state = "incomplete"
        saved = self.persist_session(state)
        if self.recording_lock:
            self.recording_lock.unlock()
            self.recording_lock = None
        self.refresh_library()
        self.prepare_playback()
        self.meter.setValue(0)
        self.status.setText(self.last_error or ("已取消 · 录音尚未开始" if state == "draft" and saved else
                            "录音已保存 · 部分翻译未完成" if saved and translation_incomplete else
                            "已保存录音与定稿" if saved else "保存失败，请导出字幕备份"))
        self.on_stage("会话", "失败，详见诊断" if self.last_error else "已结束")
        if self.closing:
            self.close()

    def on_caption(self, caption):
        if self.current_item and not self.loading_saved:
            self.session_dirty = True
        previous = self.captions.get(caption.id)
        if previous and (caption.revision < previous.revision or
                         (caption.revision == previous.revision and caption.source != previous.source)):
            return
        self.scroll.prepare_update()
        if not caption.source:
            self.captions.pop(caption.id, None)
            card = self.cards.pop(caption.id, None)
            if card:
                self.feed_layout.removeWidget(card)
                card.deleteLater()
            self.empty.setVisible(not self.captions)
            if self.current_item and not self.loading_saved:
                self.autosave.start(800)
            if self.captions:
                self.overlay.update_caption(self.captions[max(self.captions)], self.translate.isChecked())
            else:
                self.overlay.source.setText("等待语音…")
                self.overlay.target.setText("")
            self.scroll.content_changed()
            return
        self.empty.hide()
        if (previous and previous.source == caption.source and previous.language == caption.language
                and not caption.translation and (caption.ready or caption.final)):
            caption = replace(caption, translation=previous.translation,
                              translation_source=previous.translation_source,
                              translation_phase=previous.translation_phase)
        self.captions[caption.id] = caption
        if caption.id in self.cards:
            self.cards[caption.id].update_caption(caption)
        elif caption.id >= max(self.captions) - 199:
            card = CaptionCard(caption, self.caption_translation)
            self.cards[caption.id] = card
            self.feed_layout.insertWidget(self.feed_layout.count() - 1, card)
            # Bound Qt widget count while retaining the complete export in memory.
            if len(self.cards) > 200:
                old = self.cards.pop(min(self.cards))
                old.hide()
                self.feed_layout.removeWidget(old)
                old.deleteLater()
        if caption.id == max(self.captions):
            self.overlay.update_caption(caption, self.caption_translation)
        self.export_button.setEnabled(any(c.final and c.source for c in self.captions.values()))
        if self.current_item and not self.loading_saved and not self.autosave.isActive():
            self.autosave.start(1500)
        self.scroll.content_changed()

    def toggle_overlay(self):
        self.overlay.setVisible(not self.overlay.isVisible())

    def copy_latest(self):
        if not self.captions:
            self.status.setText("还没有可复制的字幕")
            return
        caption = self.captions[max(self.captions)]
        QApplication.clipboard().setText("\n".join(x for x in (caption.source, caption.translation) if x))
        self.status.setText("已复制最新字幕")

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出双语字幕", "字幕.srt", "SubRip 字幕 (*.srt)")
        if path:
            try:
                captions = [self.captions[k] for k in sorted(self.captions) if self.captions[k].final and self.captions[k].source]
                Path(path).write_text(export_srt(captions), encoding="utf-8-sig")
                self.status.setText(f"已导出 {len(captions)} 条字幕：{path}")
            except OSError as exc:
                QMessageBox.warning(self, "导出失败", str(exc))

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Resize and hasattr(self, "workspace_content")
                and watched is self.workspace_content):
            margin = max(20, (event.size().width() - 900) // 2)
            self.workspace_content_layout.setContentsMargins(margin, 12, margin, 20)
        if (sys.platform == "win32"
                and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and watched.window() is self
                and not self.isMaximized()):
            point = self.mapFromGlobal(event.globalPosition().toPoint())
            margin = 7
            edges = Qt.Edge(0)
            if point.x() <= margin:
                edges |= Qt.Edge.LeftEdge
            elif point.x() >= self.width() - margin:
                edges |= Qt.Edge.RightEdge
            if point.y() <= margin:
                edges |= Qt.Edge.TopEdge
            elif point.y() >= self.height() - margin:
                edges |= Qt.Edge.BottomEdge
            if edges and self.windowHandle():
                self.windowHandle().startSystemResize(edges)
                return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            maximized = self.isMaximized()
            self.title_bar.maximize.setText("❐" if maximized else "□")
            self.title_bar.maximize.setToolTip("还原" if maximized else "最大化")

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.centralWidget() is not None:
            self.centralWidget().update()

    def showEvent(self, event):
        super().showEvent(event)
        if (not self._backdrop_attempted
                and sys.platform == "win32"
                and os.environ.get("QT_QPA_PLATFORM") != "offscreen"):
            self._backdrop_attempted = True
            self._backdrop_applied = enable_system_backdrop(self)

    def closeEvent(self, event):
        if self.model_manager.worker is not None:
            self.model_manager.cancel_preparation()
            self.model_manager.worker.finished.connect(self.close)
            event.ignore()
            return
        if self.session is not None:
            self.closing = True
            self.stop()
            self.status.setText("正在释放模型，请等待当前加载或推理结束…")
            event.ignore()
            return
        if not self.persist_session():
            event.ignore()
            return
        if self.player:
            self.player.stop()
        self.save()
        self.overlay.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    sys.exit(app.exec())
