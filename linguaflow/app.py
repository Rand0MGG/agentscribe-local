import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .audio import list_devices
from .core import LANGUAGES, Settings, export_srt
from .management import ModelManager
from .wlk_session import Session

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
            max(1, size.width() // 24),
            max(1, size.height() // 24),
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
                painter.drawPixmap(self.rect(), self._blurred, source)
        painter.end()


def label(text, name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


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
        title = label("LinguaFlow · 本地同声字幕")
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


class Overlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("overlay")
        self.setWindowTitle("LinguaFlow · 悬浮字幕")
        self.resize(800, 180)
        layout = QVBoxLayout(self)
        self.source = label("等待语音…", "muted")
        self.target = label("译文会显示在这里")
        self.target.setStyleSheet("font-size: 26px; font-weight: 600; color: #e2e2e2;")
        layout.addWidget(self.source)
        layout.addWidget(self.target)

    def update_caption(self, caption, translating=True):
        self.source.setText(caption.source)
        self.target.setText(caption.translation or caption.error or
                            ("原文修订中…" if not caption.final else "翻译中…" if translating else ""))


class CaptionCard(QFrame):
    def __init__(self, caption, translating):
        super().__init__()
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 17)
        self.meta = label(
            f"{int(caption.start) // 60:02}:{int(caption.start) % 60:02}  ·  {caption.language.upper()}",
            "muted",
        )
        self.source = label(caption.source)
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target = label("")
        self.target.setStyleSheet("font-size: 18px; color: #dddddd;")
        self.target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.meta)
        layout.addWidget(self.source)
        layout.addWidget(self.target)
        self.translating = translating
        self.update_caption(caption)

    def update_caption(self, caption):
        self.source.setText(caption.source)
        state = "已定稿" if caption.final else "听写中 · 后文可修正原文"
        self.meta.setText(f"{int(caption.start) // 60:02}:{int(caption.start) % 60:02}  ·  {caption.language.upper()}  ·  {state}")
        self.target.setText(
            caption.translation
            or (f"⚠ {caption.error}" if caption.error else
                ("原文确认后翻译" if not caption.final and self.translating else
                 "翻译中…" if self.translating else "仅转写"))
        )


class Window(QMainWindow):
    def __init__(self, discover=True):
        super().__init__()
        self._backdrop_applied = False
        self._backdrop_attempted = False
        if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("LinguaFlow · 本地同声字幕")
        self.resize(1180, 800)
        self.setMinimumSize(900, 650)
        self.session = None
        self.last_error = ""
        self.phase_text = ""
        self.phase_started = time.monotonic()
        self.pipeline_state = {"音频": "未开始", "识别": "未加载", "翻译": "未加载"}
        self.captions = {}
        self.cards = {}
        self.closing = False
        self.overlay = Overlay()
        self.prefs = QSettings("LinguaFlow", "LocalCaptions")
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
        layout.addWidget(split, 1)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(300)
        sidebar.setMaximumWidth(380)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 18, 14, 14)
        sidebar_layout.setSpacing(10)
        sidebar_header = QHBoxLayout()
        sidebar_header.addWidget(label("LinguaFlow", "brand"))
        sidebar_header.addStretch()
        sidebar_header.addWidget(label("●  本地", "pill"))
        sidebar_layout.addLayout(sidebar_header)
        sidebar_layout.addWidget(label("实时字幕工作区", "muted"))
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
        self.model_manager = ModelManager(self)
        models = self.model_manager.whisper_form
        self.asr = QComboBox()
        self.asr.setEditable(True)
        self.asr.setMinimumContentsLength(18)
        self.asr.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.asr.addItems(["tiny", "base", "small", "medium", "large-v3", "turbo"])
        self.asr.setCurrentText("small")
        models.addRow("识别模型 · Whisper", self.asr)
        choose_asr = QPushButton("选择识别模型目录…")
        choose_asr.clicked.connect(lambda: self.choose_model(self.asr))
        models.addRow(choose_asr)
        choose_checkpoint = QPushButton("选择 Whisper .pt 文件…")
        choose_checkpoint.clicked.connect(self.choose_checkpoint)
        models.addRow(choose_checkpoint)
        self.compute = QComboBox()
        self.compute.addItem("CPU（通用）", "cpu")
        if sys.platform != "darwin":
            self.compute.addItem("NVIDIA GPU · 半精度", "cuda")
        self.model_manager.asr_form.addRow("识别计算设备", self.compute)
        models = self.model_manager.translation_form
        self.translation = QComboBox()
        self.translation.setEditable(True)
        self.translation.setMinimumContentsLength(18)
        self.translation.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.translation.addItems(["facebook/nllb-200-distilled-600M", "facebook/nllb-200-distilled-1.3B"])
        models.addRow("翻译模型 · NLLB", self.translation)
        choose_translation = QPushButton("选择翻译模型目录…")
        choose_translation.clicked.connect(lambda: self.choose_model(self.translation))
        models.addRow(choose_translation)
        self.translate = QCheckBox("同时显示翻译")
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
        self.model_manager.finish_setup(self)
        form_outer.addWidget(label("当前引擎", "section"))
        self.model_summary = label("", "muted")
        form_outer.addWidget(self.model_summary)
        manage = QPushButton("打开模型管理")
        manage.setObjectName("secondary")
        manage.clicked.connect(self.manage_models)
        form_outer.addWidget(manage)
        form_outer.addWidget(label("原文先出现，并随后文修正。\n确认短句后，逐句显示译文。", "muted"))
        form_outer.addStretch()
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setWidget(self.settings_panel)
        sidebar_layout.addWidget(settings_scroll, 1)
        split.addWidget(sidebar)
        right = QFrame()
        right.setObjectName("workspace")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        workspace_header = QFrame()
        workspace_header.setObjectName("workspaceHeader")
        toolbar = QHBoxLayout(workspace_header)
        toolbar.setContentsMargins(20, 13, 18, 13)
        toolbar.addWidget(label("实时双语字幕", "title"))
        toolbar.addWidget(label("LIVE", "pill"))
        toolbar.addStretch()
        diagnostics_button = QPushButton("诊断记录")
        diagnostics_button.setCheckable(True)
        toolbar.addWidget(diagnostics_button)
        clear_button = QPushButton("清空")
        clear_button.setToolTip("清除当前字幕，不影响模型和设置")
        clear_button.clicked.connect(self.clear_captions)
        toolbar.addWidget(clear_button)
        copy_button = QPushButton("复制最新")
        copy_button.setToolTip("复制最新一条原文和译文")
        copy_button.clicked.connect(self.copy_latest)
        toolbar.addWidget(copy_button)
        overlay_button = QPushButton("悬浮字幕")
        overlay_button.clicked.connect(self.toggle_overlay)
        toolbar.addWidget(overlay_button)
        self.export_button = QPushButton("导出 SRT")
        self.export_button.clicked.connect(self.export)
        self.export_button.setEnabled(False)
        toolbar.addWidget(self.export_button)
        right_layout.addWidget(workspace_header)
        content = QWidget()
        content.setObjectName("workspaceContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 12, 18, 14)
        content_layout.setSpacing(10)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.feed = QWidget()
        self.feed.setObjectName("feed")
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(0, 6, 0, 0)
        self.feed_layout.setSpacing(12)
        self.empty = label(
            "让对话跨越语言\n\n① 在模型管理中准备识别模型\n② 选择音频来源和语言\n③ 开始聆听，原文会持续修订，定稿后翻译",
            "muted",
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feed_layout.addWidget(self.empty)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)
        content_layout.addWidget(self.scroll, 1)
        self.follow = QCheckBox("自动滚动到最新字幕")
        self.follow.setChecked(True)
        content_layout.addWidget(self.follow)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(500)
        self.diagnostics.setMaximumHeight(160)
        self.diagnostics.hide()
        diagnostics_button.toggled.connect(self.diagnostics.setVisible)
        content_layout.addWidget(self.diagnostics)
        self.meter = QProgressBar()
        self.pipeline = label("音频：未开始   /   识别：未加载   /   翻译：未加载", "muted")
        content_layout.addWidget(self.pipeline)
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        self.meter.setTextVisible(False)
        content_layout.addWidget(self.meter)
        footer = QFrame()
        footer.setObjectName("footer")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(13, 9, 9, 9)
        self.status = label("就绪 · 模型在开始聆听后加载", "muted")
        bottom.addWidget(self.status, 1)
        self.start_button = QPushButton("开始聆听")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        bottom.addWidget(self.start_button)
        bottom.addWidget(self.stop_button)
        content_layout.addWidget(footer)
        right_layout.addWidget(content, 1)
        split.addWidget(right)
        split.setSizes([330, 1050])
        for widget_type in (QPushButton, QComboBox, QCheckBox):
            for interactive in self.findChildren(widget_type):
                interactive.setCursor(Qt.CursorShape.PointingHandCursor)
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            child.installEventFilter(self)
        self.restore()
        self.update_model_summary()
        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self.update_activity)
        self.activity_timer.start(1000)
        if discover:
            QTimer.singleShot(0, self.refresh_devices)

    def restore(self):
        for key, combo in [("asr", self.asr), ("translation", self.translation)]:
            value = self.prefs.value(key)
            if value:
                combo.setCurrentText(str(value))
        for key, combo in [("source", self.source), ("target", self.target), ("compute", self.compute)]:
            value = self.prefs.value(key)
            index = combo.findText(str(value))
            if key == "compute" and "NVIDIA" in str(value):
                index = combo.findData("cuda")
            if index >= 0:
                combo.setCurrentIndex(index)
        self.offline.setChecked(self.prefs.value("offline", False, type=bool))
        self.translate.setChecked(self.prefs.value("translate", True, type=bool))
        manager = self.model_manager
        backend = self.prefs.value("backend", "wlk-whisper")
        backend = {"whisper-live": "wlk-whisper", "qwen-stream": "qwen3-streaming"}.get(backend, backend)
        index = manager.backend.findData(backend)
        manager.backend.setCurrentIndex(max(0, index))
        manager.qwen_model.setCurrentText(self.prefs.value("qwen_model", "Qwen/Qwen3-ASR-0.6B"))
        manager.translation_device.setCurrentIndex(max(0, manager.translation_device.findData(self.prefs.value("translation_device", self.compute.currentData()))))
        for key in ["update_seconds", "endpoint_seconds"]:
            getattr(manager, key).setValue(self.prefs.value(key, 0.5 if key == "endpoint_seconds" else 1.0, type=float))

    def manage_models(self):
        self.model_manager.exec()
        self.save()
        self.update_model_summary()

    def update_model_summary(self):
        manager = self.model_manager
        if manager.backend.currentData() == "wlk-whisper":
            text = f"WhisperLiveKit · {self.asr.currentText()}\nAlignAtt · {self.compute.currentText()}"
        else:
            text = f"WhisperLiveKit · {manager.qwen_model.currentText()}\nQwen 窗口式流式 · {self.compute.currentText()}"
        self.model_summary.setText(text)

    def save(self):
        for key, combo in [
            ("asr", self.asr),
            ("translation", self.translation),
            ("source", self.source),
            ("target", self.target),
            ("compute", self.compute),
        ]:
            self.prefs.setValue(key, combo.currentText())
        self.prefs.setValue("offline", self.offline.isChecked())
        self.prefs.setValue("translate", self.translate.isChecked())
        manager = self.model_manager
        self.prefs.setValue("backend", manager.backend.currentData())
        self.prefs.setValue("qwen_model", manager.qwen_model.currentText())
        self.prefs.setValue("translation_device", manager.translation_device.currentData())
        for key in ["update_seconds", "endpoint_seconds"]:
            self.prefs.setValue(key, getattr(manager, key).value())

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
        try:
            devices = list_devices()
            self.device.clear()
            for device in devices:
                self.device.addItem(device.name, (device.id, device.loopback))
            if previous:
                index = self.device.findData(previous)
                if index >= 0:
                    self.device.setCurrentIndex(index)
            self.status.setText("就绪" if devices else "未发现录音设备，请连接设备并检查麦克风权限。")
        except Exception as exc:
            self.status.setText(f"无法读取音频设备：{exc}")

    def start(self):
        if self.session is not None:
            return
        if self.device.currentData() is None:
            QMessageBox.warning(self, "没有音频来源", "请连接录音设备并刷新列表。")
            return
        if self.model_manager.backend.currentData() == "qwen3-streaming" and self.source.currentData()[0] is None:
            QMessageBox.warning(self, "请选择原文语言", "Qwen 流式模式需要明确原文语言，例如 English 或简体中文。")
            return
        if self.model_manager.backend.currentData() == "qwen3-streaming":
            from .model_cache import resolve_qwen_cached
            try:
                resolve_qwen_cached(self.model_manager.qwen_model.currentText().strip())
            except ValueError as exc:
                QMessageBox.warning(self, "模型尚未准备好", str(exc))
                return
        if ((self.model_manager.backend.currentData() == "wlk-whisper" and not self.asr.currentText().strip())
                or (self.translate.isChecked() and not self.translation.currentText().strip())):
            QMessageBox.warning(self, "模型为空", "请选择模型名称或本地模型目录。")
            return
        if self.captions:
            answer = QMessageBox.question(
                self, "开始新会话", "新会话会清空当前字幕。需要保存时请先导出 SRT。继续？"
            )
            if answer != QMessageBox.StandardButton.Yes:
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
        device_id, loopback = self.device.currentData()
        source, source_nllb = self.source.currentData()
        settings = Settings(
            device_id=device_id,
            loopback=loopback,
            asr_model=self.asr.currentText().strip(),
            asr_device=self.compute.currentData(),
            translation_model=self.translation.currentText().strip(),
            source=source,
            source_nllb=source_nllb,
            target=self.target.currentData(),
            translate=self.translate.isChecked(),
            offline=self.offline.isChecked(),
            backend=self.model_manager.backend.currentData(),
            translation_device=self.model_manager.translation_device.currentData(),
            qwen_model=self.model_manager.qwen_model.currentText(),
            update_seconds=self.model_manager.update_seconds.value(),
            endpoint_seconds=self.model_manager.endpoint_seconds.value(),
        )
        self.save()
        self.settings_panel.setEnabled(False)
        self.start_button.setEnabled(False)
        self.start_button.setText("正在启动…")
        self.stop_button.setEnabled(True)
        self.export_button.setEnabled(False)
        self.session = Session(settings, self)
        self.session.status.connect(self.on_status)
        self.session.stage.connect(self.on_stage)
        self.session.ready.connect(self.on_ready)
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
        self.phase_text = message
        self.phase_started = time.monotonic()
        self.status.setText(message)

    def update_activity(self):
        if self.session is not None and not self.last_error and self.phase_text:
            elapsed = int(time.monotonic() - self.phase_started)
            self.status.setText(f"{self.phase_text}  ·  已等待 {elapsed} 秒")

    def on_ready(self):
        if self.last_error:
            return
        self.start_button.setText("聆听中")
        self.on_stage("会话", "聆听中")
        self.on_status("识别已就绪，正在聆听；翻译模型独立加载。" if self.translate.isChecked()
                       else "识别已就绪，正在聆听。")
        self.empty.setText("识别已就绪，正在等待语音…\n若有音量但没有原文，请打开诊断记录查看每段识别结果。")

    def clear_captions(self):
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
            self.session.stop()
            self.stop_button.setEnabled(False)
            self.on_status("正在停止并处理剩余字幕；模型加载或当前推理结束后完成…")

    def on_failure(self, message):
        self.last_error = message
        self.status.setText(message)
        self.diagnostics.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)
        self.diagnostics.show()
        if not self.captions:
            self.empty.setText(message)

    def on_finished(self):
        if self.translate.isChecked():
            for caption in list(self.captions.values()):
                if caption.final and not caption.translation and not caption.error:
                    self.on_caption(replace(caption, error="会话已结束，此条翻译未完成"))
        self.session.deleteLater()
        self.session = None
        self.settings_panel.setEnabled(True)
        self.start_button.setEnabled(True)
        self.start_button.setText("开始聆听")
        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(any(c.final and c.source for c in self.captions.values()))
        self.meter.setValue(0)
        self.status.setText(self.last_error or f"会话已结束 · {len(self.captions)} 条字幕 · 模型已释放")
        self.on_stage("会话", "失败，详见诊断" if self.last_error else "已结束")
        if self.closing:
            self.close()

    def on_caption(self, caption):
        previous = self.captions.get(caption.id)
        if previous and (caption.revision < previous.revision or (previous.final and not caption.final)):
            return
        if not caption.source:
            self.captions.pop(caption.id, None)
            card = self.cards.pop(caption.id, None)
            if card:
                self.feed_layout.removeWidget(card)
                card.deleteLater()
            self.empty.setVisible(not self.captions)
            if self.captions:
                self.overlay.update_caption(self.captions[max(self.captions)], self.translate.isChecked())
            else:
                self.overlay.source.setText("等待语音…")
                self.overlay.target.setText("")
            return
        self.empty.hide()
        self.captions[caption.id] = caption
        if caption.id in self.cards:
            self.cards[caption.id].update_caption(caption)
        elif caption.id >= max(self.captions) - 199:
            card = CaptionCard(caption, self.translate.isChecked())
            self.cards[caption.id] = card
            self.feed_layout.insertWidget(self.feed_layout.count() - 1, card)
            # Bound Qt widget count while retaining the complete export in memory.
            if len(self.cards) > 200:
                old = self.cards.pop(min(self.cards))
                old.hide()
                self.feed_layout.removeWidget(old)
                old.deleteLater()
        if caption.id == max(self.captions):
            self.overlay.update_caption(caption, self.translate.isChecked())
        if self.follow.isChecked():
            QTimer.singleShot(
                0, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
            )

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
        if self.session is not None:
            self.closing = True
            self.session.stop(discard=True)
            self.stop_button.setEnabled(False)
            self.status.setText("正在释放模型，请等待当前加载或推理结束…")
            event.ignore()
            return
        self.overlay.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    sys.exit(app.exec())
