import json
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
    QSignalBlocker,
    QSize,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .audio import list_devices
from .caption_view import CaptionScrollArea, CaptionText
from .core import LANGUAGES
from .deleted_dialog import DeletedDialog
from .knowledge.client import KnowledgeClient
from .knowledge.panel import KnowledgePanel
from .knowledge.session import read_manifest, session_context
from .library import Library
from .library_access import acquire_recording_lock, check_library_access
from .library_startup import LibrarySelectionCancelled, open_library
from .management import ModelManager
from .model_options import asr_devices, normalize_asr_selection, recommended_selection
from .preferences import PREFERENCES, read_audio_device, read_preferences, write_preferences
from .qt_controls import data_index
from .qt_controls import text_label as label
from .recording_save import RecordingSaver
from .recording_state import RecordingState
from .runtime_preparation import RuntimePreparation
from .settings_binding import SettingsBinding
from .subtitles_overlay import Overlay
from .ui_backdrop import desktop_wallpaper_path, frosted_wallpaper
from .ui_components import (
    ActionMenu,
    AudioLevelMeter,
    FloatingIsland,
    NameDialog,
    SurfaceDialog,
)
from .ui_components import ChoiceBox as QComboBox
from .ui_theme import STYLE, WORKSPACE_RADIUS, appearance_style, theme_colors
from .window_platform import enable_native_resize, enable_system_backdrop, start_edge_resize
from .wlk_session import Session
from .workspace_widgets import LanguagePopup, LibraryTree, RecordingDialog, SettingsWorkspace, Switch


class WallpaperBackdrop(QWidget):
    """Paint a blurred, screen-aligned wallpaper beneath the L-shaped glass."""

    def __init__(self):
        super().__init__()
        self.setObjectName("appRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._wallpaper_path = ""
        self._wallpaper_stamp = 0
        self._source = QPixmap()
        self._blurred = QPixmap()
        self._blurred_size = None
        self._blurred_appearance = None
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
        self._wallpaper_path = path
        self._wallpaper_stamp = stamp
        self._source = wallpaper
        self._blurred = QPixmap()
        self._blurred_size = None
        self.update()

    def _build_blurred_wallpaper(self, size):
        if size.isEmpty():
            return
        self._blurred_appearance = QApplication.instance().property('appearance') or 'light'
        self._blurred = frosted_wallpaper(self._source, size, self._blurred_appearance)
        self._blurred_size = size

    def paintEvent(self, event):
        painter = QPainter(self)
        appearance = QApplication.instance().property('appearance') or 'light'
        painter.fillRect(self.rect(), QColor(theme_colors(appearance)['glass']))
        screen = self.window().screen() or QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            if self._blurred_size != geometry.size() or self._blurred_appearance != appearance:
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


class WindowButton(QPushButton):
    """Draw window controls without depending on symbol-font fallback."""
    def __init__(self, host, kind):
        super().__init__('')
        self.host, self.kind = host, kind
        self.setObjectName('windowClose' if kind == 'close' else 'windowControl')

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme_colors(QApplication.instance().property('appearance'))
        p.setPen(QPen(QColor('#ffffff' if self.kind == 'close' and self.underMouse() else c['text']), 1.2))
        x, y = self.width() // 2, self.height() // 2
        if self.kind == 'close':
            p.drawLine(x-4, y-4, x+4, y+4)
            p.drawLine(x-4, y+4, x+4, y-4)
        elif self.kind == 'minimize':
            p.drawLine(x-5, y, x+5, y)
        elif self.host.isMaximized():
            p.drawRect(x-3, y-5, 8, 8)
            p.fillRect(x-5, y-3, 8, 8, QColor(c['glass']))
            p.drawRect(x-5, y-3, 8, 8)
        else:
            p.drawRect(x-4, y-4, 8, 8)


class GlassTitleBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.host = window
        self.setObjectName("glassTopBar")
        self.setFixedHeight(44)
        bar = QHBoxLayout(self)
        bar.setContentsMargins(13, 0, 0, 0)
        bar.setSpacing(8)
        title = label("AgentScribe · 本地同声字幕")
        title.setWordWrap(False)
        bar.addWidget(title)
        bar.addStretch()
        minimize = WindowButton(window, 'minimize')
        minimize.setToolTip("最小化")
        minimize.setAccessibleName('最小化')
        minimize.clicked.connect(window.showMinimized)
        self.maximize = WindowButton(window, 'maximize')
        self.maximize.setToolTip("最大化")
        self.maximize.setAccessibleName('最大化或还原')
        self.maximize.clicked.connect(self.toggle_maximized)
        close = WindowButton(window, 'close')
        close.setToolTip("关闭")
        close.setAccessibleName('关闭')
        close.clicked.connect(window.close)
        bar.addWidget(minimize)
        bar.addWidget(self.maximize)
        bar.addWidget(close)

    def toggle_maximized(self):
        if self.host.isMaximized():
            self.host.showNormal()
            self.maximize.setToolTip("最大化")
        else:
            self.host.showMaximized()
            self.maximize.setToolTip("还原")
        self.maximize.update()

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
        radius = float(WORKSPACE_RADIUS)
        path = QPainterPath()
        path.moveTo(self.width() - .5, radius)
        path.quadTo(self.width() - .5, .5, self.width() - radius, .5)
        path.lineTo(radius, 0.5)
        path.quadTo(0.5, 0.5, 0.5, radius)
        path.lineTo(0.5, self.height())
        path.lineTo(self.width(), self.height())
        path.closeSubpath()
        colors = theme_colors(QApplication.instance().property('appearance'))
        painter.fillPath(path, QColor(colors['surface']))
        edge = QPainterPath()
        edge.moveTo(self.width() - .5, radius)
        edge.quadTo(self.width() - .5, .5, self.width() - radius, .5)
        edge.lineTo(radius, 0.5)
        edge.quadTo(0.5, 0.5, 0.5, radius)
        edge.lineTo(0.5, self.height())
        painter.setPen(QPen(QColor(colors['border']), 1))
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
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(x, y), 2, 2)
    elif kind == 'chevron':
        painter.drawLine(6, 8, 10, 12)
        painter.drawLine(10, 12, 14, 8)
    elif kind == 'refresh':
        painter.drawArc(4, 4, 12, 12, 40*16, 280*16)
        painter.drawLine(15, 3, 15, 7)
        painter.drawLine(11, 7, 15, 7)
    elif kind == 'check':
        painter.drawLine(4, 10, 8, 14)
        painter.drawLine(8, 14, 16, 6)
    elif kind == 'system':
        painter.drawRoundedRect(3, 3, 14, 10, 2, 2)
        painter.drawLine(10, 13, 10, 17)
        painter.drawLine(6, 17, 14, 17)
    elif kind == 'input':
        painter.drawRoundedRect(7, 2, 6, 10, 3, 3)
        painter.drawArc(4, 5, 12, 10, 180*16, 180*16)
        painter.drawLine(10, 15, 10, 18)
        painter.drawLine(7, 18, 13, 18)
    elif kind == 'trash':
        painter.drawLine(3, 5, 17, 5)
        painter.drawLine(7, 3, 13, 3)
        painter.drawLine(5, 7, 6, 17)
        painter.drawLine(6, 17, 14, 17)
        painter.drawLine(14, 17, 15, 7)
        painter.drawLine(8, 8, 8, 14)
        painter.drawLine(12, 8, 12, 14)
    elif kind == 'play':
        path = QPainterPath()
        path.moveTo(7, 4)
        path.lineTo(16, 10)
        path.lineTo(7, 16)
        path.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(path)
    elif kind == 'pause':
        painter.drawLine(7, 4, 7, 16)
        painter.drawLine(13, 4, 13, 16)
    else:
        painter.drawRoundedRect(5, 3, 10, 14, 2, 2)
        painter.drawLine(8, 7, 12, 7)
        painter.drawLine(8, 10, 12, 10)
    painter.end()
    return QIcon(pixmap)


class CaptionCard(QFrame):
    def __init__(self, caption, translating, *, animate=False):
        super().__init__()
        self.setObjectName("captionRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 14, 4, 18)
        layout.setSpacing(9)
        self.meta = label("", "timestamp")
        self.source = CaptionText()
        self.target = CaptionText()
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
        self.pending.setText(('译文更新失败，请查看错误详情' if caption.error else '原文已更新，正在更新译文…')
                             if stale else '')
        self.pending.setToolTip(caption.error)
        self.pending.setVisible(self.translating and stale)


class Window(QMainWindow):

    def __init__(self, discover=True, library_root=None, prefs=None, library=None, runtime=None):
        super().__init__()
        if sys.platform == "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._backdrop_applied = False
        self._backdrop_attempted = False
        self._native_resize_applied = False
        if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("AgentScribe · 本地同声字幕")
        self.resize(1280, 840)
        self.setMinimumSize(640, 480)
        self.session = None
        self.runtime = runtime
        self.recording_lock = None
        self.last_error = ""
        self.recording_state = RecordingState.IDLE
        self.save_error = ''
        self.phase_started = time.monotonic()
        self.pipeline_state = {"音频": "未开始", "识别": "未加载", "翻译": "未加载"}
        self.captions = {}
        self.cards = {}
        self.closing = False
        self.asset_check = None
        self.missing_model_assets = None
        self.model_action = None
        self.model_prompt = None
        self.asset_check_timer = QTimer(self)
        self.asset_check_timer.setSingleShot(True)
        self.asset_check_timer.timeout.connect(self.check_model_assets)
        self.asset_check_generation = 0
        self.asset_check_closed = False
        self.startup_update_job = None
        self.background_checks = set()
        self.prefs = prefs if prefs is not None else QSettings("LinguaFlow", "LocalCaptions")
        self.overlay = Overlay(self.prefs)
        self.library = library if library is not None else self.open_recording_library(library_root)
        self.knowledge_client = KnowledgeClient(self)
        self.knowledge_panel = None
        self.session_dirty = False
        self.save_generation = 0
        self.caption_version = 0
        self.export_saver = RecordingSaver(self)
        self.export_saver.completed.connect(self.on_exported)
        self.recording_saver = RecordingSaver(self)
        self.recording_saver.completed.connect(self.on_saved)
        self.recording_saver.idle.connect(self.release_recording_lock)
        self.current_item = None
        self.folder_id = self.library.index["folders"][0]["id"]
        self.loading_saved = False
        self.caption_translation = True
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.timeout.connect(self.queue_session_save)
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
        self.recording_sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(180)
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
        settings_button = self.settings_button = QPushButton("  设置")
        settings_button.setObjectName("navigation")
        settings_button.setIcon(line_icon("settings"))
        settings_button.clicked.connect(self.open_settings)
        deleted_button = self.deleted_button = QPushButton("  最近删除")
        deleted_button.setObjectName("navigation")
        deleted_button.setIcon(line_icon('trash'))
        deleted_button.clicked.connect(self.show_deleted)
        sidebar_layout.addWidget(deleted_button)
        self.ui_update_button = QPushButton("↓  检查更新")
        self.ui_update_button.setObjectName("navigation")
        self.ui_update_button.clicked.connect(self.check_software_updates)
        sidebar_layout.addWidget(self.ui_update_button)
        self.ui_update_button.hide()
        sidebar_layout.addWidget(settings_button)
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
        hint = "Windows：选择“系统音频”录制电脑播放内容。"
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
        self.model_manager = ModelManager(self, compute_device=lambda: self.compute.currentData(),
                                         start_check=self.start_background_check)
        self.asr = QComboBox()
        self.asr.setEditable(True)
        self.asr.setMinimumContentsLength(18)
        self.asr.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.asr.addItems(["tiny", "base", "small", "medium", "large-v3", "turbo"])
        self.asr.setCurrentText("small")
        self.compute = QComboBox()
        device_labels = {'cpu': 'CPU（通用）', 'mlx': 'Apple GPU · Metal / MLX',
                         'cuda': 'NVIDIA GPU · 半精度'}
        for device in asr_devices():
            self.compute.addItem(device_labels[device], device)
        self.translation = QComboBox()
        self.translation.setEditable(True)
        self.translation.setMinimumContentsLength(18)
        self.translation.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.translation.addItems(["facebook/nllb-200-distilled-600M", "tencent/Hy-MT2-1.8B", "facebook/nllb-200-distilled-1.3B"])
        self.translate = Switch("启用翻译")
        self.translate.setChecked(True)
        form_outer.addWidget(self.translate)
        self.model_manager.finish_setup(asr=self.asr, translation=self.translation, compute=self.compute,
                                        choose_asr=lambda: self.choose_model(self.asr),
                                        choose_checkpoint=self.choose_checkpoint,
                                        choose_translation=lambda: self.choose_model(self.translation))
        self.model_manager.diagnostic.connect(self.diagnostics_append)
        form_outer.addWidget(label("当前引擎", "section"))
        self.model_summary = label("", "muted")
        form_outer.addWidget(self.model_summary)
        manage = QPushButton("打开模型管理")
        manage.setObjectName("secondary")
        manage.clicked.connect(self.manage_models)
        form_outer.addWidget(manage)
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
        toolbar.setContentsMargins(20, 5, 18, 5)
        self.workspace_title = label("新录音")
        self.workspace_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.workspace_title.setMinimumWidth(0)
        self.workspace_title.setWordWrap(False)
        self.workspace_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(self.workspace_title, 1)
        self.knowledge_button = QPushButton("课程资料与笔记 · Beta")
        self.knowledge_button.setObjectName("quiet")
        self.knowledge_button.hide()
        self.knowledge_button.clicked.connect(self.open_knowledge)
        toolbar.addWidget(self.knowledge_button)
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
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        self.scroll = CaptionScrollArea()
        self.scroll.viewport().installEventFilter(self)
        self.feed = QWidget()
        self.feed.setObjectName("feed")
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(12, 24, 12, 16)
        self.feed_layout.setSpacing(4)
        self.empty = label(
            "点击「新录音」开始。",
            "muted",
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(160)
        self.empty.setStyleSheet("font-size: 16px; color: #89898f;")
        self.feed_layout.addWidget(self.empty)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)
        content_layout.addWidget(self.scroll, 1)
        self.reduce_motion = Switch('减少动态效果')
        self.reduce_motion.toggled.connect(lambda value: QApplication.instance().setProperty('reduceMotion', value))
        self.reduce_motion.toggled.connect(self.scroll.content_changed)
        self.beta_features = Switch('体验 Beta 功能')
        menu.addSeparator()
        menu.addAction('移到最近删除…', self.delete_current)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(500)
        self.diagnostics.setMaximumHeight(160)
        self.diagnostics.hide()
        diagnostics_button.toggled.connect(self.diagnostics.setVisible)
        content_layout.addWidget(self.diagnostics)
        self.meter = AudioLevelMeter()
        self.pipeline = label("音频：未开始   /   识别：未加载   /   翻译：未加载", "muted")
        self.pipeline.hide()
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        self.meter.setTextVisible(False)
        self.meter.setToolTip('输入音量；暂停收音时归零')
        self.volume_caption = label('音频音量\n开始后显示', 'muted')
        self.volume_caption.setWordWrap(False)
        self.volume_caption.setStyleSheet('font-size: 11px;')
        self.pending_source_revision = None
        footer = self.control_island = FloatingIsland(self.scroll.viewport())
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(14, 12, 14, 12)
        footer_layout.setSpacing(8)
        input_row = self.input_row = QGridLayout()
        self.quick_device = QComboBox()
        self.quick_device.setAccessibleName('音频来源')
        self.quick_device.setPlaceholderText('选择系统音频或外部输入')
        self.quick_device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.quick_device.setMinimumContentsLength(12)
        self.quick_device.setMinimumWidth(0)
        self.quick_device.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.quick_device.setModel(self.device.model())
        self.quick_device.setCurrentIndex(self.device.currentIndex())
        self.quick_device.currentIndexChanged.connect(self.device.setCurrentIndex)
        self.device.currentIndexChanged.connect(self.quick_device.setCurrentIndex)
        self.quick_device.currentTextChanged.connect(self.quick_device.setToolTip)
        input_row.addWidget(self.quick_device, 0, 0)
        input_row.setColumnStretch(0, 1)
        self.refresh_source = QPushButton()
        self.refresh_source.setIcon(line_icon('refresh'))
        self.refresh_source.setFixedSize(30, 30)
        self.refresh_source.setAccessibleName('刷新音频来源')
        self.refresh_source.setObjectName('quiet')
        self.refresh_source.setToolTip('刷新音频设备列表')
        self.refresh_source.clicked.connect(self.refresh_devices)
        self.refresh_feedback = QTimer(self)
        self.refresh_feedback.setSingleShot(True)
        self.refresh_feedback.setInterval(1500)
        self.refresh_feedback.timeout.connect(self.reset_refresh_feedback)
        input_row.addWidget(self.refresh_source, 0, 2)
        footer_layout.addLayout(input_row)
        bottom = QHBoxLayout()
        footer_layout.addLayout(bottom)
        self.status = label("准备开始", "muted")
        self.status.setObjectName('status')
        self.status.setStyleSheet('font-size: 11px;')
        self.status.setMaximumHeight(36)
        self.status.hide()
        content_layout.insertWidget(0, self.status)
        transport_column = QVBoxLayout()
        transport_column.setSpacing(2)
        self.transport = QStackedWidget()
        self.transport.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.live_transport = QWidget()
        live_row = QHBoxLayout(self.live_transport)
        live_row.setContentsMargins(0, 0, 0, 0)
        live_row.addWidget(self.volume_caption)
        live_row.addWidget(self.meter, 1)
        live_row.addStretch()
        self.transport.addWidget(self.live_transport)
        transport_column.addWidget(self.transport)
        bottom.addLayout(transport_column, 1)
        self.start_button = QPushButton("开始聆听")
        self.start_button.setFixedWidth(98)
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("结束")
        self.stop_button.setToolTip('结束聆听并保存录音与字幕')
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
        playback_layout.setContentsMargins(0, 0, 0, 0)
        self.play_button = QPushButton()
        self.play_button.setIcon(line_icon('play'))
        self.play_button.setFixedSize(32, 32)
        self.play_button.setAccessibleName('播放录音')
        self.play_button.setToolTip('播放录音')
        self.play_button.setObjectName("quiet")
        self.play_button.clicked.connect(self.toggle_playback)
        playback_layout.addWidget(self.play_button)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName('录音播放进度')
        self.seek.setMinimumWidth(70)
        playback_layout.addWidget(self.seek, 1)
        self.play_time = label("00:00 / 00:00", "timestamp")
        self.play_time.setWordWrap(False)
        self.playback_duration_ms = 0
        playback_layout.addWidget(self.play_time)
        self.playback.hide()
        self.playback.setProperty('available', False)
        self.player = None
        self.transport.addWidget(self.playback)
        self.quick_language = QPushButton('输入与语言')
        self.quick_language.setObjectName('quiet')
        self.quick_language.setToolTip('更改原文和目标语言')
        self.language_popup = LanguagePopup(self.source, self.target, self.translate, self)
        self.language_popup.finished.connect(self.save)
        self.quick_language.clicked.connect(lambda: self.language_popup.show_at(
            self.quick_language, next_session=self.recording_state.active))
        self.quick_language.setMinimumWidth(0)
        self.quick_language.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        input_row.addWidget(self.quick_language, 0, 1)
        self.control_island.compactChanged.connect(self.arrange_input_controls)
        footer_layout.addWidget(self.pipeline)
        self.pipeline.setStyleSheet('font-size: 11px;')
        self.control_island.heightChanged.connect(self.update_caption_insets)
        self.control_island.heightChanged.connect(self.scroll.set_overlay_height)
        self.control_island.placement.start(0)
        self.update_transport()
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
        self.appearance = QComboBox()
        self.appearance.addItem("白色", "light")
        self.appearance.addItem("深色", "dark")
        self.settings_binding = SettingsBinding({
            pref.key: getattr(self, pref.key) if hasattr(self, pref.key) else getattr(self.model_manager, pref.key)
            for pref in PREFERENCES})
        self.restore()
        self.initial_model_selection = self.model_manager.preparation_selection()
        self.apply_appearance()
        self.appearance.currentIndexChanged.connect(self.apply_appearance)
        QApplication.instance().setProperty('reduceMotion', self.reduce_motion.isChecked())
        self.model_manager.backend.currentIndexChanged.connect(self.sync_asr_device)
        self.compute.currentIndexChanged.connect(self.select_asr_device)
        self.update_model_summary()
        self.settings_workspace = SettingsWorkspace(WorkspaceFrame,
            storage_root=self.library.root, manager=self.model_manager,
            controls={key: getattr(self, key) for key in
                      ('device', 'source', 'target', 'translate', 'reduce_motion', 'beta_features', 'appearance', 'compute')})
        self.beta_features.toggled.connect(self.apply_beta_features)
        self.apply_beta_features(self.beta_features.isChecked(), persist=False)
        self.settings_panel = self.settings_workspace.listening_page
        self.settings_workspace.model_settings_changed.connect(self.save)
        self.device.currentIndexChanged.connect(self.save)
        self.device.currentIndexChanged.connect(self.change_audio_source)
        for signal, action in (
                (self.settings_workspace.back_requested, self.leave_settings),
                (self.settings_workspace.open_storage_requested, self.reveal_library),
                (self.settings_workspace.choose_storage_requested, self.choose_library),
                (self.settings_workspace.deleted_requested, self.show_deleted),
                (self.settings_workspace.refresh_devices_requested, self.refresh_devices)):
            signal.connect(action)
        self.settings_workspace.prepare_models_requested.connect(self.prepare_recommended_models)
        self.settings_workspace.model_browser.start_check = self.start_background_check
        self.settings_workspace.model_browser.changed.connect(self.check_model_assets)
        self.model_manager.selection_changed.connect(lambda *_: self.asset_check_timer.start(100))
        self.pages.addWidget(self.settings_workspace)
        for pref in PREFERENCES:
            control = self.settings_binding.controls[pref.key]
            signal = (control.toggled if pref.kind == 'bool' else
                      control.valueChanged if pref.kind == 'float' else control.currentTextChanged)
            signal.connect(self.save_next_settings)
        self.source.currentTextChanged.connect(self.update_quick_settings)
        self.target.currentTextChanged.connect(self.update_quick_settings)
        self.translate.toggled.connect(self.update_quick_settings)
        self.model_manager.backend.currentIndexChanged.connect(self.update_quick_settings)
        self.update_quick_settings()
        self.translate.setText("")
        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self.update_activity)
        self.activity_timer.start(1000)
        self.knowledge_client.closing_changed.connect(self.on_knowledge_closing)
        if discover:
            QTimer.singleShot(0, self.refresh_devices)
        self.model_manager.preparation_changed.connect(self.refresh_model_assets_after_preparation)
        QTimer.singleShot(0, self.check_model_assets)
        if sys.platform == 'darwin':
            self.setup_application_menu()

    def setup_application_menu(self):
        """Expose version and update entry points in the native macOS app menu."""
        self.menuBar().setNativeMenuBar(True)
        menu = self.menuBar().addMenu('AgentScribe')
        self.about_action = QAction('关于 AgentScribe', self)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self.about_action.triggered.connect(self.show_about)
        menu.addAction(self.about_action)
        self.version_action = QAction('版本与更新…', self)
        self.version_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
        self.version_action.triggered.connect(lambda: self.open_settings('运行环境'))
        menu.addAction(self.version_action)
        self.update_action = QAction('检查更新…', self)
        self.update_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
        self.update_action.triggered.connect(self.check_software_updates)
        menu.addAction(self.update_action)
        menu.addSeparator()
        quit_action = QAction('退出 AgentScribe', self)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

    def show_about(self):
        if not hasattr(self, 'about_dialog'):
            self.about_dialog = QMessageBox(self)
            self.about_dialog.setWindowTitle('关于 AgentScribe')
            self.about_dialog.setText('AgentScribe · 本地同声字幕')
            self.about_dialog.setInformativeText(f'版本 {__version__}\n本地语音识别、字幕与翻译。')
            self.about_dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        self.about_dialog.open()

    def apply_appearance(self):
        app = QApplication.instance()
        mode = self.appearance.currentData() or 'light'
        app.setProperty('appearance', mode)
        from PySide6.QtGui import QPalette
        palette = QPalette()
        colors = ("#ffffff", "#242428", "#ededf0", "#4d4d56") if mode == "light" else ("#222224", "#f1f1f3", "#3e4149", "#f1f1f3")
        for role, color in ((QPalette.ColorRole.Window, colors[0]), (QPalette.ColorRole.Base, colors[0]),
                            (QPalette.ColorRole.Text, colors[1]), (QPalette.ColorRole.WindowText, colors[1]),
                            (QPalette.ColorRole.ButtonText, colors[1]), (QPalette.ColorRole.Button, colors[0]),
                            (QPalette.ColorRole.Highlight, colors[2]), (QPalette.ColorRole.HighlightedText, colors[3])):
            palette.setColor(role, QColor(color))
        app.setPalette(palette)
        app.setStyleSheet(appearance_style(STYLE, mode))
        for button, kind in ((self.new_button, 'new'), (self.settings_button, 'settings'),
                             (self.deleted_button, 'trash'),
                             (self.quick_language, 'chevron'),
                             (self.refresh_source, 'check' if self.refresh_feedback.isActive() else 'refresh')):
            button.setIcon(line_icon(kind, theme_colors(mode)['muted']))
        for index in range(self.device.count()):
            data = self.device.itemData(index)
            if data:
                self.device.setItemIcon(index, line_icon('system' if data[1] else 'input', colors[1]))
        for widget in self.findChildren(QWidget):
            widget.update()
        self.prefs.setValue('appearance', mode)
        self.update_playback_button()
        self.centralWidget().update()
        for frame in self.findChildren(WorkspaceFrame):
            frame.update()

    def check_software_updates(self):
        self.open_settings('运行环境')
        self.model_manager.check_updates()

    def start_background_check(self, module, callback, *arguments):
        from .ui_checks import BackgroundCheck
        check = BackgroundCheck(module, arguments, self)
        self.background_checks.add(check)
        check.result.connect(callback)
        def finished():
            self.background_checks.discard(check)
            check.deleteLater()
            if self.asset_check_closed:
                QTimer.singleShot(0, self.close)
        check.completed.connect(finished)
        check.begin()
        return check

    def check_startup_updates(self):
        """Keep dependency imports and Python GC out of the Qt process's workers."""
        if self.asset_check_closed or self.startup_update_job is not None:
            return
        self.startup_update_job = self.start_background_check(
            'linguaflow.updates', self.on_startup_update_checked)

    def on_startup_update_checked(self, result):
        if self.asset_check_closed or not isinstance(result, dict) or result.get('kind') not in ('package', 'source'):
            return
        from .updates import trusted_release_url
        if not trusted_release_url(result.get('url')):
            return
        self.model_manager.show_update(result, respect_cancel=False)
        self.model_manager.version_label.setText(f'当前版本：{__version__} · 可用新版：{result["version"]}')
        self.update_dialog = QMessageBox(self)
        self.ui_update_button.setText('↓  有新版本')
        self.ui_update_button.show()
        self.update_dialog.setWindowTitle('AgentScribe 有新版本')
        self.update_dialog.setText(f'发现新版 {result["version"]}，建议更新。')
        self.update_dialog.setInformativeText(result['message'])
        view = self.update_dialog.addButton('查看发行页', QMessageBox.ButtonRole.AcceptRole)
        self.update_dialog.addButton('稍后', QMessageBox.ButtonRole.RejectRole)
        self.update_dialog.buttonClicked.connect(
            lambda button: self.model_manager.update_link.click() if button is view else None)
        self.update_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.update_dialog.show()

    def refresh_model_assets_after_preparation(self, active):
        if active:
            self.model_action = None
        self.asset_check_generation += 1
        if not active:
            self.check_model_assets()

    def check_model_assets(self):
        if self.asset_check_closed or self.model_manager.preparing:
            return
        if self.asset_check is not None and self.asset_check in self.background_checks:
            self.asset_check_timer.start(200)
            return
        self.asset_check_generation += 1
        generation = self.asset_check_generation
        selection = self.preparation_selection()
        translating = self.translate.isChecked()
        def checked(value):
            if selection != self.preparation_selection() or translating != self.translate.isChecked():
                self.check_model_assets()
                return
            missing = value if isinstance(value, list) else ['本地模型检查未完成，可在模型管理中重新检查']
            self.on_model_assets_checked(generation, missing)
        arguments = ['--check', '--selection', json.dumps(selection, ensure_ascii=False)]
        if not translating:
            arguments += ['--only', 'asr']
        self.asset_check = self.start_background_check('linguaflow.recommended_prepare', checked, *arguments)

    def on_model_assets_checked(self, generation, missing):
        if self.asset_check_closed or generation != self.asset_check_generation:
            return
        self.missing_model_assets = tuple(missing)
        action, self.model_action = self.model_action, None
        if not missing:
            if self.model_prompt is not None:
                self.model_prompt.close()
            if action == 'start':
                self.start(models_checked=True)
            elif action and not self.save_error:
                self.status.setText('模型已就绪 · 可以开始聆听')
        elif action:
            if not self.save_error:
                self.status.setText('需要准备所选模型')
            self.prompt_missing_models()

    def check_models_for_action(self, action):
        """Only explicit recording actions request a prompt; checks never download."""
        if self.model_manager.preparing:
            return
        self.model_action = action
        if not self.save_error:
            self.status.setText('正在检查所选模型…')
        self.check_model_assets()

    def prompt_missing_models(self):
        if (self.asset_check_closed or not self.missing_model_assets or not self.isVisible()
                or self.recording_state.active or self.model_manager.preparing):
            return
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            QTimer.singleShot(300, self.prompt_missing_models)
            return
        if self.model_prompt is not None:
            self.model_prompt.close()
        dialog = self.model_prompt = SurfaceDialog('本地模型需要准备',
            '缺少所选模型文件：' + '、'.join(self.missing_model_assets), self)
        dialog.body.addWidget(label('前往“设置 → 模型管理”下载或导入模型。关闭提示后仍可在那里操作；已有录音可以继续查看和回听。', 'muted'))
        later = QPushButton('稍后')
        later.clicked.connect(dialog.close)
        manage = QPushButton('前往模型管理')
        manage.clicked.connect(lambda: (dialog.close(), self.open_settings('模型管理')))
        download = QPushButton('下载所选模型')
        download.setObjectName('primary')
        download.clicked.connect(lambda: (dialog.close(), self.open_settings('模型管理'),
                                          self.prepare_recommended_models(only=None if self.translate.isChecked() else 'asr')))
        dialog.actions.addStretch()
        dialog.actions.addWidget(later)
        dialog.actions.addWidget(manage)
        dialog.actions.addWidget(download)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.show()

    def open_settings(self, category="常规"):
        category = category if isinstance(category, str) else "常规"
        if category in ('识别模型', '翻译模型'):
            category = '模型管理'
        self.settings_workspace.search.clear()
        index = self.settings_workspace.categories.index(category)
        self.settings_workspace.navigation.setCurrentRow(index)
        self.settings_workspace.select(index)
        self.pages.setCurrentIndex(1)

    def leave_settings(self):
        self.save()
        self.update_model_summary()
        self.pages.setCurrentIndex(0)

    def return_to_recording(self):
        if self.pages.currentIndex() == 1 and QApplication.activeModalWidget() is None:
            self.leave_settings()

    def update_quick_settings(self):
        language = self.source.currentText()
        self.quick_language.setText(language + (' → ' + self.target.currentText()
                                    if self.translate.isChecked() else ' · 仅原文'))

    def open_recording_library(self, explicit_root):
        def choose_directory(root, error):
            QMessageBox.warning(self, "请选择录音保存位置",
                f"默认目录无法使用：{root}\n{error}\n请选择一个可写目录。")
            return QFileDialog.getExistingDirectory(self, "选择录音保存目录")

        def migration_failed(root, error):
            QMessageBox.warning(self, "旧录音仍保留在原位置",
                f"迁移未完成，可稍后重试。\n{root}\n{error}")

        from .runtime_paths import resource_root
        install_root = resource_root()
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

    def queue_session_save(self, state=None):
        if not self.current_item or self.loading_saved or (not self.session_dirty and state is None):
            return
        token = (self.save_generation, self.current_item['id'])
        self.recording_saver.submit(self.library.save, token, self.caption_version,
                                   self.current_item, self.captions.values(), state)

    def on_saved(self, snapshot, state, error):
        if not self.current_item or snapshot.token != (self.save_generation, self.current_item['id']):
            return
        if error:
            self.session_dirty = True
            self.save_error = error
            self.update_activity()
            return
        self.current_item['state'] = state
        if self.knowledge_client.identifier == self.current_item['id']:
            self.knowledge_client.saved(snapshot.captions, final=state in ('complete', 'incomplete'))
        if snapshot.revision == self.caption_version:
            self.session_dirty = False
            self.save_error = ''
            self.status.setToolTip('')
            if not self.recording_state.active and not self.last_error:
                self.status.setText('已保存')
            self.update_activity()

    def persist_session(self, state=None):
        self.autosave.stop()
        if self.recording_saver.waiting:
            return False
        self.queue_session_save(state)
        if not self.recording_saver.flush():
            self.status.setText("保存仍在进行，请稍后重试；字幕已保留在界面中")
            return False
        return not self.session_dirty

    def release_recording_lock(self):
        if (self.recording_lock and self.session is None and not self.recording_state.active
                and not self.recording_saver.busy):
            self.recording_lock.unlock()
            self.recording_lock = None

    def release_playback(self):
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.playback.setProperty('available', False)
        self.playback_duration_ms = 0
        self.seek.setRange(0, 0)
        self.playback_position(0)
        self.update_transport()

    def reset_recording_view(self):
        self.model_action = None
        self.close_knowledge()
        self.release_playback()
        self.autosave.stop()
        self.current_item = None
        self.session_dirty = False
        self.save_error = ''
        self.status.setToolTip('')
        self.update_activity()
        self.clear_captions()
        self.workspace_title.setText("新录音")
        self.empty.setText("点击「新录音」开始。")
        self.export_button.setEnabled(False)

    def new_recording(self, checked=False, *, folder_id=None, name=None, check_models=True):
        if not self.can_edit_library():
            return False
        self.library.refresh()
        folders = self.library.index['folders']
        folder_id = folder_id or self.folder_id or (folders[0]['id'] if folders else None)
        if name is None:
            dialog = RecordingDialog(self.library, folder_id, self)
            if not dialog.exec():
                return False
            name, folder_id = dialog.name.text(), dialog.folder.currentData()
        try:
            if not self.library.index['folders']:
                folder_id = self.library.folder('我的录音')['id']
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
        if check_models:
            self.check_models_for_action('new')
        return True

    def open_library_item(self, row, column):
        if not self.can_edit_library():
            return
        self.model_action = None
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
        self.attach_knowledge()
        self.prepare_playback()

    def open_knowledge(self):
        if not self.beta_features.isChecked():
            return
        if not self.current_item:
            QMessageBox.information(self, "选择录音", "请先新建或选择一段录音，再关联课程资料。")
            return
        if self.knowledge_panel is None:
            self.knowledge_panel = KnowledgePanel(self.knowledge_client, self.cancel_knowledge, self.persist_session, self)
            self.knowledge_panel.seekRequested.connect(self.seek_knowledge_source)
        self.knowledge_panel.set_recording(self.recording_state.active)
        self.knowledge_panel.show()
        self.knowledge_panel.raise_()
        self.attach_knowledge(force=True)

    def attach_knowledge(self, force=False):
        if not self.beta_features.isChecked() or not self.current_item:
            return
        try:
            if force or read_manifest(self.library, self.current_item['id'])['notes_cloud']:
                if self.knowledge_panel and self.knowledge_client.identifier != self.current_item['id']:
                    self.knowledge_panel.reset()
                self.knowledge_client.open(self.library, self.current_item, self.captions.values())
        except (OSError, ValueError) as exc:
            self.status.setText(f"课程资料未就绪：{exc}")

    def close_knowledge(self):
        ready = self.knowledge_client.close()
        if self.knowledge_panel:
            self.knowledge_panel.hide()
            self.knowledge_panel.reset()
        return ready

    def on_knowledge_closing(self, closing):
        for control in (self.library_tree, self.new_button, self.folder_button):
            control.setEnabled(not closing and not self.recording_state.active)
        if closing:
            self.status.setText('课程后台正在释放文件，完成后继续当前操作。')

    def apply_beta_features(self, enabled, *, persist=True):
        """Gate all course-agent entry points and stop its owned process when opting out."""
        self.knowledge_button.setVisible(enabled)
        self.model_manager.set_beta_enabled(enabled)
        if not enabled:
            self.close_knowledge()
        if persist:
            self.save()

    def cancel_knowledge(self):
        # API calls are cancellable in the worker; a blocked parser requires owned-process termination.
        if self.knowledge_panel and self.knowledge_panel.busy:
            self.knowledge_client.send('cancel')
            if self.knowledge_panel.operation == 'import':
                self.close_knowledge()
                self.status.setText('课件导入已取消，已保存内容保留。')

    def seek_knowledge_source(self, seconds):
        if self.player and not self.recording_state.active:
            self.player.setPosition(int(seconds * 1000))
        self.status.setText(f"笔记引用：录音约 {seconds:.1f} 秒")

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
        if self.knowledge_client.closing:
            self.status.setText('课程后台正在释放文件，请稍后操作；界面仍可使用。')
            return False
        if self.session is not None or not self.persist_session():
            return False
        if not self.close_knowledge():
            self.status.setText(self.knowledge_client.close_error or '课程后台尚未退出，请稍后重试。')
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
        self.settings_workspace.set_storage_root(library.root)
        self.refresh_library()
        self.status.setText("已切换保存目录 · 旧录音仍保留在原目录，可切换回去查看")

    def prepare_playback(self):
        if self.player:
            self.player.stop()
        path = self.library.directory(self.current_item["id"]) / "录音.wav" if self.current_item else None
        available = bool(path and path.exists() and path.stat().st_size > 44)
        self.playback.setProperty('available', available)
        self.update_transport()
        if available:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            if self.player is None:
                self.player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.player.setAudioOutput(self.audio_output)
                self.player.durationChanged.connect(self.playback_duration)
                self.player.positionChanged.connect(self.playback_position)
                self.seek.sliderMoved.connect(self.player.setPosition)
                self.player.playbackStateChanged.connect(lambda *_: self.update_playback_button())
                self.player.errorOccurred.connect(lambda *_: QMessageBox.warning(
                    self, '录音无法播放', self.player.errorString()))
            self.player.setSource(QUrl.fromLocalFile(str(path)))

    def update_transport(self):
        active = self.recording_state.active
        replay = not active and bool(self.playback.property('available'))
        self.transport.setCurrentWidget(self.playback if replay else self.live_transport)
        self.meter.setVisible(not replay)
        self.transport.setVisible(True)
        self.start_button.setVisible(not active and not replay)
        self.quick_device.setVisible(not replay)
        self.quick_language.setVisible(not replay)
        self.refresh_source.setVisible(not replay)
        self.update_volume_caption()

    def update_volume_caption(self):
        source = self.quick_device.currentData()
        category = ('系统音频' if source[1] else '外部输入') if source else '音频音量'
        state = self.recording_state
        detail = ('收尾中' if state is RecordingState.STOPPING else
                  '继续后切换' if self.pending_source_revision is not None and state is RecordingState.PAUSED else
                  '正在切换…' if self.pending_source_revision is not None else
                  '已暂停' if state is RecordingState.PAUSED else
                  '实时音量' if state is RecordingState.LISTENING else
                  '准备收音' if state.active else '开始后显示')
        self.volume_caption.setText(f'{category}\n{detail}')

    def change_audio_source(self):
        source = self.device.currentData()
        if self.session is not None and self.recording_state.active and source:
            self.pending_source_revision = self.session.switch_source(*source)
            self.meter.setValue(0)
        self.update_volume_caption()

    def on_source_changed(self, revision):
        if self.sender() is not None and self.sender() is not self.session:
            return
        if revision == self.pending_source_revision:
            self.pending_source_revision = None
            self.update_volume_caption()

    def on_level(self, value):
        if self.sender() is not None and self.sender() is not self.session:
            return
        # Queued levels from the previous source must not light up its replacement.
        if self.recording_state is RecordingState.LISTENING and self.pending_source_revision is None:
            self.meter.set_rms(value)
        else:
            self.meter.setValue(0)

    def arrange_input_controls(self, compact):
        self.input_row.addWidget(self.quick_device, 0, 0, 1, 3 if compact else 1)
        self.input_row.addWidget(self.quick_language, 1 if compact else 0, 0 if compact else 1,
                                 1, 2 if compact else 1)
        self.input_row.addWidget(self.refresh_source, 1 if compact else 0, 2)

    @staticmethod
    def playback_clock(milliseconds):
        seconds = max(0, milliseconds // 1000)
        return (f'{seconds//3600}:{seconds//60%60:02}:{seconds%60:02}' if seconds >= 3600 else
                f'{seconds//60:02}:{seconds%60:02}')

    def playback_duration(self, milliseconds):
        self.playback_duration_ms = max(0, milliseconds)
        self.seek.setRange(0, self.playback_duration_ms)
        self.playback_position(self.seek.value())

    def update_playback_button(self):
        playing = self.player is not None and self.player.playbackState().name == 'PlayingState'
        title = '暂停播放' if playing else '播放录音'
        self.play_button.setIcon(line_icon('pause' if playing else 'play',
                                         theme_colors(QApplication.instance().property('appearance'))['text']))
        self.play_button.setAccessibleName(title)
        self.play_button.setToolTip(title)

    def playback_position(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.play_time.setText(self.playback_clock(position) + ' / ' + self.playback_clock(self.playback_duration_ms))

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

    def sync_asr_device(self):
        manager = self.model_manager
        mlx = manager.backend.currentData() == 'qwen3-mlx'
        device, model = normalize_asr_selection(manager.backend.currentData(), self.compute.currentData(),
                                               manager.qwen_model.currentText())
        self.compute.setCurrentIndex(data_index(self.compute, device))
        manager.qwen_model.setCurrentText(model)
        self.compute.setEnabled(not mlx)

    def select_asr_device(self):
        if self.compute.currentData() == 'mlx':
            manager = self.model_manager
            manager.backend.setCurrentIndex(data_index(manager.backend, 'qwen3-mlx'))

    def use_recommended_profile(self):
        selection = recommended_selection()
        manager = self.model_manager
        manager.apply_selection(selection)
        self.sync_asr_device()
        self.translate.setChecked(True)
        manager.status.setText('已选择推荐模型；下一次开始聆听时生效。')

    use_mac_profile = use_recommended_profile  # Compatibility for the previous action name.

    def preparation_selection(self):
        selection = self.model_manager.preparation_selection()
        defaults = recommended_selection()
        # Preserve the existing first-use Apple preset, without overriding user selections.
        if (defaults['backend'] == 'qwen3-mlx' and selection == self.initial_model_selection
                and not any(self.prefs.contains(key) for key in ('backend', 'asr', 'qwen_model', 'translation',
                                                                'translation_engine', 'llama_model',
                                                                'translation_device', 'compute', 'translate'))):
            return defaults
        return selection

    def prepare_recommended_models(self, *, only=None):
        if self.preparation_selection() != self.model_manager.preparation_selection():
            self.use_recommended_profile()
        self.model_manager.prepare_selected(self.model_manager.preparation_selection(), only=only)

    def diagnostics_append(self, message):
        self.diagnostics.appendPlainText(message)

    def update_pipeline_visibility(self):
        active = self.recording_state.active
        attention = any(any(word in value for word in ('加载中', '准备中', '失败'))
                        for value in self.pipeline_state.values())
        self.pipeline.setVisible(active and attention)

    def save_next_settings(self):
        if self.recording_state.active:
            self.save()

    def manage_models(self):
        self.open_settings("识别模型")

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
        values.update(audio_device=self.device.currentData())
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
            # The two views share a model. Block both during its reset so a
            # transient first row cannot overwrite the selected microphone/prefs.
            with QSignalBlocker(self.device), QSignalBlocker(self.quick_device):
                self.device.clear()
                for device in devices:
                    category = '系统音频' if device.loopback else '外部输入'
                    # Keep category visible even when a long device name is elided.
                    name = device.name.split(' · ', 1)[-1]
                    color = theme_colors(QApplication.instance().property('appearance'))['text']
                    self.device.addItem(line_icon('system' if device.loopback else 'input', color),
                                        f'{category} · {name}', (device.id, device.loopback))
                self.device.setCurrentIndex(data_index(self.device, previous) if previous else (0 if devices else -1))
                self.quick_device.setCurrentIndex(self.device.currentIndex())
            self.save()
            self.update_volume_caption()
            self.quick_device.setToolTip(self.device.currentText() or '音频来源不可用，请连接设备后刷新。')
            if previous and self.device.currentIndex() < 0:
                QMessageBox.warning(self, '音频来源不可用', '上次的音频设备不可用，请重新选择系统音频或外部输入。')
                return
            if not devices:
                QMessageBox.warning(self, '没有音频来源', '未发现录音设备，请连接设备并检查麦克风权限。')
                return
            self.refresh_source.setIcon(line_icon('check', theme_colors(QApplication.instance().property('appearance'))['text']))
            self.refresh_source.setToolTip(f'已刷新 · 找到 {len(devices)} 个音频来源')
            self.refresh_feedback.start()
        except Exception as exc:
            self.status.setText(f"无法读取音频设备：{exc}")
            QMessageBox.warning(self, '无法读取音频设备', str(exc))

    def reset_refresh_feedback(self):
        self.refresh_source.setIcon(line_icon('refresh', theme_colors(QApplication.instance().property('appearance'))['muted']))
        self.refresh_source.setToolTip('刷新音频设备列表')

    def start(self, *, models_checked=False):
        if self.session is not None:
            return
        if reason := self.model_manager.start_block_reason():
            QMessageBox.information(self, *reason)
            return
        if not models_checked:
            self.check_models_for_action('start')
            return
        device = self.quick_device.currentData()
        if device is None:
            QMessageBox.warning(self, "没有音频来源", "请连接录音设备并刷新列表。")
            return
        from .inference_startup import start_problem
        # The start action belongs to the recording page: freeze exactly the
        # source visible beside it, rather than reading a hidden settings view.
        settings = self.settings_binding.session_settings(device)
        if reason := start_problem(settings):
            QMessageBox.warning(self, *reason)
            return
        if not self.current_item or self.current_item["state"] != "draft":
            if not self.new_recording(check_models=False):
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
        self.empty.setText("正在准备模型…\n准备好后自动开始录音。")
        if self.beta_features.isChecked() and settings.backend in ('qwen3-streaming', 'qwen3-mlx'):
            try:
                context = session_context(self.library, self.current_item['id'])
                settings = replace(settings, asr_context=context)
            except (OSError, ValueError) as exc:
                self.on_failure(f"课程术语无效：{exc}")
                return
        if self.knowledge_client.identifier == self.current_item['id']:
            if not self.knowledge_client.close():
                self.on_status('课程后台尚未退出，请稍后开始聆听。')
                return
            self.attach_knowledge(force=True)
        else:
            self.attach_knowledge()
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
                self._finish_session(self.session)
            else:
                self.persist_session('incomplete')
                self.recording_lock.unlock()
                self.recording_lock = None
                self.set_recording_state(RecordingState.IDLE)

    def set_recording_state(self, state):
        self.recording_state = state
        if self.knowledge_panel:
            self.knowledge_panel.set_recording(state.active)
        self.model_manager.set_session_active(state.active)
        for control in (self.library_tree, self.new_button, self.folder_button):
            control.setEnabled(not state.active)
        source_enabled = state in (RecordingState.IDLE, RecordingState.LISTENING, RecordingState.PAUSED)
        for control in (self.device, self.quick_device, self.refresh_source):
            control.setEnabled(source_enabled)
        if state is RecordingState.IDLE:
            self.pending_source_revision = None
        self.start_button.setEnabled(not state.active)
        self.start_button.setText(state.value)
        self.stop_button.setEnabled(state.can_stop)
        self.stop_button.setVisible(state.active)
        self.pause_button.setVisible(state.active)
        self.pause_button.setEnabled(state.can_pause and not self.last_error)
        self.pause_button.setText("继续录音" if state is RecordingState.PAUSED else "暂停")
        self.start_button.setVisible(not state.active)
        self.update_transport()
        self.export_button.setEnabled(not state.active and any(c.final and c.source for c in self.captions.values()))
        self.update_pipeline_visibility()
        reason = '正在聆听，请先停止录音再切换或整理文件。' if state.active else ''
        for control in (self.library_tree, self.new_button, self.folder_button):
            control.setToolTip(reason)
        if not state.active:
            self.folder_button.setToolTip('新建文件夹')
        self.quick_device.setToolTip(self.device.currentText() + '\n系统音频：电脑播放的声音；外部输入：麦克风或虚拟输入。\n录音时可切换，暂停时切换将在继续后生效。')

    def launch_session(self, settings):
        self.session = Session(settings, self, recording_path=
                               self.library.directory(self.current_item["id"]) / "录音.wav", runtime=self.runtime)
        self.session.status.connect(self.on_status)
        self.session.stage.connect(self.on_stage)
        self.session.ready.connect(self.on_ready)
        self.session.paused.connect(self.on_paused)
        self.session.caption.connect(self.on_caption)
        self.session.level.connect(self.on_level)
        self.session.source_changed.connect(self.on_source_changed)
        self.session.failure.connect(self.on_failure)
        self.session.finished.connect(self.on_finished)
        self.session.start()

    def on_stage(self, name, state):
        self.pipeline_state[name] = state
        self.pipeline.setText(
            "   /   ".join(f"{name}：{value}" for name, value in self.pipeline_state.items())
        )
        self.update_pipeline_visibility()
        if name == '音频' and self.recording_state is RecordingState.LISTENING and not self.captions:
            if state.startswith('输入持续为零'):
                self.empty.setText('没有收到声音。\n请检查所选音频来源、静音和麦克风权限。')
            elif state.startswith('已收到声音'):
                self.empty.setText('正在聆听…')

    def on_status(self, message):
        self.diagnostics.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)
        if self.last_error:
            return
        # Optional Whisper advice is irrelevant to the active Qwen backend.
        if (message.startswith('MLX Whisper not found') and self.session is not None
                and self.session.settings.backend.startswith('qwen3-')):
            return
        self.phase_started = time.monotonic()
        if not self.save_error:
            self.status.setToolTip(message)
        self.update_activity()

    def update_activity(self):
        self.status.setVisible(bool(self.save_error or self.last_error))
        if self.status.property('saveError') != bool(self.save_error):
            self.status.setProperty('saveError', bool(self.save_error))
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        if self.save_error:
            self.status.setText('自动保存失败 · 字幕仍保留，请检查保存位置')
            self.status.setToolTip(self.save_error)
        elif self.recording_state.active and not self.last_error:
            elapsed = int(time.monotonic() - self.phase_started)
            self.status.setText(self.recording_state.status(elapsed))

    def on_ready(self):
        if self.last_error:
            return
        if self.recording_state is not RecordingState.STARTING:
            return
        self.set_recording_state(RecordingState.LISTENING)
        self.on_stage("会话", "聆听中")
        self.on_status("识别已就绪，正在聆听；翻译模型独立加载。" if self.caption_translation
                       else "识别已就绪，正在聆听。")
        self.empty.setText("正在聆听…")

    def clear_captions(self):
        self.save_generation += 1
        self.caption_version = 0
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
        self.update_activity()
        self.diagnostics.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)
        self.diagnostics.show()
        if not self.captions:
            self.empty.setText(message)

    @Slot()
    def on_finished(self):
        finished_session = self.session
        sender = self.sender()
        if finished_session is None or (sender is not None and sender is not finished_session):
            return
        self.set_recording_state(RecordingState.STOPPING)
        # Leave finished.emit() before starting the save worker or entering
        # its nested wait. Keep the session identity across the queued callback.
        QTimer.singleShot(0, lambda: self._finish_session(finished_session))

    def _finish_session(self, finished_session):
        if self.session is not finished_session:
            return
        if self.caption_translation:
            for caption in list(self.captions.values()):
                if caption.final and (not caption.translation or caption.translation_phase == 'initial') and not caption.error:
                    self.on_caption(replace(caption, error="会话已结束，此条翻译未完成"))
        self.session = None
        self.set_recording_state(RecordingState.STOPPING)
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
        # The sender's emission has returned; the saver owns any timed-out job.
        finished_session.deleteLater()
        self.set_recording_state(RecordingState.IDLE)
        self.release_recording_lock()
        self.refresh_library()
        self.prepare_playback()
        self.meter.setValue(0)
        self.status.setText(self.last_error or ("已取消 · 录音尚未开始" if state == "draft" and saved else
                            "录音已保存 · 部分翻译未完成" if saved and translation_incomplete else
                            "已保存录音与定稿" if saved else "保存失败，请导出字幕备份"))
        self.on_stage("会话", "失败，详见诊断" if self.last_error else "已结束")
        if self.closing:
            self.close()
        elif self.runtime is not None:
            self.runtime.prepare()

    def on_caption(self, caption):
        previous = self.captions.get(caption.id)
        if previous and (caption.revision < previous.revision or
                         (caption.revision == previous.revision and caption.source != previous.source)):
            return
        if self.current_item and not self.loading_saved:
            self.session_dirty = True
            self.caption_version += 1
            if self.knowledge_client.identifier == self.current_item['id']:
                self.knowledge_client.observe(caption)
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
                self.overlay.update_caption(self.captions[max(self.captions)],
                    self.caption_translation if self.recording_state.active else self.translate.isChecked())
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
            self.cards[caption.id].update_caption(caption, animate=not self.loading_saved)
        elif caption.id >= max(self.captions) - 199:
            card = CaptionCard(caption, self.caption_translation, animate=not self.loading_saved)
            self.cards[caption.id] = card
            self.feed_layout.insertWidget(self.feed_layout.count() - 1, card)
            # Bound Qt widget count while retaining the complete export in memory.
            if len(self.cards) > 200:
                old = self.cards.pop(min(self.cards))
                old.hide()
                self.feed_layout.removeWidget(old)
                old.deleteLater()
        if caption.id == max(self.captions):
            self.overlay.update_caption(caption, self.caption_translation, animate=not self.loading_saved)
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
        from .recording_export import FORMATS, export_target, write_export
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出录音定稿", "字幕", ";;".join(label for label, _ in FORMATS.values()))
        if path:
            target, kind = export_target(path, selected_filter)
            # The native dialog confirms the entered name; confirm again only if
            # adding a missing suffix identifies a different existing file.
            if target != Path(path) and target.exists():
                answer = QMessageBox.question(self, "覆盖导出文件", f"{target.name} 已存在，是否替换？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            # Freeze the captions through the existing owned saver; IO/formatting run off the UI thread.
            captions = [self.captions[k] for k in sorted(self.captions)]
            self.export_saver.submit(write_export, (0, str(target)), self.caption_version,
                                     dict(path=str(target), format=kind, state='exported'), captions)
            self.status.setText('正在导出录音定稿…')

    def on_exported(self, snapshot, state, error):
        if error:
            QMessageBox.warning(self, "导出失败", error)
        else:
            self.status.setText(f"已导出录音定稿：{snapshot.item['path']}")

    def update_caption_insets(self, *_):
        width = self.scroll.viewport().width()
        margin = max(20, (width-900)//2) + 12
        self.feed_layout.setContentsMargins(margin, 24, margin, self.control_island.height()+46)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Resize and hasattr(self, "workspace_content")
                and watched is self.workspace_content):
            self.update_caption_insets()
        if (event.type() == QEvent.Type.Resize and hasattr(self, 'control_island')
                and watched is self.scroll.viewport()):
            self.update_caption_insets()
        if (event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and watched.window() is self
                and start_edge_resize(self.windowHandle(), self.mapFromGlobal(event.globalPosition().toPoint()),
                                      self.size(), maximized=self.isMaximized())):
            return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            maximized = self.isMaximized()
            self.title_bar.maximize.update()
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
            self._native_resize_applied = enable_native_resize(int(self.winId()))
            self._backdrop_applied = enable_system_backdrop(int(self.winId()))

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
        if not self.export_saver.flush():
            event.ignore()
            return
        if not self.persist_session():
            event.ignore()
            return
        if not self.close_knowledge():
            self.knowledge_client.closed.connect(self.close)
            event.ignore()
            return
        if self.player:
            self.player.stop()
        self.save()
        self.overlay.close()
        if self.runtime is not None:
            self.runtime.close(wait=False)
        self.asset_check_closed = True
        self.model_action = None
        self.asset_check_timer.stop()
        self.language_popup.close()
        if self.model_prompt is not None:
            self.model_prompt.close()
        if self.background_checks:
            for check in tuple(self.background_checks):
                check.kill()
            event.ignore()
            return
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AgentScribe")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(appearance_style(STYLE))
    runtime = RuntimePreparation()
    window = Window(runtime=runtime)
    window.show()
    QTimer.singleShot(1500, window.check_startup_updates)
    QTimer.singleShot(0, runtime.prepare)
    app.aboutToQuit.connect(lambda: runtime.close(wait=False))
    sys.exit(app.exec())
