import json
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QSettings,
    QSignalBlocker,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QPainter,
)
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
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from . import diagnostic_log as diag
from .audio import list_devices
from .caption_feed import CaptionCard as CaptionCard
from .caption_feed import CaptionFeed
from .core import LANGUAGES, Caption
from .deleted_dialog import DeletedDialog
from .knowledge.client import KnowledgeClient
from .knowledge.panel import KnowledgePanel
from .knowledge.session import read_manifest, session_context
from .library import default_recording_name
from .library_access import (
    acquire_library_migration_lock,
    acquire_recording_lock,
    check_library_access,
    check_library_migration,
)
from .library_loading import LibraryReader
from .library_migration import LibraryMigration
from .library_startup import LibrarySelectionCancelled, open_library
from .management import ModelManager
from .model_options import asr_devices, normalize_asr_selection, recommended_selection
from .native_updates import NativeUpdater
from .notifications import FeedbackLabel, NotificationCenter
from .onboarding import FirstRunDialog
from .playback import PlaybackIndex
from .playback_controller import PlaybackController
from .preferences import PREFERENCES, read_audio_device, read_preferences, write_preferences
from .qt_controls import data_index
from .qt_controls import text_label as label
from .recording_controls import RecordingControls
from .recording_save import RecordingSaver
from .recording_state import RecordingState
from .runtime_preparation import RuntimePreparation
from .settings_binding import SettingsBinding
from .subtitles_overlay import Overlay
from .transcript import Transcript
from .ui_backdrop import WallpaperBackdrop
from .ui_components import (
    ActionMenu,
    NameDialog,
    NavigationButton,
    RecordingTitle,
    SurfaceDialog,
    paint_window_shadow,
)
from .ui_components import ChoiceBox as QComboBox
from .ui_theme import (
    STYLE,
    WINDOW_RADIUS,
    WINDOW_SHADOW_MARGIN,
    WORKSPACE_RADIUS,
    appearance_style,
    theme_colors,
)
from .ui_tooltips import install_tooltips
from .window_chrome import GlassTitleBar, WorkspaceFrame, line_icon
from .window_platform import (
    configure_main_window,
    enable_native_resize,
    expand_window_content,
    start_edge_resize,
)
from .wlk_session import Session
from .workspace_widgets import LanguagePopup, LibraryTree, SettingsWorkspace, Switch


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












class Window(QMainWindow):
    @property
    def library_rows(self):
        return self.library_tree.rows

    @property
    def player(self):
        return self.playback_controller.player

    @player.setter
    def player(self, value):
        self.playback_controller.player = value

    @property
    def playback_stream(self):
        return self.playback_controller.stream

    @playback_stream.setter
    def playback_stream(self, value):
        self.playback_controller.stream = value

    @property
    def audio_output(self):
        return self.playback_controller.audio_output

    @audio_output.setter
    def audio_output(self, value):
        self.playback_controller.audio_output = value

    @property
    def playback_index(self):
        return self.playback_controller.index

    @playback_index.setter
    def playback_index(self, value):
        self.playback_controller.index = value

    @property
    def playback_duration_ms(self):
        return self.playback_controller.duration_ms

    @playback_duration_ms.setter
    def playback_duration_ms(self, value):
        self.playback_controller.duration_ms = value

    @property
    def cards(self):
        return self.caption_feed.cards

    @property
    def caption_page_start(self):
        return self.caption_feed.page_start

    @caption_page_start.setter
    def caption_page_start(self, value):
        self.caption_feed.page_start = value

    @property
    def source_preview(self):
        return self.caption_feed.preview

    @source_preview.setter
    def source_preview(self, value):
        self.caption_feed.preview = value

    @property
    def source_preview_card(self):
        return self.caption_feed.preview_card

    @property
    def playback_caption_id(self):
        return self.caption_feed.playing_id

    @playback_caption_id.setter
    def playback_caption_id(self, value):
        self.caption_feed.playing_id = value

    @property
    def captions(self):
        return self.caption_feed.rows

    @captions.setter
    def captions(self, rows):
        self.caption_feed.rows = Transcript(rows)


    def __init__(self, discover=True, library_root=None, prefs=None, library=None, runtime=None):
        super().__init__()
        if sys.platform == "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.integrated_titlebar = expand_window_content(self)
        self._native_titlebar_attempted = False
        self._backdrop_attempted = False
        self._native_resize_applied = False
        self.custom_frame = sys.platform == "win32" and QApplication.platformName() == 'windows'
        if self.custom_frame:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setContentsMargins(*([WINDOW_SHADOW_MARGIN] * 4))
        self.setWindowTitle("AgentScribe · 本地同声字幕")
        self.resize(1280, 840)
        self.setMinimumSize(640, 480)
        self.session = None
        self.runtime = runtime
        self.recording_lock = None
        self.last_error = ""
        self.recording_state = RecordingState.IDLE
        self.save_error = ''
        self.recovery_snapshot = None
        self.phase_started = time.monotonic()
        self.pipeline_state = {"音频": "未开始", "识别": "未加载", "翻译": "未加载"}
        self.caption_feed = CaptionFeed(self)
        self.playback_controller = PlaybackController(self)
        self.playback_controller.available_changed.connect(self.on_playback_available)
        self.playback_controller.duration_changed.connect(self.playback_duration)
        self.playback_controller.position_changed.connect(self.playback_position)
        self.playback_controller.state_changed.connect(lambda state: (
            diag.event('playback_state', state=state), self.update_playback_button()))
        self.playback_controller.failed.connect(lambda error: self.show_warning('录音无法播放', error))
        self.playback_controller.notice.connect(lambda text: self.notifications.post('playback', text, kind='attention'))
        self.caption_page_start = None
        self.source_preview = None
        self.source_preview_sequence = 0
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
        self.first_run = None
        self.startup_model_guidance_pending = False
        self.pending_recording_close = None
        self.pending_library_path = None
        self.migration_locks = []
        self.migration_source = None
        self.playback_index = PlaybackIndex()
        self.playback_caption_id = None
        self.save_target_state = None
        self.update_fenced = False
        self.update_check_busy = False
        self.background_checks = set()
        self.prefs = prefs if prefs is not None else QSettings("LinguaFlow", "LocalCaptions")
        self.overlay = Overlay(self.prefs)
        self.library = library if library is not None else self.open_recording_library(library_root)
        self.knowledge_client = KnowledgeClient(self)
        self.knowledge_panel = None
        self.library_reader = LibraryReader(self)
        self.library_reader.completed.connect(self.on_library_read)
        self.session_dirty = False
        self.save_generation = 0
        self.caption_version = 0
        self.export_saver = RecordingSaver(self)
        self.export_request = 0
        self.export_saver.completed.connect(self.on_exported)
        self.export_saver.idle.connect(lambda: self.notifications.clear('export'))
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
        root.shutdown_complete.connect(self.close)
        self.setCentralWidget(root)
        if self.custom_frame:
            root.set_corner_radius(WINDOW_RADIUS)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.title_bar = GlassTitleBar(self)
        self.title_bar.setVisible(sys.platform == "win32" or self.integrated_titlebar)
        layout.addWidget(self.title_bar)
        split = QSplitter()
        split.setHandleWidth(1)
        self.pages = QStackedWidget()
        self.pages.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(split)
        layout.addWidget(self.pages, 1)
        self.notifications = NotificationCenter(root)
        self.library_migration = LibraryMigration(self)
        self.library_migration.progress.connect(lambda value: self.notifications.post(
            'migration', '正在迁移录音', kind='progress', progress=value,
            action=self.library_migration.cancel, action_text='取消'))
        self.library_migration.copied.connect(self.on_library_copied)
        self.library_migration.cleaned.connect(self.on_library_migrated)
        self.recording_saver.idle.connect(self.continue_deferred_operations)
        self.native_updater = NativeUpdater(self)
        self.native_updater.event.connect(self.on_native_update)
        self.native_updater.shutdown_complete.connect(self.on_update_runtime_released)
        sidebar = QFrame()
        self.recording_sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(420)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 0, 14, 14)
        sidebar_layout.setSpacing(10)
        sidebar_header = QHBoxLayout()
        self.brand = label("AgentScribe", "brand")
        self.brand.setFixedHeight(40)
        self.brand.setWordWrap(False)
        self.brand.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sidebar_header.addWidget(self.brand)
        sidebar_header.addStretch()

        sidebar_layout.addLayout(sidebar_header)
        sidebar_layout.addSpacing(6)
        self.new_button = NavigationButton("新录音")
        self.new_button.setIcon(line_icon("new"))
        self.new_button.setObjectName("navigation")
        self.new_button.clicked.connect(diag.action('recording.new', self.new_recording))
        sidebar_layout.addWidget(self.new_button)
        sidebar_layout.addSpacing(10)
        folders_heading = QHBoxLayout()
        folders_heading.addWidget(label("文件夹", "section"))
        folders_heading.addStretch()
        self.folder_button = QPushButton("＋")
        self.folder_button.setToolTip("新建文件夹")
        self.folder_button.setObjectName("quiet")
        self.folder_button.setFixedSize(28, 28)
        self.folder_button.setStyleSheet('QPushButton { min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; border: none; padding: 0; }')
        self.folder_button.clicked.connect(diag.action('folder.create', self.create_folder))
        folders_heading.addWidget(self.folder_button)
        sidebar_layout.addLayout(folders_heading)
        self.library_tree = LibraryTree()
        self.library_tree.itemClicked.connect(diag.action('library.select', self.load_library_item))
        self.library_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library_tree.customContextMenuRequested.connect(self.library_menu)
        self.library_tree.menuRequested.connect(self.show_library_menu)
        sidebar_layout.addWidget(self.library_tree, 1)
        settings_button = self.settings_button = NavigationButton("设置")
        settings_button.setObjectName("navigation")
        settings_button.setIcon(line_icon("settings"))
        settings_button.clicked.connect(diag.action('settings.open', self.open_settings))
        deleted_button = self.deleted_button = NavigationButton("最近删除")
        deleted_button.setObjectName("navigation")
        deleted_button.setIcon(line_icon('trash'))
        deleted_button.clicked.connect(diag.action('library.deleted', self.show_deleted))
        sidebar_layout.addWidget(deleted_button)
        self.ui_update_button = NavigationButton("检查更新")
        self.ui_update_button.setObjectName("navigation")
        self.ui_update_button.clicked.connect(diag.action('updates.check', self.check_software_updates))
        sidebar_layout.addWidget(self.ui_update_button)
        self.ui_update_button.show()
        sidebar_layout.addWidget(settings_button)
        self.settings_panel = QWidget()
        self.settings_panel.setObjectName("settingsPanel")
        form_outer = QVBoxLayout(self.settings_panel)
        form_outer.setContentsMargins(0, 8, 4, 0)
        form_outer.addWidget(label("聆听设置", "section"))
        form = QFormLayout()
        # Attach before adding controls that later move to SettingsWorkspace.
        # Older PySide versions otherwise retain wrappers for deleted layout items.
        form_outer.addLayout(form)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setSpacing(10)
        self.device = QComboBox()
        self.device.setMinimumWidth(270)
        self.device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device.setMinimumContentsLength(20)
        form.addRow("音频来源", self.device)
        refresh = QPushButton("刷新设备")
        refresh.clicked.connect(diag.action('audio.refresh_sources', self.refresh_devices))
        form.addRow(refresh)
        hint = "Windows：选择“系统音频”录制电脑播放内容。"
        if sys.platform == "darwin":
            hint = "电脑声音选择“系统音频”。首次使用时需允许系统录制权限。"
        form.addRow(label(hint, "muted"))
        self.source = QComboBox()
        self.source.addItem("自动检测", (None, None))
        self.target = QComboBox()
        for name, whisper, nllb in LANGUAGES:
            self.source.addItem(name, (whisper, nllb))
            self.target.addItem(name, nllb)
        form.addRow("原文语言", self.source)
        form.addRow("翻译为", self.target)
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
        manage.clicked.connect(diag.action('models.manage', self.manage_models))
        form_outer.addWidget(manage)
        form_outer.addWidget(label("原文提交后先显示初译。\n识别定稿后，再生成最终译文。", "muted"))
        form_outer.addStretch()
        self.legacy_settings_panel = self.settings_panel
        self.legacy_settings_panel.setParent(self)
        self.legacy_settings_panel.hide()
        split.addWidget(sidebar)
        right = self.workspace_frame = WorkspaceFrame()
        right.setObjectName("workspace")
        right.setMinimumWidth(300)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(1, 1, 1, WORKSPACE_RADIUS)
        right_layout.setSpacing(0)
        workspace_header = self.workspace_header = QFrame()
        workspace_header.setObjectName("workspaceHeader")
        toolbar = QHBoxLayout(workspace_header)
        workspace_header.setFixedHeight(40)
        toolbar.setContentsMargins(20, 2, 18, 2)
        self.workspace_title = RecordingTitle("新录音")
        self.workspace_title.editRequested.connect(diag.action('recording.rename', self.rename_current))
        self.workspace_title.submitted.connect(diag.action('recording.rename_submit', self.commit_recording_title))
        self.workspace_title.setStyleSheet("font-size: 16px; font-weight: 400;")
        self.workspace_title.setMinimumWidth(0)
        self.workspace_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(self.workspace_title, 1)
        self.recording_actions = QWidget()
        header_actions = self.header_actions = QHBoxLayout(self.recording_actions)
        header_actions.setContentsMargins(0, 0, 0, 0)
        header_actions.setSpacing(6)
        toolbar.addWidget(self.recording_actions)
        self.knowledge_button = QPushButton("课程资料与笔记 · Beta")
        self.knowledge_button.setObjectName("quiet")
        self.knowledge_button.hide()
        self.knowledge_button.clicked.connect(diag.action('knowledge.open', self.open_knowledge))
        header_actions.addWidget(self.knowledge_button)
        overlay_button = QPushButton("悬浮字幕")
        overlay_button.setObjectName("quiet")
        overlay_button.clicked.connect(diag.action('captions.overlay', self.toggle_overlay))
        header_actions.addWidget(overlay_button)
        self.export_button = QPushButton("导出定稿")
        self.export_button.setObjectName("quiet")
        self.export_button.clicked.connect(diag.action('recording.export', self.export))
        self.export_button.setEnabled(False)
        header_actions.addWidget(self.export_button)
        more = QPushButton("···")
        more.setObjectName("quiet")
        more.setToolTip("更多操作")
        menu = ActionMenu(more)
        self.knowledge_action = menu.addAction('课程资料与笔记 · Beta', self.open_knowledge)
        self.knowledge_action.setVisible(False)
        self.find_action = menu.addAction('查找字幕…', diag.action('captions.find', self.find_captions))
        menu.addAction("复制最新字幕", self.copy_latest)
        menu.addSeparator()
        menu.addAction("重命名录音", diag.action('recording.rename', self.rename_current))
        menu.addAction("打开保存位置", self.reveal_recording)
        menu.addAction("刷新文件列表", self.rescan_library)
        menu.addSeparator()
        diagnostics_button = menu.addAction("诊断记录")
        diagnostics_button.setCheckable(True)
        menu.addAction("打开诊断日志文件夹", diag.action('diagnostics.open', self.open_diagnostic_logs))
        more.setMenu(menu)
        header_actions.addWidget(more)
        for button in self.recording_actions.findChildren(QPushButton):
            button.setFixedHeight(32)
            button.setStyleSheet('QPushButton { min-height: 32px; max-height: 32px; border: none; padding: 0 8px; font-size: 15px; }')
        right_layout.addWidget(workspace_header)
        content = QWidget()
        content.setObjectName("workspaceContent")
        content_layout = QVBoxLayout(content)
        self.workspace_content = content
        self.workspace_content_layout = content_layout
        self.notifications.set_anchor(content)
        content.installEventFilter(self)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        self.scroll = self.caption_feed
        self.scroll.activated.connect(self.play_caption)
        self.scroll.viewport().installEventFilter(self)
        self.feed = self.scroll.feed
        self.feed_layout = self.scroll.feed_layout
        self.older_captions, self.newer_captions = self.scroll.older, self.scroll.newer
        self.empty = self.scroll.empty
        content_layout.addWidget(self.scroll, 1)
        self.reduce_motion = Switch('减少动态效果')
        self.reduce_motion.toggled.connect(lambda value: QApplication.instance().setProperty('reduceMotion', value))
        self.reduce_motion.toggled.connect(self.scroll.content_changed)
        self.beta_features = Switch('体验 Beta 功能')
        menu.addSeparator()
        menu.addAction('移到最近删除…', diag.action('recording.delete', self.delete_current))
        menu.addSeparator()
        self.retry_save_action = menu.addAction('重试保存录音', diag.action('recording.retry_save', self.retry_save))
        self.backup_action = menu.addAction('备份全部文字（含草稿）…', diag.action('recording.backup', self.backup_recording_text))
        self.finish_recovery_action = menu.addAction('使用文字备份关闭录音…',
                                                    lambda: self.finish_text_recovery(self.recovery_snapshot))
        self.retry_save_action.setEnabled(False)
        self.backup_action.setEnabled(False)
        self.finish_recovery_action.setEnabled(False)
        self.cancel_migration_action = menu.addAction('取消录音库迁移', diag.action('library.cancel_migration', self.cancel_library_migration))
        self.cancel_migration_action.setEnabled(False)
        self.cancel_model_check_action = menu.addAction('取消模型检查', diag.action('models.cancel_check', self.cancel_model_check))
        self.cancel_model_check_action.setEnabled(False)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(500)
        self.diagnostics.setMaximumHeight(160)
        self.diagnostics.hide()
        diagnostics_button.toggled.connect(self.diagnostics.setVisible)
        content_layout.addWidget(self.diagnostics)
        self.pending_source_revision = None
        self.control_island = RecordingControls(self.scroll.viewport())
        for name in (
            'meter',
            'pipeline',
            'volume_caption',
            'input_controls',
            'input_row',
            'quick_device',
            'refresh_source',
            'transport',
            'live_transport',
            'live_row',
            'state_caption',
            'capture_time',
            'transport_actions',
            'start_button',
            'stop_button',
            'pause_button',
            'playback',
            'play_button',
            'seek',
            'play_time',
            'playback_volume',
            'quick_language',
            'quick_folder',
        ):
            setattr(self, name, getattr(self.control_island, name))
        self.refresh_feedback = QTimer(self)
        self.refresh_feedback.setSingleShot(True)
        self.refresh_feedback.setInterval(1500)
        self.refresh_feedback.timeout.connect(self.reset_refresh_feedback)
        self.status = FeedbackLabel(self.notifications)
        self.status.setObjectName('status')
        self.status.setStyleSheet('font-size: 11px;')
        self.status.setMaximumHeight(36)
        self.status.hide()
        # Legacy callers use status; its presentation is exclusively global.
        self.quick_device.setModel(self.device.model())
        self.quick_device.setCurrentIndex(self.device.currentIndex())
        self.quick_device.currentIndexChanged.connect(self.device.setCurrentIndex)
        self.device.currentIndexChanged.connect(self.quick_device.setCurrentIndex)
        self.refresh_source.clicked.connect(lambda: (self.quick_device.hidePopup(), self.refresh_devices()))
        self.start_button.clicked.connect(diag.action('recording.start', self.start))
        self.stop_button.clicked.connect(diag.action('recording.stop', self.stop))
        self.pause_button.clicked.connect(diag.action('recording.pause_resume', self.toggle_pause))
        self.play_button.clicked.connect(diag.action('playback.toggle', self.toggle_playback))
        self.playback_duration_ms = 0
        self.seek.sliderMoved.connect(self.seek_playback)
        self.playback_volume.valueChanged.connect(self.set_playback_volume)
        self.language_popup = LanguagePopup(self.source, self.target, self.translate, self)
        self.language_popup.finished.connect(self.save)
        self.quick_language.clicked.connect(lambda: self.language_popup.show_at(
            self.quick_language, next_session=self.recording_state.active))
        self.quick_folder.clicked.connect(diag.action('recording.folder_select', self.choose_recording_folder))
        self.reduce_motion.toggled.connect(lambda: self.control_island.placement.start(0))
        self.control_island.heightChanged.connect(self.update_caption_insets)
        self.control_island.heightChanged.connect(self.scroll.set_overlay_height)
        self.update_transport()
        self.recording_pages = QStackedWidget()
        self.recording_pages.addWidget(content)
        right_layout.addWidget(self.recording_pages, 1)
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
        if discover and not any(self.prefs.contains(key) for key in (
                'backend', 'asr', 'qwen_model', 'translation', 'translation_engine',
                'llama_model', 'translation_device', 'compute', 'translate')):
            try:
                # A first run must start from the recommended bundle; the device
                # refresh below saves preferences before the model-check timer runs.
                self.use_recommended_profile(enable_translation=False)
            except (ValueError, RuntimeError):
                pass
        self.initial_model_selection = self.model_manager.preparation_selection()
        self.apply_appearance()
        self.appearance.currentIndexChanged.connect(self.apply_appearance)
        QApplication.instance().setProperty('reduceMotion', self.reduce_motion.isChecked())
        self.model_manager.backend.currentIndexChanged.connect(self.sync_asr_device)
        self.compute.currentIndexChanged.connect(self.select_asr_device)
        self.update_model_summary()
        self.settings_workspace = SettingsWorkspace(WorkspaceFrame,
            storage_root=self.library.root, manager=self.model_manager, audio_source_hint=hint,
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
            signal.connect(diag.action('settings.' + action.__name__, action))
        self.settings_workspace.prepare_models_requested.connect(
            diag.action('models.prepare_recommended', self.prepare_recommended_models))
        self.settings_workspace.model_browser.start_check = self.start_background_check
        self.settings_workspace.model_browser.changed.connect(self.check_model_assets)
        self.model_manager.selection_changed.connect(lambda *_: self.asset_check_timer.start(100))
        self.pages.addWidget(self.settings_workspace)
        self.pages.currentChanged.connect(self.update_preparation_feedback)
        self.settings_workspace.pages.currentChanged.connect(self.update_preparation_feedback)
        for pref in PREFERENCES:
            control = self.settings_binding.controls[pref.key]
            signal = (control.toggled if pref.kind == 'bool' else
                      control.valueChanged if pref.kind == 'float' else control.currentTextChanged)
            signal.connect(self.save_next_settings)
            signal.connect(lambda *_, key=pref.key: diag.periodic('setting_changed', seconds=1., key=key, setting=key))
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
        self.model_manager.preparation_message.connect(self.on_preparation_message)
        self.model_manager.download_changed.connect(self.on_download_progress)
        self.model_manager.preparation_changed.connect(self.on_preparation_changed)
        self.model_manager.update_checked.connect(self.on_update_checked)
        self.model_manager.update_button.clicked.disconnect()
        self.model_manager.update_button.clicked.connect(self.check_software_updates)
        self.model_manager.download_card.hide()
        self.model_manager.update_status.hide()
        self.settings_workspace.model_browser.feedback.connect(self.on_model_feedback)
        self.settings_workspace.model_browser.status.hide()
        self.model_manager.selection_changed.connect(lambda *_: self.notifications.post(
            'model-selection', '模型选择已保存，下一次聆听生效。', kind='success'))
        QTimer.singleShot(0, self.check_model_assets)
        if sys.platform == 'darwin':
            self.setup_application_menu()

    def show_warning(self, title, message):
        if not hasattr(self, 'notifications'):
            QMessageBox.warning(self, title, message)
            return
        reason = ' '.join(str(message).split())
        self.notifications.post('operation', title + '：' + reason, kind='error', details=str(message))
        self.diagnostics_append(str(message))

    def find_captions(self):
        if not self.current_item or not self.captions:
            self.notifications.post('operation', '请先打开包含字幕的录音。', kind='attention')
            return
        from .recording_search import RecordingSearchDialog
        identifier = self.current_item['id']
        self.search_dialog = RecordingSearchDialog(self.captions.values(), self)
        self.search_dialog.located.connect(lambda caption_id: self.locate_caption(identifier, caption_id))
        self.search_dialog.open()

    def locate_caption(self, identifier, caption_id):
        if not self.current_item or self.current_item['id'] != identifier or caption_id not in self.captions:
            self.notifications.post('operation', '录音内容已变化，请重新查找。', kind='attention')
            return
        self.pages.setCurrentIndex(0)
        caption = self.captions[caption_id]
        self.scroll.browse_history()
        self.ensure_caption_card(caption_id)
        if self.player:
            self.player.setPosition(round(caption.start * 1000))
        self.scroll.reveal_card(self.cards[caption_id])

    def on_model_feedback(self, text, kind):
        self.notifications.post('model-management', text, kind=kind,
                                action=self.settings_workspace.model_browser.refresh if kind == 'error' else None,
                                action_text='重试')

    def show_first_run(self):
        if self.asset_check_closed or self.recording_state.active or self.model_manager.preparing:
            return
        if self.missing_model_assets is None or 'model-check' in self.notifications.notices:
            self.startup_model_guidance_pending = True
            self.check_model_assets()
            return
        selection = self.preparation_selection()
        translating = self.translate.isChecked()
        prefixes = ('识别模型：', '翻译模型：') if translating else ('识别模型：',)
        unassigned = not selection['asr_model'] or (translating and not selection['translation_model'])
        if not unassigned and not any(item.startswith(prefixes) for item in self.missing_model_assets):
            return  # Missing runtime components or a failed check are not missing model choices.
        if self.first_run is None:
            asr_label = 'Qwen3-ASR 1.7B · MLX 4-bit' if recommended_selection()['backend'] == 'qwen3-mlx' else 'Qwen3-ASR 1.7B'
            self.first_run = FirstRunDialog(self.library.root, self, asr_label=asr_label)
            self.first_run.choose_storage.connect(self.choose_library)
            self.first_run.prepare_models.connect(self.prepare_first_run_models)
        self.first_run.set_translation_enabled(translating)
        self.first_run.storage.setText(str(self.library.root))
        missing = list(self.missing_model_assets)
        if not selection['asr_model']:
            missing.append('识别模型：尚未指定')
        if translating and not selection['translation_model']:
            missing.append('翻译模型：尚未指定')
        self.first_run.set_models(missing, preparing=self.model_manager.preparing)
        self.first_run.setWindowModality(Qt.WindowModality.NonModal)
        self.first_run.show()

    def prepare_first_run_models(self):
        self.first_run.close()
        self.open_settings('模型管理')
        self.use_recommended_profile(enable_translation=False)
        self.prepare_recommended_models(only=None if self.translate.isChecked() else 'asr')

    def update_preparation_feedback(self, *_):
        manager = self.model_manager
        visible = manager.download_card.isVisibleTo(self)
        self.notifications.set_suppressed('preparation', visible and manager.preparing)

    def on_preparation_message(self, text):
        worker = self.model_manager.worker
        if worker is not None and worker.cancelled:
            self.notifications.post('preparation', '正在取消准备；等待后台任务结束，已完成文件保留。',
                                    kind='progress')
            return
        self.model_manager.download_card.setVisible(self.model_manager.preparing or self.model_manager.retry_request is not None)
        error = text.startswith(('未完成：', '准备未完成：'))
        self.notifications.post('preparation', text if error else
                                '正在准备本地模型与组件' if self.model_manager.preparing else text,
                                kind='error' if error else 'progress' if self.model_manager.preparing else 'success',
                                details=text if error else '',
                                action=self.model_manager.cancel_preparation if self.model_manager.preparing else
                                self.model_manager.retry_preparation if error else None,
                                action_text='取消' if self.model_manager.preparing else '重试')

    def on_download_progress(self, event):
        self.model_manager.download_card.setVisible(self.model_manager.preparing or self.model_manager.retry_request is not None)
        done, total = event.get('completed', 0), event.get('total')
        known = isinstance(total, (int, float)) and total > 0 and event.get('unit') != 'stage'
        self.notifications.post('preparation', '正在下载模型' if event.get('unit') == 'B' else '正在准备本地组件',
                                kind='progress', progress=min(100, max(0, done/total*100)) if known else None,
                                action=self.model_manager.cancel_preparation, action_text='取消')

    def on_preparation_changed(self, active):
        if active:
            self.notifications.clear('preparation')
        self.model_manager.download_card.setVisible(active or self.model_manager.retry_request is not None)
        self.update_preparation_feedback()
        if not active:
            text = self.model_manager.status.text()
            if text.startswith(('未完成：', '准备未完成：')):
                self.on_preparation_message(text)
            else:
                self.notifications.post('preparation', '准备已取消，已有文件保留。' if text.startswith('准备已取消') else
                                        '本地模型与组件准备完成。', kind='success')
        if self.first_run:
            self.first_run.set_models(self.missing_model_assets, preparing=active)

    def close_recording(self):
        if not self.current_item:
            return
        self.pending_recording_close = self.current_item['id']
        self.cancel_model_check()
        if self.session is not None:
            self.stop()
            self.notifications.post('recording-close', '录音结束并保存后关闭', kind='progress')
        else:
            self.continue_deferred_operations()

    def continue_deferred_operations(self):
        if self.session is not None or self.recording_state.active or self.recording_saver.busy:
            return
        if self.pending_recording_close:
            if self.current_item and self.pending_recording_close == self.current_item['id']:
                if not self.can_edit_library():
                    return
                self.reset_recording_view()
                self.refresh_library()
            self.pending_recording_close = None
            self.notifications.clear('recording-close')
        if self.pending_library_path and not self.library_migration.busy:
            self.begin_library_migration()

    def retry_save(self):
        self.queue_session_save(self.save_target_state)

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
        app.setStyleSheet(appearance_style(mode))
        install_tooltips(app).hide()
        for button, kind in ((self.new_button, 'new'), (self.settings_button, 'settings'),
                             (self.deleted_button, 'trash'),
                             (self.ui_update_button, 'download'),
                             (self.quick_language, 'language'),
                             (self.quick_folder, 'folder'),
                             (self.refresh_source, 'check' if self.refresh_feedback.isActive() else 'refresh')):
            button.setIcon(line_icon(kind, theme_colors(mode)['muted']))
        self.quick_device.setProperty('fallbackIcon', line_icon('system', theme_colors(mode)['muted']))
        for index in range(self.device.count()):
            data = self.device.itemData(index)
            if data:
                self.device.setItemIcon(index, line_icon('system' if data[1] else 'input', colors[1]))
        for widget in self.findChildren(QWidget):
            widget.update()
        self.prefs.setValue('appearance', mode)
        self.update_playback_button()
        self.update_transport_icons()
        self.centralWidget().update()
        for frame in self.findChildren(WorkspaceFrame):
            frame.update()

    def check_software_updates(self):
        if self.asset_check_closed:
            return
        self.notifications.clear('update')
        if self.update_check_busy:
            self.notifications.post('update', '正在检查更新', kind='progress')
            return
        if self.native_updater.installed:
            self.native_updater.check()
            return
        self.notifications.post('update', '正在检查更新', kind='progress')
        self.ui_update_button.setText('正在检查…')
        self.model_manager.version_label.setText(f'当前版本：{__version__} · 正在检查更新')
        self.update_check_busy = True
        self.start_background_check('linguaflow.updates', self.on_update_checked)

    def on_update_checked(self, result):
        self.update_check_busy = False
        if self.asset_check_closed:
            return
        if not isinstance(result, dict):
            result = {'kind': 'error', 'message': '暂时无法检查更新，请重试。'}
        kind = result.get('kind', 'error')
        self.ui_update_button.setText('有新版本' if kind in ('source', 'package') else '检查更新')
        self.model_manager.version_label.setText(f'当前版本：{__version__} · ' + result.get('message', '检查失败，请重试。'))
        self.model_manager.show_update(result, respect_cancel=False)
        self.notifications.post('update', result.get('message', '暂时无法检查更新，请重试。'),
                                kind='error' if kind == 'error' else 'attention' if kind in ('source', 'package') else 'success',
                                action=self.check_software_updates if kind == 'error' else
                                self.model_manager.update_link.click if kind in ('source', 'package') else None,
                                action_text='重试' if kind == 'error' else '查看源码')

    def on_native_update(self, event):
        if self.asset_check_closed:
            return
        stage = event.get('stage')
        if event.get('text'):
            self.model_manager.version_label.setText(f'当前版本：{__version__} · ' + event['text'])
        self.ui_update_button.setText({'checking': '正在检查…', 'available': '有新版本',
                                      'downloading': '正在下载更新', 'verifying': '正在校验更新',
                                      'ready': '更新待安装', 'waiting': '更新待安装',
                                      'installing': '正在安装更新', 'busy': '更新进行中'}.get(stage, '检查更新'))
        if stage == 'quit':
            self.closing = True
            self.close()
            return
        if stage == 'waiting':
            self.try_install_update()
            return
        if stage == 'dismissed':
            # Acknowledging an error must not erase its recovery information.
            return
        if stage in ('error', 'cancelled'):
            self.native_updater.pending = False
            self.native_updater.installing = False
            self.native_updater.ready.clear()
            # A cancelled release may still be waiting for the runtime lock.
            # Keep its gate until the owning shutdown thread has finished.
            if self.native_updater.shutdown_job is None:
                self.restore_after_update()
        kinds = {'checking': 'progress', 'downloading': 'progress', 'verifying': 'progress',
                 'installing': 'progress', 'available': 'attention', 'ready': 'attention',
                 'error': 'error', 'native': 'attention', 'informational': 'attention', 'busy': 'attention'}
        action = self.show_update_notes if stage == 'available' else self.native_updater.confirm_install if stage == 'ready' else \
                 self.native_updater.cancel if stage in ('checking', 'downloading') else \
                 self.check_software_updates if stage == 'error' else None
        if stage == 'available':
            self.update_notes = event.get('notes', '')
            self.update_version = event.get('version', '')
        self.notifications.post('update', event.get('text', ''), kind=kinds.get(stage, 'success'),
                                progress=event.get('progress'), details=event.get('details', ''), action=action,
                                action_text='查看更新' if stage == 'available' else '重启更新' if stage == 'ready' else
                                '取消' if stage in ('checking', 'downloading') else '重试')

    def show_update_notes(self):
        import re
        from html import unescape
        dialog = SurfaceDialog('更新到 ' + self.update_version, '更新保留录音、模型与设置。录音中可以下载，结束并保存后才能安装。', self)
        notes = label(unescape(re.sub('<[^>]+>', '', self.update_notes)) or '此版本未提供更新说明。', 'muted')
        notes.setTextFormat(Qt.TextFormat.PlainText)
        dialog.body.addWidget(notes)
        later = QPushButton('稍后')
        later.clicked.connect(dialog.reject)
        dialog.rejected.connect(self.native_updater.cancel)
        download = QPushButton('下载更新')
        download.setObjectName('primary')
        download.clicked.connect(lambda: (dialog.accept(), self.native_updater.adapter.download()))
        dialog.actions.addStretch()
        dialog.actions.addWidget(later)
        dialog.actions.addWidget(download)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.update_dialog = dialog
        dialog.show()

    def try_install_update(self):
        self.native_updater.pending = True
        if self.knowledge_panel and self.knowledge_panel.has_unsaved_terms():
            self.notifications.post('update', '更新等待课程术语保存，请打开对应录音的课程面板完成审核。', kind='attention',
                                    action=self.cancel_update_install, action_text='取消等待')
            return
        if (self.session is not None or self.recording_state.active or self.session_dirty or self.save_error
                or self.recording_saver.busy or self.export_saver.busy or self.library_migration.busy or self.library_reader.busy
                or self.model_manager.preparing or self.knowledge_client.closing):
            self.notifications.post('update', '更新等待录音结束与文件保存，应用仍可使用。', kind='attention',
                                    action=self.cancel_update_install, action_text='取消等待')
            return
        if self.background_checks:
            self.notifications.post('update', '更新等待后台检查结束。', kind='attention',
                                    action=self.cancel_update_install, action_text='取消等待')
            return
        if not self.close_knowledge():
            self.notifications.post('update', '更新等待资料保存与后台释放。', kind='attention',
                                    action=self.cancel_update_install, action_text='取消等待')
            return
        if self.update_fenced:
            return
        self.update_fenced = True
        self.model_manager.update_fenced = True
        self.notifications.post('update', '正在保留旧版并准备重启更新', kind='progress')
        for widget in (self.library_tree, self.new_button, self.folder_button, self.start_button):
            widget.setEnabled(False)
        self.native_updater.release_runtime(self.runtime)

    def cancel_update_install(self):
        self.native_updater.pending = False
        self.notifications.post('update', '已取消等待，下载的更新可稍后安装。', kind='success')

    def on_update_runtime_released(self, error):
        if not self.native_updater.pending:
            self.restore_after_update()
            return
        if error:
            self.native_updater.event.emit({'stage': 'error', 'text': '更新准备失败，当前版本保留。', 'details': error})
            return
        self.native_updater.install()

    def restore_after_update(self):
        """Resume normal use only after the updater no longer owns shutdown work."""
        if self.runtime is not None and self.runtime.closed:
            self.runtime = RuntimePreparation()
        self.update_fenced = False
        self.model_manager.update_fenced = False
        self.set_recording_state(self.recording_state)

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
        if self.native_updater.installed:
            self.native_updater.check(manual=False)
        else:
            self.startup_update_job = self.start_background_check(
                'linguaflow.updates', self.on_startup_update_checked)

    def on_startup_update_checked(self, result):
        if self.asset_check_closed or not isinstance(result, dict) or result.get('kind') not in ('package', 'source'):
            return
        from .updates import trusted_release_url
        if not trusted_release_url(result.get('url')):
            return
        self.on_update_checked(result)
        self.model_manager.version_label.setText(f'当前版本：{__version__} · 可用新版：{result["version"]}')
        self.ui_update_button.setText('有新版本')
        self.ui_update_button.show()

    def refresh_model_assets_after_preparation(self, active):
        if active:
            self.cancel_model_check()
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
            if self.asset_check_closed or generation != self.asset_check_generation:
                return
            if selection != self.preparation_selection() or translating != self.translate.isChecked():
                self.check_model_assets()
                return
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                self.model_action = None
                self.update_start_button()
                self.startup_model_guidance_pending = False
                reason = getattr(self.asset_check, 'failure_reason', '') or '返回内容不符合预期，请重新检查。'
                message = f'模型检查未完成：{reason} 已有模型文件保留，暂时无法确认是否就绪。'
                self.model_manager.status.setText(message)
                self.notifications.post('model-check', message, kind='error',
                                        action=lambda: self.check_models_for_action('check'), action_text='重新检查')
                return
            self.on_model_assets_checked(generation, value)
        arguments = ['--check', '--selection', json.dumps(selection, ensure_ascii=False)]
        if not translating:
            arguments += ['--only', 'asr']
        self.asset_check = self.start_background_check('linguaflow.recommended_prepare', checked, *arguments)

    def on_model_assets_checked(self, generation, missing):
        if self.asset_check_closed or generation != self.asset_check_generation:
            return
        check_error = self.notifications.notices.get('model-check')
        self.notifications.clear('model-check')
        if (check_error and not self.model_manager.preparing
                and self.model_manager.status.text() == check_error.text):
            self.model_manager.status.setText('所选模型已就绪。' if not missing else
                                             '所选模型尚有缺失，请在模型管理中准备。')
        self.missing_model_assets = tuple(missing)
        self.update_translation_availability(missing)
        if self.first_run:
            self.first_run.set_models(missing, preparing=self.model_manager.preparing)
        if self.startup_model_guidance_pending:
            self.startup_model_guidance_pending = False
            if self.model_action is None:
                self.show_first_run()
        action, self.model_action = self.model_action, None
        self.update_start_button()
        blocking = [item for item in missing
                    if not item.startswith(('翻译模型：', '翻译运行组件'))]
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
            if action == 'start' and not blocking:
                self.start(models_checked=True)
            else:
                self.prompt_missing_models()

    def check_models_for_action(self, action):
        """Only explicit recording actions request a prompt; checks never download."""
        if self.model_manager.preparing or self.model_action == 'start':
            return
        self.model_action = action
        self.update_start_button()
        self.model_manager.status.setText('正在检查所选模型…')
        self.notifications.clear('model-check')
        self.notifications.post('model-check', '正在检查所选模型…', kind='progress',
                                action=self.cancel_model_check, action_text='取消检查')
        self.check_model_assets()

    def cancel_model_check(self):
        if self.model_action is None:
            return
        self.model_action = None
        self.asset_check_generation += 1
        self.asset_check_timer.stop()
        if self.asset_check in self.background_checks:
            self.asset_check.kill()
        notice = self.notifications.notices.get('model-check')
        if notice and notice.kind == 'progress' and self.model_manager.status.text() == notice.text:
            self.model_manager.status.setText('模型检查已取消；已有模型文件保留。')
        self.notifications.clear('model-check')
        self.update_start_button()

    def update_start_button(self):
        checking = self.model_action == 'start'
        self.start_button.setEnabled(not checking and not self.recording_state.active
                                     and not self.update_fenced and not self.library_migration.busy)
        self.start_button.setText('正在检查模型…' if checking else self.recording_state.value)
        self.start_button.setToolTip(self.start_button.text())
        self.start_button.setAccessibleName(self.start_button.text())
        self.cancel_model_check_action.setEnabled(self.model_action is not None)
        self.update_transport_icons()

    def translation_unavailable(self, missing=None):
        missing = self.missing_model_assets if missing is None else missing
        return bool(missing) and any(
            item.startswith(('翻译模型：', '翻译运行组件')) for item in missing)

    def update_translation_availability(self, missing=None):
        unavailable = self.translation_unavailable(missing)
        self.translate.setEnabled(not unavailable)
        self.translate.setToolTip('翻译模型未准备；本次仅识别，准备好后可开启。' if unavailable else '')
        if hasattr(self, 'language_popup'):
            self.language_popup.translation_switch.setEnabled(not unavailable)
            self.language_popup.translation_switch.setToolTip(self.translate.toolTip())
        if hasattr(self, 'quick_language'):
            self.update_quick_settings()
            self.update_recording_hint()

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

    def update_recording_header(self):
        if not hasattr(self, 'knowledge_action') or not hasattr(self, 'beta_features'):
            return
        buttons = self.recording_actions.findChildren(QPushButton)
        margins = self.workspace_header.layout().contentsMargins()
        required = (120 + margins.left() + margins.right() + self.workspace_header.layout().spacing()
                    + sum(button.sizeHint().width() for button in buttons)
                    + self.header_actions.spacing()*(len(buttons)-1))
        wide = self.workspace_header.width() >= required
        enabled = self.beta_features.isChecked()
        self.knowledge_button.setVisible(enabled and wide)
        self.knowledge_action.setVisible(enabled and not wide)

    def open_settings(self, category="常规"):
        diag.event("navigation", page="settings", category=category if category in ("常规", "聆听", "模型管理", "字幕与延迟", "运行环境", "使用指南") else "other")
        category = category if isinstance(category, str) else "常规"
        if category in ('识别模型', '翻译模型'):
            category = '模型管理'
        self.settings_workspace.search.clear()
        index = self.settings_workspace.categories.index(category)
        self.settings_workspace.navigation.setCurrentRow(index)
        self.settings_workspace.select(index)
        self.pages.setCurrentIndex(1)

    def leave_settings(self):
        diag.event("navigation", page="recording")
        self.save()
        self.update_model_summary()
        self.pages.setCurrentIndex(0)

    def return_to_recording(self):
        if self.pages.currentIndex() == 1 and QApplication.activeModalWidget() is None:
            self.leave_settings()

    def update_quick_settings(self):
        source = self.source.currentData()
        translated = self.translate.isChecked() and self.translate.isEnabled()
        if source and source[1] and source[1] == self.target.currentData() and translated:
            self.translate.setChecked(False)
            return  # The toggled signal refreshes both views with the final state.
        language = self.source.currentText()
        self.quick_language.setToolTip(language + (' → ' + self.target.currentText()
                                    if translated else ' · 仅原文'))
        self.update_recording_hint()

    def open_recording_library(self, explicit_root):
        def choose_directory(root, error):
            self.show_warning("请选择录音保存位置",
                f"默认目录无法使用：{root}\n{error}\n请选择一个可写目录。")
            return QFileDialog.getExistingDirectory(self, "选择录音保存目录")

        def migration_failed(root, error):
            self.show_warning("旧录音仍保留在原位置",
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
        current = self.library_tree.populate(self.library.index,
            current_id=self.current_item['id'] if self.current_item else None, folder_id=self.folder_id)
        if current is not None:
            self.current_item = current
            self.workspace_title.setText(current['name'])

    def rescan_library(self):
        if not self.can_edit_library():
            return
        self.library_reader.start(self.library, refresh=True,
                                  identifier=self.current_item['id'] if self.current_item else None)
        self.notifications.post('library', '正在刷新录音列表，界面仍可使用。', kind='progress')

    def on_library_read(self, result, error):
        diag.event('library_read_result', success=not bool(error), has_result=result is not None)
        if self.closing:
            self.close()
            return
        if error:
            if self.current_item and self.current_item['id'] in self.library_rows:
                self.library_tree.setCurrentItem(self.library_rows[self.current_item['id']])
            self.show_warning('无法载入录音，原视图保留', error)
            self.notifications.clear('library')
            return
        if result is None:
            self.notifications.clear('library')
            return
        snapshot, item, loaded = result
        self.library.index, self.library.paths, self.library.warnings = snapshot.index, snapshot.paths, snapshot.warnings
        if self.current_item and self.current_item["id"] not in self.library.paths:
            self.reset_recording_view()
        if self.folder_id not in self.library.paths:
            self.folder_id = self.library.index["folders"][0]["id"] if self.library.index["folders"] else None
        self.refresh_library()
        if loaded is not None:
            self.show_library_item(item, *loaded)
        self.notifications.post('library', '录音列表已载入。', kind='success')
        if self.library.warnings:
            self.show_warning("部分文件未载入", "\n".join(self.library.warnings[:8]))

    def create_folder(self, checked=False, parent_id=None):
        if self.session:
            return
        name, ok = NameDialog.getText(self, "新建文件夹", "文件夹名称")
        if ok:
            try:
                self.folder_id = self.library.folder(name, parent=parent_id)["id"]
                self.refresh_library()
            except (OSError, ValueError) as exc:
                self.show_warning("无法创建文件夹", str(exc))

    def queue_session_save(self, state=None):
        if not self.current_item or self.loading_saved or (not self.session_dirty and state is None):
            return
        # Ordinary retries must retain the terminal state that failed to save.
        if state is not None:
            self.save_target_state = state
        else:
            state = self.save_target_state
        token = (self.save_generation, self.current_item['id'])
        from .source_preview import preview_captions
        self.recording_saver.submit(self.library.save, token, self.caption_version,
                                   self.current_item, preview_captions(self.captions, self.source_preview), state)

    def on_saved(self, snapshot, state, error):
        fields = dict(session=None, recording_id=snapshot.token[1], revision=snapshot.revision,
                      state=state, success=not bool(error), level='ERROR' if error else 'INFO')
        if error or state in ('complete', 'incomplete'):
            diag.event('recording_save_result', **fields)
        else:
            diag.periodic('recording_save_result', key=snapshot.token[1], **fields)
        if not self.current_item or snapshot.token != (self.save_generation, self.current_item['id']):
            return
        if error:
            self.session_dirty = True
            self.save_error = error
            self.save_target_state = self.save_target_state or snapshot.state
            self.update_activity()
            return
        self.current_item['state'] = state
        if self.knowledge_client.identifier == self.current_item['id']:
            self.knowledge_client.saved(snapshot.captions, final=state in ('complete', 'incomplete'))
        if (snapshot.revision == self.caption_version
                and (self.save_target_state is None or state == self.save_target_state)):
            self.session_dirty = False
            self.save_error = ''
            self.save_target_state = None
            self.notifications.clear('save')
            self.status.setToolTip('')
            if not self.recording_state.active and not self.last_error:
                self.status.set_state_text('已保存')
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
                and not self.recording_saver.busy and not self.session_dirty and not self.save_error):
            self.recording_lock.unlock()
            self.recording_lock = None

    def release_playback(self):
        self.playback_controller.release()

    def on_playback_available(self, available):
        self.playback.setProperty('available', available)
        self.scroll.set_playback(available)
        self.update_transport()

    def update_recording_hint(self):
        if not hasattr(self, 'quick_folder'):
            return
        folder = self.library.folder_label(self.folder_id) if self.folder_id else '我的录音'
        self.quick_folder.setToolTip('保存到：' + folder)
        if self.recording_state.active or (self.current_item and self.current_item['state'] != 'draft'):
            return
        source = self.device.currentText() or '尚未选择音频来源，点击下方音频图标选择'
        self.quick_device.setToolTip(source)
        language = self.source.currentText() + (' → ' + self.target.currentText()
                    if self.translate.isChecked() and self.translate.isEnabled() else ' · 仅原文')
        self.empty.set_context(source, folder, language)

    def choose_recording_folder(self):
        if self.recording_state.active:
            return
        try:
            self.library.refresh()
            fallback = self.library.ensure_default_folder()
            if self.folder_id not in {folder['id'] for folder in self.library.index['folders']}:
                self.folder_id = fallback['id']
            self.refresh_library()
            self.update_recording_hint()
        except (OSError, ValueError) as exc:
            self.show_warning('无法准备录音文件夹', str(exc))
            return
        menu = ActionMenu(self.quick_folder)
        for folder in self.library.index['folders']:
            action = menu.addAction(self.library.folder_label(folder['id']))
            action.setCheckable(True)
            action.setChecked(folder['id'] == self.folder_id)
            action.triggered.connect(lambda checked=False, identifier=folder['id']: self.select_recording_folder(identifier))
        menu.exec(self.quick_folder.mapToGlobal(QPoint(0, -menu.sizeHint().height())))
        menu.deleteLater()

    def select_recording_folder(self, folder_id):
        if not self.can_edit_library():
            return
        if self.current_item:
            self.move_recording(self.current_item, folder_id)
        else:
            self.folder_id = folder_id
            self.refresh_library()
        self.update_recording_hint()

    def reset_recording_view(self):
        self.recording_pages.setCurrentIndex(0)
        self.recording_actions.show()
        self.notifications.clear('status')
        self.cancel_model_check()
        self.close_knowledge()
        self.release_playback()
        self.autosave.stop()
        self.current_item = None
        self.session_dirty = False
        self.save_error = ''
        self.save_target_state = None
        self.recovery_snapshot = None
        self.status.setToolTip('')
        self.update_activity()
        self.clear_captions()
        self.pending_recording_name = default_recording_name()
        self.workspace_title.setText(self.pending_recording_name)
        if self.folder_id not in self.library.paths:
            folders = self.library.index['folders']
            self.folder_id = folders[0]['id'] if folders else None
        self.update_recording_hint()
        self.export_button.setEnabled(False)

    def new_recording(self, checked=False, *, folder_id=None, name=None, check_models=True):
        if not self.can_edit_library():
            return False
        try:
            # A pending recording uses the current index; opening this page must
            # not recursively scan every recording on the Qt thread.
            fallback = self.library.ensure_default_folder()
            folder_id = folder_id or self.folder_id
            if folder_id not in {folder['id'] for folder in self.library.index['folders']}:
                folder_id = fallback['id']
            if name is not None:
                item = self.library.create(folder_id, {}, name=name)
        except (OSError, ValueError) as exc:
            self.show_warning("无法创建录音", str(exc))
            return False
        if name is None:
            self.reset_recording_view()
            self.folder_id = folder_id
            self.update_recording_hint()
            if folder_id not in self.library_rows:
                self.refresh_library()
            else:
                self.library_tree.setCurrentItem(self.library_rows[folder_id])
            self.pages.setCurrentIndex(0)
            notice = self.notifications.notices.get('session')
            if notice is not None and notice.kind == 'success':
                self.notifications.clear('session')
            return True
        self.reset_recording_view()
        self.folder_id, self.current_item = folder_id, item
        self.workspace_title.setText(item["name"])
        self.update_recording_hint()
        self.status.set_state_text("待开始 · " + self.library.folder_label(folder_id))
        self.refresh_library()
        self.pages.setCurrentIndex(0)
        if check_models:
            self.check_models_for_action('new')
        return True

    def open_library_item(self, row, column):
        if not self.can_edit_library():
            if self.current_item and self.current_item['id'] in self.library_rows:
                self.library_tree.setCurrentItem(self.library_rows[self.current_item['id']])
            return
        self.cancel_model_check()
        kind, identifier = row.data(0, Qt.ItemDataRole.UserRole)
        if kind == "folder":
            self.reset_recording_view()
            self.folder_id = identifier
            self.update_recording_hint()
            self.refresh_library()
            return
        item = next((i for i in self.library.index["sessions"] if i["id"] == identifier), None)
        if item is None:
            return
        try:
            data, captions = self.library.load(item)
        except (OSError, ValueError, TypeError) as exc:
            self.show_warning("无法打开录音", str(exc))
            return
        self.show_library_item(item, data, captions)

    def load_library_item(self, row, column):
        kind, identifier = row.data(0, Qt.ItemDataRole.UserRole)
        if kind == 'folder':
            self.open_library_item(row, column)
            return
        if not self.can_edit_library():
            return
        self.cancel_model_check()
        self.library_reader.start(self.library, identifier=identifier)
        self.notifications.post('library', '正在载入录音，原视图保留。', kind='progress')

    def show_library_item(self, item, data, captions):
        diag.event('recording_opened', session=None, recording_id=item['id'])
        self.release_playback()
        self.loading_saved = True
        self.clear_captions()
        self.current_item = item
        row = self.library_rows.get(item["id"])
        if row is not None:
            self.library_tree.setCurrentItem(row)
        self.folder_id = item["folder"]
        self.caption_translation = data["settings"].get("translate", True)
        self.captions = {caption.id: caption for caption in captions if caption.source}
        self.render_caption_page()
        self.empty.setVisible(not self.captions)
        self.backup_action.setEnabled(bool(self.captions))
        self.sync_overlay(animate=False)
        self.loading_saved = False
        self.session_dirty = False
        self.workspace_title.setText(item["name"])
        states = {"complete": "已保存在本机", "draft": "待开始 · 点击开始聆听"}
        self.notifications.clear('status')
        if item['state'] in states:
            self.status.set_state_text(states[item['state']])
        else:
            self.status.setText('未完整结束 · 已保留录音与草稿')
        self.recording_pages.setCurrentIndex(0)
        self.recording_actions.show()
        self.empty.setText("无内容")
        self.export_button.setEnabled(any(c.final and c.source for c in captions))
        self.attach_knowledge()
        self.prepare_playback()
        self.update_recording_hint()

    def open_knowledge(self):
        if not self.beta_features.isChecked():
            return
        if not self.current_item:
            self.notifications.post('operation', '请先新建或选择一段录音，再关联课程资料。', kind='attention')
            return
        if self.knowledge_panel is None:
            self.knowledge_panel = KnowledgePanel(self.knowledge_client, self.cancel_knowledge, self.persist_session, self,
                                                 feedback=self.notifications)
            self.knowledge_panel.seekRequested.connect(self.seek_knowledge_source)
            self.knowledge_panel.reconnectRequested.connect(self.open_knowledge)
        self.knowledge_panel.set_recording(self.recording_state.active)
        self.knowledge_panel.show()
        self.knowledge_panel.raise_()
        self.notifications.clear('knowledge')
        self.notifications.post('knowledge', '正在连接课程后台…', kind='progress')
        self.attach_knowledge(force=True)
        self.knowledge_panel.update_controls()

    def attach_knowledge(self, force=False):
        if not self.beta_features.isChecked() or not self.current_item:
            return
        try:
            if force or read_manifest(self.library, self.current_item['id'])['notes_cloud']:
                if self.knowledge_panel and self.knowledge_client.identifier != self.current_item['id']:
                    self.knowledge_panel.reset()
                self.knowledge_client.open(self.library, self.current_item, self.captions.values())
        except (OSError, ValueError, RuntimeError) as exc:
            self.notifications.post('knowledge', f'课程资料未就绪：{exc}', kind='error',
                                    action=self.open_knowledge, action_text='重新连接')

    def close_knowledge(self):
        ready = self.knowledge_client.close()
        if self.knowledge_panel:
            self.knowledge_panel.hide()
            self.knowledge_panel.reset()
        return ready

    def on_knowledge_closing(self, closing):
        for control in (self.library_tree, self.new_button, self.folder_button):
            control.setEnabled(not closing and not self.update_fenced and not self.library_migration.busy
                               and (control is self.library_tree or not self.recording_state.active))
        if closing:
            self.status.setText('课程后台正在释放文件，完成后继续当前操作。')

    def apply_beta_features(self, enabled, *, persist=True):
        """Gate all course-agent entry points and stop its owned process when opting out."""
        self.update_recording_header()
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
        if self.can_edit_library(self.current_item, rename_current=True):
            self.workspace_title.begin_edit()

    def commit_recording_title(self, name):
        if self.workspace_title.currentIndex() != 1:
            return
        # End editing before a library refresh can move focus and emit editingFinished again.
        self.workspace_title.setText(self.workspace_title.text())
        if not self.can_edit_library(self.current_item, rename_current=True):
            self.workspace_title.setText(self.workspace_title.text())
            return
        try:
            self.library.validate_name(name)
            if self.current_item:
                active = self.session is not None or self.recording_state.active
                if not active:
                    self.release_playback()
                self.library.rename(self.current_item, name, defer_directory=active)
                self.refresh_library()
                if not active:
                    self.prepare_playback()
            else:
                self.pending_recording_name = name.strip()
                self.workspace_title.setText(self.pending_recording_name)
        except (OSError, ValueError) as exc:
            self.workspace_title.setText(self.workspace_title.text())
            self.show_warning('重命名失败', str(exc))

    def rename_item(self, item):
        if self.recording_state.active and self.current_item and item['id'] == self.current_item['id']:
            self.rename_current()
            return
        if not self.can_edit_library(item):
            return
        name, ok = NameDialog.getText(self, "重命名", "名称", text=item["name"])
        if ok:
            if not self.recording_state.active:
                self.release_playback()
            try:
                self.library.rename(item, name)
                diag.event('library_item_renamed', session=None, item_id=item['id'])
                self.refresh_library()
                if not self.recording_state.active:
                    self.prepare_playback()
            except (OSError, ValueError) as exc:
                self.show_warning("重命名失败", str(exc))

    def library_menu(self, point):
        row = self.library_tree.itemAt(point)
        if row:
            self.show_library_menu(row, self.library_tree.viewport().mapToGlobal(point))

    def show_library_menu(self, row, position):
        kind, identifier = row.data(0, Qt.ItemDataRole.UserRole)
        collection = self.library.index["folders" if kind == "folder" else "sessions"]
        item = next((i for i in collection if i["id"] == identifier), None)
        if item is None:
            return
        menu = ActionMenu(self)
        active = self.session is not None or self.recording_state.active
        protected = active and self.item_contains_current(item)
        if kind == "folder":
            menu.addAction("在此文件夹中新建录音…", lambda: self.new_recording(folder_id=identifier)).setEnabled(not active)
            menu.addAction("新建子文件夹…", lambda: self.create_folder(parent_id=identifier)).setEnabled(not active)
            menu.addSeparator()
        menu.addAction("重命名…", diag.action('library.rename', lambda: self.rename_item(item))).setEnabled(not protected or kind == 'session')
        menu.addAction("在资源管理器中打开", lambda: self.open_path(self.library.directory(identifier)))
        move = ActionMenu(menu)
        move.setTitle('移动到文件夹')
        menu.addMenu(move)
        move.setEnabled(not protected)
        for folder in self.library.index["folders"]:
            if folder["id"] != identifier:
                move.addAction(self.library.folder_label(folder["id"]), lambda f=folder: self.move_recording(item, f["id"]))
        menu.addSeparator()
        menu.addAction("移到最近删除…", diag.action('library.delete', lambda: self.delete_item(item))).setEnabled(not protected)
        menu.exec(position)

    def move_recording(self, item, folder_id):
        if not self.can_edit_library(item):
            return
        if not self.recording_state.active:
            self.release_playback()
        try:
            self.library.move(item, folder_id)
            diag.event('library_item_moved', session=None, item_id=item['id'])
            if self.current_item and self.current_item["id"] == item["id"]:
                self.folder_id = folder_id
            self.refresh_library()
            if not self.recording_state.active:
                self.prepare_playback()
        except (OSError, ValueError) as exc:
            self.show_warning("移动失败", str(exc))

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
        if not self.recording_state.active:
            self.release_playback()
        try:
            self.library.trash(item)
            diag.event('library_item_trashed', session=None, item_id=item['id'])
            if self.current_item and self.current_item["id"] not in self.library.paths:
                self.reset_recording_view()
            if self.folder_id not in self.library.paths:
                self.folder_id = self.library.index["folders"][0]["id"] if self.library.index["folders"] else None
            self.refresh_library()
            self.status.setText("已移到最近删除 · 可从左下角恢复")
        except (OSError, ValueError) as exc:
            self.show_warning("删除失败，原文件保留", str(exc))

    def show_deleted(self):
        if self.session:
            self.status.setText("请先停止录音，再管理最近删除")
            return
        dialog = DeletedDialog(self.library, self, warn=self.show_warning)
        dialog.changed.connect(self.refresh_library)
        dialog.exec()
        dialog.deleteLater()

    def item_contains_current(self, item):
        if not self.current_item:
            return False
        path = self.library.directory(item['id'])
        current = self.library.directory(self.current_item['id'])
        return path == current or path in current.parents

    def can_edit_library(self, item=None, *, rename_current=False):
        if self.library_reader.busy:
            self.notifications.post('library', '正在载入录音，请稍后继续操作。', kind='progress')
            return False
        if self.update_fenced:
            return False
        if self.library_migration.busy:
            self.notifications.post('migration', '录音正在迁移，完成后可继续整理文件。', kind='progress',
                                    action=self.cancel_library_migration, action_text='取消')
            return False
        try:
            check_library_migration(self.library.root)
        except ValueError as exc:
            self.show_warning('保存目录正在迁移', str(exc))
            return False
        if self.knowledge_client.closing:
            self.status.setText('课程后台正在释放文件，请稍后操作；界面仍可使用。')
            return False
        if self.session is not None or self.recording_state.active:
            if item is None:
                return False
            try:
                if self.item_contains_current(item):
                    return bool(rename_current and item['id'] == self.current_item['id']
                                and self.recording_lock is not None and self.persist_session())
            except (OSError, ValueError) as exc:
                self.show_warning('暂时无法操作', str(exc))
                return False
            return self.file_operation_ready(item)
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
            self.show_warning("暂时无法操作", str(exc))
            return False

    def open_path(self, path):
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def reveal_recording(self):
        try:
            self.open_path(self.library.directory(self.current_item["id"]) if self.current_item else self.library.root)
        except (OSError, ValueError) as exc:
            self.show_warning("无法打开", str(exc))

    def reveal_library(self):
        self.open_path(self.library.root)

    def choose_library(self):
        if self.library_migration.busy:
            self.notifications.post('migration', '录音正在迁移', kind='progress',
                                    action=self.cancel_library_migration, action_text='取消')
            return
        path = QFileDialog.getExistingDirectory(self, "选择新保存目录（自动迁移录音，请选择空目录）", str(self.library.root))
        if not path:
            return
        if Path(path).resolve() == self.library.root:
            return
        self.pending_library_path = path
        self.cancel_migration_action.setEnabled(True)
        if self.session is not None or self.recording_state.active:
            self.notifications.post('migration-pending', '录音结束并保存后，自动迁移到新位置。',
                                    kind='progress', action=self.cancel_pending_migration, action_text='取消')
            return
        self.begin_library_migration()

    def cancel_pending_migration(self):
        self.pending_library_path = None
        self.cancel_migration_action.setEnabled(self.library_migration.busy)
        self.notifications.clear('migration-pending')

    def cancel_library_migration(self):
        self.cancel_pending_migration()
        if self.library_migration.busy:
            self.library_migration.cancel()
            self.notifications.post('migration', '正在取消迁移，原录音会保留。', kind='progress')

    def begin_library_migration(self):
        if not self.pending_library_path:
            return
        if not self.can_edit_library() or not self.export_saver.flush():
            return
        try:
            self.library.refresh()
            self.migration_locks.append(acquire_library_migration_lock(self.library.root))
            for item in self.library.index['sessions']:
                self.migration_locks.append(acquire_recording_lock(self.library.directory(item['id'])))
        except (OSError, ValueError) as exc:
            self.release_migration_locks()
            self.notifications.post('migration', '录音正在其他窗口使用，迁移未开始。', kind='error',
                                    details=str(exc), action=self.begin_library_migration, action_text='重试')
            return
        self.release_playback()
        self.migration_source = self.library
        path, self.pending_library_path = self.pending_library_path, None
        self.notifications.clear('migration-pending')
        self.notifications.post('migration', '正在迁移录音', kind='progress',
                                action=self.library_migration.cancel, action_text='取消')
        self.library_migration.start(self.library, path)
        self.cancel_migration_action.setEnabled(True)
        for widget in (self.library_tree, self.new_button, self.folder_button, self.start_button):
            widget.setEnabled(False)

    def release_migration_locks(self):
        for lock in self.migration_locks:
            lock.unlock()
        self.migration_locks = []

    def on_library_copied(self, library, verified, error):
        if error:
            self.notifications.post('migration', '迁移未完成，原录音保留。原因：' + ' '.join(error.split()),
                                    kind='error', details=error,
                                    action=self.choose_library, action_text='重新选择')
            self.on_library_migrated([], success=False)
            return
        old_root = self.library.root
        self.prefs.setValue('library_directory', str(library.root))
        self.prefs.sync()
        if self.prefs.status() != QSettings.Status.NoError:
            self.prefs.setValue('library_directory', str(old_root))
            self.notifications.post('migration', '无法保存新位置，原录音保留；新位置有已校验副本。',
                                    kind='error', action=self.choose_library, action_text='重试')
            self.on_library_migrated([], success=False)
            return
        self.library = library
        self.settings_workspace.set_storage_root(library.root)
        if self.first_run:
            self.first_run.storage.setText(str(library.root))
        if self.current_item:
            self.current_item = next((item for item in library.index['sessions'] if item['id'] == self.current_item['id']), None)
        if self.folder_id not in library.paths:
            self.folder_id = library.index['folders'][0]['id']
        self.refresh_library()
        self.library_migration.cleanup(old_root, verified)

    def on_library_migrated(self, retained, *, success=True):
        self.cancel_migration_action.setEnabled(False)
        self.release_migration_locks()
        self.migration_source = None
        for widget in (self.library_tree, self.new_button, self.folder_button, self.start_button):
            widget.setEnabled(True)
        self.update_start_button()
        if success:
            self.notifications.post('migration', '录音已迁移；部分旧文件因变化仍保留。' if retained else '录音已迁移到新位置。',
                                    kind='success', details='\n'.join(retained))
        self.prepare_playback()
        if self.closing:
            self.close()

    def prepare_playback(self):
        path = self.library.directory(self.current_item['id']) / '录音.wav' if self.current_item else None
        self.playback_controller.load(path, self.captions.values(), recover_recording=bool(
            self.current_item and self.recording_lock is None and self.current_item['state'] in ('recording', 'incomplete')))
        if self.playback_stream is not None:
            self.playback_volume.slider.setMaximum(300 if self.playback_stream.supports_gain else 100)
            self.set_playback_volume(self.playback_volume.slider.value())

    def close_playback_stream(self):
        self.playback_controller.close_stream()

    def update_transport(self):
        active = self.recording_state.active
        replay = not active and bool(self.playback.property('available'))
        self.control_island.playback_mode = replay
        self.control_island.setProperty("recording", active)
        margins = (16, 12, 16, 6) if active else (12, 8, 12, 8)
        self.control_island.content.layout().setContentsMargins(*margins)
        self.control_island.content.layout().setSpacing(8 if active else 6)
        self.playback_volume.setVisible(replay)
        self.transport.setCurrentWidget(self.playback if replay else self.live_transport)
        self.transport.setVisible(active or replay)
        self.input_controls.setVisible(not replay)
        self.start_button.setVisible(not active and not replay)
        self.quick_device.setVisible(not replay)
        self.quick_language.setVisible(not replay)
        self.quick_folder.setVisible(not active and not replay)
        for card in self.cards.values():
            for text in (card.source, card.target):
                text.set_playback_clickable(replay)
        self.update_volume_caption()
        current = self.playback if replay else self.live_transport
        current.layout().activate()
        self.transport.setFixedHeight(current.sizeHint().height())
        self.control_island.placement.start(0)

    def update_transport_icons(self):
        colors = theme_colors(QApplication.instance().property('appearance'))
        self.playback_volume.button.setIcon(line_icon('volume', colors['text']))
        for button, kind in ((self.start_button, 'play'), (self.stop_button, 'stop')):
            button.setIcon(line_icon(kind, colors['primary_text'] if button.isEnabled() else colors['disabled']))
        paused = self.recording_state is RecordingState.PAUSED
        self.pause_button.setIcon(line_icon('play' if paused else 'pause', colors['text']))
        self.pause_button.setAccessibleName('继续录音' if paused else '暂停录音')
        self.pause_button.setToolTip('继续录音' if paused else '暂停收音；已有字幕继续处理')

    def update_volume_caption(self):
        source = self.quick_device.currentData()
        category = ('系统音频' if source[1] else '外部输入') if source else '音频音量'
        state = self.recording_state
        detail = ('收尾中' if state is RecordingState.STOPPING else
                  '继续后切换' if self.pending_source_revision is not None and state is RecordingState.PAUSED else
                  '正在切换…' if self.pending_source_revision is not None else
                  '已暂停' if state is RecordingState.PAUSED else
                  '输入音量' if state is RecordingState.LISTENING else
                  '准备收音' if state.active else '')
        self.volume_caption.setText(detail)
        self.volume_caption.setToolTip(category + ' · ' + detail)
        visible = state.active and self.transport.currentWidget() is self.live_transport
        self.volume_caption.setVisible(visible)
        self.meter.setVisible(visible)

    def change_audio_source(self):
        source = self.device.currentData()
        if self.session is not None and self.recording_state.active and source:
            self.pending_source_revision = self.session.switch_source(*source)
            self.meter.setValue(0)
        self.update_volume_caption()
        self.update_recording_hint()

    def on_source_changed(self, revision):
        if self.sender() is not None and self.sender() is not self.session:
            return
        if self.recording_state is RecordingState.STARTING and not self.last_error:
            self.set_recording_state(RecordingState.LISTENING)
            self.on_stage('会话', '录音中')
            self.on_stage('音频', '连续采集')
            if self.session.model_ready.is_set():
                self.on_ready()
            else:
                self.on_status('已开始录音，正在加载识别模型。')
                self.empty.setText(self.capture_wait_text())
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
        self.control_island.arrange_input_controls(compact)

    @staticmethod
    def playback_clock(milliseconds):
        seconds = max(0, milliseconds // 1000)
        return (f'{seconds//3600}:{seconds//60%60:02}:{seconds%60:02}' if seconds >= 3600 else
                f'{seconds//60:02}:{seconds%60:02}')

    def playback_duration(self, milliseconds):
        self.playback_duration_ms = max(0, milliseconds)
        self.seek.setRange(0, self.playback_duration_ms)
        self.playback_position(self.seek.value())

    def set_playback_volume(self, value):
        self.playback_controller.set_volume(value)

    def update_playback_button(self):
        playing = self.player is not None and self.player.playbackState().name == 'PlayingState'
        title = '暂停播放' if playing else '播放录音'
        self.play_button.setIcon(line_icon('pause' if playing else 'play',
                                         theme_colors(QApplication.instance().property('appearance'))['text']))
        self.play_button.setAccessibleName(title)
        self.play_button.setToolTip(title)

    def playback_position(self, position):
        if self.seek.isSliderDown():
            return
        self.seek.setValue(position)
        self.play_time.setText(self.playback_clock(position) + ' / ' + self.playback_clock(self.playback_duration_ms))
        self.highlight_playback(position)

    def highlight_playback(self, position, *, seek=False):
        identifier = self.playback_index.at(position / 1000) if self.scroll.playback_mode else None
        if identifier is not None and (seek or self.scroll.following):
            self.ensure_caption_card(identifier)
        if identifier != self.playback_caption_id:
            for value in (self.playback_caption_id, identifier):
                card = self.cards.get(value)
                if card:
                    card.setProperty('playing', value == identifier)
                    card.update()
            self.playback_caption_id = identifier
        self.scroll.follow_playback(self.cards.get(identifier), seek=seek)
        self.update_caption_page_controls()

    def seek_playback(self, position):
        if self.player:
            self.player.setPosition(position)
        self.play_time.setText(self.playback_clock(position) + ' / ' + self.playback_clock(self.playback_duration_ms))
        self.highlight_playback(position, seek=True)

    def play_caption(self, identifier, card):
        if (self.cards.get(identifier) is not card or self.recording_state.active
                or not self.playback.property('available') or self.player is None):
            return
        caption = self.captions.get(identifier)
        if caption is not None:
            self.seek_playback(round(caption.start*1000))
            self.player.play()

    def toggle_playback(self):
        self.playback_controller.toggle()

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
        self.sync_source_options()

    def sync_source_options(self):
        """Qwen requires a concrete language; only Whisper advertises auto-detect."""
        qwen = self.model_manager.backend.currentData() in ('qwen3-streaming', 'qwen3-mlx')
        auto = self.source.findText('自动检测')
        current = self.source.currentText()
        if qwen and auto >= 0:
            if current == '自动检测':
                current = 'English'
            self.source.removeItem(auto)
            index = self.source.findText(current)
            self.source.setCurrentIndex(max(0, index))
        elif not qwen and auto < 0:
            self.source.insertItem(0, '自动检测', (None, None))
            index = self.source.findText(current)
            self.source.setCurrentIndex(max(0, index))

    def select_asr_device(self):
        if self.compute.currentData() == 'mlx':
            manager = self.model_manager
            manager.backend.setCurrentIndex(data_index(manager.backend, 'qwen3-mlx'))

    def use_recommended_profile(self, *, enable_translation=True):
        selection = recommended_selection()
        manager = self.model_manager
        manager.apply_selection(selection)
        self.sync_asr_device()
        if enable_translation:
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
        if self.update_fenced:
            return
        if self.preparation_selection() != self.model_manager.preparation_selection():
            self.use_recommended_profile()
        self.model_manager.prepare_selected(self.model_manager.preparation_selection(), only=only)

    def open_diagnostic_logs(self):
        from PySide6.QtGui import QDesktopServices
        path = diag.log_directory()
        if not path.is_dir() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.notifications.post('diagnostic-log', '无法打开诊断日志文件夹。', kind='error', details=str(path))

    def diagnostics_append(self, message):
        self.diagnostics.appendPlainText(message)

    def update_pipeline_visibility(self):
        self.pipeline.hide()

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
                    # Preserve the category in full labels; the island also paints its icon.
                    name = device.name.split(' · ', 1)[-1]
                    color = theme_colors(QApplication.instance().property('appearance'))['text']
                    self.device.addItem(line_icon('system' if device.loopback else 'input', color),
                                        f'{category} · {name}', (device.id, device.loopback))
                self.device.setCurrentIndex(data_index(self.device, previous) if previous else (0 if devices else -1))
                self.quick_device.setCurrentIndex(self.device.currentIndex())
            self.save()
            self.update_volume_caption()
            self.update_recording_hint()
            self.quick_device.setToolTip(self.device.currentText() or '音频来源不可用，请连接设备后刷新。')
            if previous and self.device.currentIndex() < 0:
                self.show_warning('音频来源不可用', '上次的音频设备不可用，请重新选择系统音频或外部输入。')
                return
            if not devices:
                self.show_warning('没有音频来源', '未发现录音设备，请连接设备并检查麦克风权限。')
                return
            self.refresh_source.setIcon(line_icon('check', theme_colors(QApplication.instance().property('appearance'))['text']))
            self.refresh_source.setToolTip(f'已刷新 · 找到 {len(devices)} 个音频来源')
            self.refresh_feedback.start()
        except Exception as exc:
            self.status.setText(f"无法读取音频设备：{exc}")
            self.show_warning('无法读取音频设备', str(exc))

    def reset_refresh_feedback(self):
        self.refresh_source.setIcon(line_icon('refresh', theme_colors(QApplication.instance().property('appearance'))['muted']))
        self.refresh_source.setToolTip('刷新音频设备列表')

    def start(self, *, models_checked=False):
        if self.library_reader.busy:
            self.notifications.post('library', '正在载入录音，请完成后再开始聆听。', kind='attention')
            return
        if self.update_fenced or self.library_migration.busy:
            return
        if self.session is not None:
            return
        try:
            check_library_migration(self.library.root)
        except ValueError as exc:
            self.show_warning('保存目录正在迁移', str(exc))
            return
        if reason := self.model_manager.start_block_reason():
            self.notifications.post('session', ' · '.join(reason), kind='attention')
            return
        self.cancel_model_check()
        device = self.quick_device.currentData()
        if device is None:
            self.show_warning("没有音频来源", "请连接录音设备并刷新列表。")
            return
        # The start action belongs to the recording page: freeze exactly the
        # source visible beside it, rather than reading a hidden settings view.
        settings = self.settings_binding.session_settings(device)
        translation_skipped = settings.translate and self.translation_unavailable()
        if translation_skipped:
            settings = replace(settings, translate=False)
        if not self.current_item or self.current_item["state"] != "draft":
            if not self.new_recording(name=getattr(self, "pending_recording_name", default_recording_name()), check_models=False):
                return
        self.clear_captions()
        self.last_error = ""
        self.notifications.clear('session')
        self.notifications.clear('operation')
        for key in list(self.notifications.notices):
            if key.startswith('pipeline-'):
                self.notifications.clear(key)
        self.pipeline_state = {
            "音频": "正在连接音频来源",
            "识别": "准备中",
            "翻译": "等待" if settings.translate else "关闭",
        }
        self.on_stage("会话", "启动中")
        self.diagnostics.clear()
        self.on_status("正在启动录音，同时加载识别模型。")
        self.empty.setText("正在连接音频来源…")
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
        # Persist the same visible source that the recording snapshot uses.
        with QSignalBlocker(self.device):
            self.device.setCurrentIndex(self.quick_device.currentIndex())
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
        if translation_skipped:
            self.notifications.post('translation', '翻译模型未准备，本次仅识别。', kind='attention')
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
                self.set_recording_state(RecordingState.IDLE)
                self.release_recording_lock()

    def set_recording_state(self, state):
        if state is not self.recording_state:
            diag.event('recording_state', state=state.name,
                       recording_id=self.current_item['id'] if self.current_item else None)
        self.recording_state = state
        self.state_caption.setText('录音中' if state is RecordingState.LISTENING else state.value)
        self.update_capture_feedback()
        if state is RecordingState.STARTING:
            self.capture_time.setText('00:00:00')
        if state is not RecordingState.LISTENING:
            self.meter.setValue(0)
        if self.knowledge_panel:
            self.knowledge_panel.set_recording(state.active)
        self.model_manager.set_session_active(state.active)
        for control in (self.library_tree, self.new_button, self.folder_button):
            control.setEnabled((control is self.library_tree or not state.active)
                               and not self.update_fenced and not self.library_migration.busy
                               and not self.knowledge_client.closing)
        source_enabled = state in (RecordingState.IDLE, RecordingState.LISTENING, RecordingState.PAUSED)
        for control in (self.device, self.quick_device, self.refresh_source):
            control.setEnabled(source_enabled)
        if state is RecordingState.IDLE:
            self.pending_source_revision = None
        self.update_start_button()
        self.stop_button.setEnabled(state.can_stop)
        self.stop_button.setVisible(state.active)
        self.pause_button.setVisible(state.active)
        self.pause_button.setEnabled(state.can_pause and not self.last_error)
        self.pause_button.setText("继续录音" if state is RecordingState.PAUSED else "暂停")
        self.update_transport_icons()
        self.start_button.setVisible(not state.active)
        self.update_transport()
        self.export_button.setEnabled(not state.active and any(c.final and c.source for c in self.captions.values()))
        self.update_pipeline_visibility()
        reason = '正在聆听，请先停止录音再切换。' if state.active else ''
        for control in (self.library_tree, self.new_button, self.folder_button):
            control.setToolTip(reason)
        self.library_tree.setToolTip('右键可管理其他录音；当前录音可改名，停止后可切换。' if state.active else '')
        if not state.active:
            self.folder_button.setToolTip('新建文件夹')
        self.quick_device.setToolTip(self.device.currentText() + '\n系统音频：电脑播放的声音；外部输入：麦克风或虚拟输入。\n录音时可切换，暂停时切换将在继续后生效。')

    def launch_session(self, settings):
        self.session = Session(settings, self, recording_path=
                               self.library.directory(self.current_item["id"]) / "录音.wav", runtime=self.runtime)
        diag.event('recording_session_link', session=getattr(self.session, 'log_session', None),
                   recording_id=self.current_item['id'])
        self.session.status.connect(self.on_status)
        self.session.stage.connect(self.on_stage)
        self.session.ready.connect(self.on_ready)
        self.session.paused.connect(self.on_paused)
        self.session.caption.connect(self.on_caption)
        self.session.source_preview.connect(self.on_source_preview)
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
        if self.last_error:
            self.notifications.clear('pipeline-' + name)
            return
        if any(word in state for word in ('失败', '错误')):
            self.notifications.post('pipeline-' + name, name + '未就绪，请检查设置后重试。', kind='error', details=state)
        else:
            self.notifications.clear('pipeline-' + name)
        if name == '音频' and self.recording_state is RecordingState.LISTENING and not self.captions:
            if state.startswith('输入持续为零'):
                self.empty.setText('没有收到声音。\n请检查所选音频来源、静音和麦克风权限。')
            elif state.startswith('已收到声音'):
                self.empty.setText(self.capture_wait_text())

    def capture_wait_text(self):
        state = self.recording_state
        if state is RecordingState.IDLE:
            return '等待语音…'
        if state is RecordingState.STARTING:
            return '正在连接音频来源…'
        if state is not RecordingState.LISTENING:
            return state.value
        ready = getattr(self.session, 'model_ready', None)
        return ('录音已开始'
                if ready is not None and not ready.is_set() else '正在聆听…')

    def update_capture_feedback(self):
        ready = getattr(self.session, 'model_ready', None)
        loading = (self.recording_state.active
            and self.recording_state is not RecordingState.STOPPING
            and not self.last_error and ready is not None and not ready.is_set())
        if loading:
            self.notifications.post('model-loading', '正在加载模型', kind='progress')
        else:
            self.notifications.clear('model-loading')
        self.sync_overlay(animate=False)

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
        self.update_capture_feedback()
        if self.recording_state is RecordingState.STOPPING:
            self.notifications.post('session', '正在收尾并保存录音', kind='progress')
        elif self.recording_state in (RecordingState.PAUSING, RecordingState.RESUMING):
            self.notifications.post('session', '正在暂停收音' if self.recording_state is RecordingState.PAUSING else
                                    '正在继续录音', kind='progress')
        self.update_activity()

    def update_activity(self):
        self.retry_save_action.setEnabled(bool(self.save_error) and not self.recording_saver.busy)
        self.backup_action.setEnabled(bool(self.captions or self.source_preview))
        self.finish_recovery_action.setEnabled(self.recovery_ready(self.recovery_snapshot))
        if self.session is not None:
            seconds = max(0, int(getattr(self.session, 'recorded_seconds', 0)))
            self.capture_time.setText(f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}')
        if self.native_updater.pending and not self.update_fenced:
            self.try_install_update()
        if self.pending_library_path and not self.recording_state.active and not self.session_dirty:
            self.continue_deferred_operations()
        self.status.setVisible(bool(self.save_error or self.last_error))
        if self.status.property('saveError') != bool(self.save_error):
            self.status.setProperty('saveError', bool(self.save_error))
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        if self.save_error:
            self.status.set_state_text('自动保存失败 · 字幕仍保留，请检查保存位置')
            self.status.setToolTip(self.save_error)
            text = ('文字备份已保存；原录音仍未保存。可重试，或从更多操作使用备份关闭。'
                    if self.finish_recovery_action.isEnabled() else
                    '录音保存失败，字幕仍保留。请检查磁盘空间及目录权限，也可从更多操作备份文字。')
            self.notifications.post('save', text, kind='error', details=self.save_error,
                                    action=self.retry_save, action_text='重试保存')
        elif self.recording_state.active and not self.last_error:
            elapsed = int(time.monotonic() - self.phase_started)
            self.status.set_state_text(self.recording_state.status(elapsed))

    def on_ready(self):
        if self.last_error:
            return
        if self.recording_state not in (RecordingState.STARTING, RecordingState.LISTENING,
                                       RecordingState.PAUSED, RecordingState.PAUSING, RecordingState.RESUMING):
            return
        self.update_capture_feedback()
        self.on_status('识别模型已就绪，录音按当前状态继续。')
        if self.recording_state in (RecordingState.STARTING, RecordingState.LISTENING):
            if not self.pipeline_state.get('音频', '').startswith('输入持续为零'):
                self.empty.setText(self.capture_wait_text())

    def clear_captions(self):
        self.caption_feed.clear()
        self.source_preview_sequence = 0
        self.save_generation += 1
        self.caption_version = 0
        self.playback_index = PlaybackIndex()
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
        self.notifications.post('session', '已暂停收音。' if paused else '已继续录音。', kind='success')
        self.on_stage("会话", "已暂停" if paused else "聆听中")
        self.on_status("已暂停收音；点击继续录音可接着录，暂停时间不计入录音。" if paused else "已继续录音。")
        if paused:
            self.meter.setValue(0)
        if not self.captions:
            self.empty.setText("已暂停收音" if paused else self.capture_wait_text())

    def on_failure(self, message):
        self.last_error = message
        self.notifications.clear('model-loading')
        for key in list(self.notifications.notices):
            if key.startswith('pipeline-'):
                self.notifications.clear(key)
        self.pause_button.setEnabled(False)
        self.status.set_state_text('识别未完成，已有录音和字幕会保留。')
        reason = ' '.join(str(message).split())
        self.notifications.post('session', '识别未完成，已有录音和字幕会保留。原因：' + reason, kind='error', details=message,
                                action=lambda: self.open_settings('运行环境'), action_text='检查环境')
        self.update_activity()
        self.diagnostics.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)
        if not self.captions:
            self.empty.setText('识别未完成。\n请查看右上角错误提示，或在设置中检查运行环境。\n已有内容会保留。')

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
        self.retain_source_preview()
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
        if saved and self.current_item and 'pending_name' in self.current_item:
            try:
                if self.file_operation_ready(self.current_item):
                    self.library.rename(self.current_item, self.current_item['pending_name'])
            except (OSError, ValueError) as exc:
                self.show_warning('名称已保存，文件夹名暂未同步', str(exc))
        self.refresh_library()
        self.prepare_playback()
        if not self.captions:
            self.empty.setText('无内容')
        self.meter.setValue(0)
        for key in list(self.notifications.notices):
            if key.startswith('pipeline-'):
                self.notifications.clear(key)
        self.status.setText('保存失败，请从更多操作重试保存或备份全部文字。' if not saved else
                           '识别未完成，已有录音和字幕会保留。' if self.last_error else ("已取消 · 录音尚未开始" if state == "draft" and saved else
                            "录音已保存 · 部分翻译未完成" if saved and translation_incomplete else
                            "已保存录音与定稿"))
        self.on_stage("会话", "失败，详见诊断" if self.last_error else "已结束")
        if not self.last_error:
            self.notifications.clear('session')
        if not self.last_error and saved:
            self.notifications.post('session', '录音已保存，部分翻译未完成。' if translation_incomplete else
                                    '录音与字幕已保存。', kind='success')
        if saved:
            QTimer.singleShot(0, self.continue_deferred_operations)
        if self.closing:
            self.close()
        elif self.runtime is not None:
            self.runtime.prepare()

    def on_source_preview(self, event):
        sender = self.sender()
        if (not self.recording_state.active or self.session is None
                or (sender is not None and sender is not self.session)):
            return
        sequence = event['sequence']
        if event.get('done'):
            if self.source_preview is not None and sequence == self.source_preview_sequence:
                self.clear_source_preview()
                self.save_source_preview()
            return
        if sequence <= self.source_preview_sequence:
            return
        self.source_preview_sequence = sequence
        self.caption_feed.set_preview(event)
        self.save_source_preview()
        self.backup_action.setEnabled(True)
        self.sync_overlay(animate=False)

    def save_source_preview(self):
        # The saver coalesces pending revisions off the UI thread. Do not wait
        # for SaT or restart a debounce timer on every recognition update.
        if self.current_item and not self.loading_saved:
            self.session_dirty = True
            self.caption_version += 1
            self.queue_session_save()

    def apply_source_preview(self):
        self.caption_feed.apply_preview()

    def clear_source_preview(self):
        self.caption_feed.clear_preview()
        self.sync_overlay(animate=False)

    def retain_source_preview(self):
        """Keep the newest recognized words if semantic processing did not finish."""
        event = self.source_preview
        if event is None:
            return
        from .source_preview import preview_captions
        snapshot = preview_captions(self.captions, event)
        keep = set(event['keep_ids'])
        replaced = [caption for identifier, caption in self.captions.items() if identifier not in keep]
        self.clear_source_preview()
        for caption in replaced:
            self.on_caption(replace(caption, source='', revision=caption.revision+1))
        for caption in snapshot:
            if caption.id not in keep:
                self.on_caption(caption)
        if not self.last_error:
            self.on_failure('原文分句未完成，最新识别结果已作为草稿保留，请对照录音。')

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
        if (caption.source and previous and previous.source == caption.source
                and previous.language == caption.language and not caption.translation and (caption.ready or caption.final)):
            caption = replace(caption, translation=previous.translation,
                              translation_source=previous.translation_source,
                              translation_phase=previous.translation_phase)
        self.caption_feed.set_context(translating=self.caption_translation,
            active=self.recording_state.active, loading=self.loading_saved)
        self.caption_feed.set_caption(caption)
        self.sync_overlay(animate=not self.loading_saved)
        self.export_button.setEnabled(any(c.final and c.source for c in self.captions.values()))
        self.backup_action.setEnabled(bool(self.captions or self.source_preview))
        if self.current_item and not self.loading_saved:
            if not caption.source:
                self.autosave.start(800)
            elif not self.autosave.isActive():
                self.autosave.start(1500)

    def render_caption_page(self):
        self.caption_feed.set_context(translating=self.caption_translation,
            active=self.recording_state.active, loading=self.loading_saved)
        self.caption_feed.render()

    def update_caption_page_controls(self):
        self.caption_feed.update_page_controls()

    def ensure_caption_card(self, identifier):
        self.caption_feed.ensure_card(identifier)

    def change_caption_page(self, direction):
        self.caption_feed.change_page(direction)

    def return_to_caption_target(self):
        self.caption_feed.return_to_target()

    def toggle_overlay(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.sync_overlay(animate=False)
            self.overlay.show()
            self.overlay.raise_()

    def sync_overlay(self, *, animate=True):
        if self.source_preview is not None and self.source_preview['source']:
            event = self.source_preview
            self.overlay.update_caption(Caption(0, event['start'], event['end'], event['source'],
                event['language'], final=False), False, animate=False)
            return
        if self.source_preview is None:
            captions = self.captions.values()
        else:
            keep = set(self.source_preview['keep_ids'])
            captions = (value for key, value in self.captions.items() if key in keep)
        caption = max(captions, key=lambda item: (item.start, item.id), default=None)
        if caption is not None:
            self.overlay.update_caption(caption, self.caption_translation if self.recording_state.active
                                        else self.translate.isChecked(), animate=animate)
        else:
            self.overlay.source.setText(self.capture_wait_text())
            self.overlay.target.setText('')
            self.overlay.target.hide()

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
            self.show_export_progress('正在导出录音定稿…')
            self.export_request += 1
            self.export_saver.submit(write_export, (-self.export_request, str(target)), 0,
                                     dict(path=str(target), format=kind, state='exported'), captions)

    def show_export_progress(self, text):
        if not self.export_saver.busy:
            self.notifications.clear('export')
        else:
            text = '正在导出或备份文字，后续任务已排队…'
        self.notifications.post('export', text, kind='progress')

    def backup_recording_text(self):
        from .recording_export import write_recovery
        if not self.current_item or not (self.captions or self.source_preview):
            return
        identity = (self.save_generation, self.current_item['id'])
        path, _ = QFileDialog.getSaveFileName(self, '备份全部文字（含草稿）',
                                             '录音文字恢复备份.txt', '文字恢复备份 (*.txt)')
        if not path:
            return
        if not self.current_item or identity != (self.save_generation, self.current_item['id']):
            self.show_warning('录音内容已变化', '请重新选择要备份的录音。')
            return
        target = Path(path)
        if target.suffix.lower() != '.txt':
            target = Path(path + '.txt')
            if target.exists() and QMessageBox.question(self, '覆盖恢复备份？', str(target),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
                return
        captions = list(self.captions.values())
        if self.source_preview and self.source_preview['source']:
            event = self.source_preview
            captions.append(Caption(max(self.captions, default=0)+1, event['start'], event['end'],
                                    event['source'], event['language'], final=False,
                                    error='实时原文预览，尚未完成分句。'))
        item = dict(path=str(target), format='recovery', state='recovery', name=self.current_item['name'],
                    recording_id=self.current_item['id'])
        self.show_export_progress('正在备份全部文字…')
        self.export_saver.submit(write_recovery, (self.save_generation, str(target)),
                                 self.caption_version, item, captions)

    def recovery_ready(self, snapshot):
        return bool(snapshot and self.current_item and self.session_dirty and self.save_error
            and not self.recording_state.active and self.session is None and not self.recording_saver.busy
            and snapshot.token[0] == self.save_generation
            and snapshot.item.get('recording_id') == self.current_item['id']
            and snapshot.revision == self.caption_version)

    def finish_text_recovery(self, snapshot):
        if snapshot is None or not self.session_dirty or not self.save_error:
            return
        if not self.recovery_ready(snapshot):
            self.show_warning('录音内容已变化', '请先停止录音并重新备份全部文字，再关闭此录音。')
            return
        if not Path(snapshot.item['path']).is_file():
            self.show_warning('恢复备份不可用', '请重新备份全部文字，再关闭此录音。')
            return
        if QMessageBox.question(self, '使用文字备份并关闭此录音？',
                '文字已备份到：' + snapshot.item['path'] + '\n\n原录音仍未成功保存。备份不含音频；'
                '原目录及已有音频会保留。关闭后，请使用备份核对草稿和译文。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        if not self.recovery_ready(snapshot):
            self.show_warning('录音内容已变化', '请重新备份全部文字，再关闭此录音。')
            return
        self.autosave.stop()
        self.session_dirty = False
        self.save_error = ''
        self.notifications.clear('save')
        self.notifications.clear('recovery')
        self.release_recording_lock()
        self.reset_recording_view()
        self.refresh_library()

    def on_exported(self, snapshot, state, error):
        diag.event('text_export_result', session=None, kind=snapshot.item.get('format'),
                   revision=snapshot.revision, success=not bool(error))
        if error:
            self.show_warning("导出失败", error)
        elif snapshot.item.get('format') == 'recovery':
            self.recovery_snapshot = snapshot
            self.update_activity()
            self.notifications.post('recovery', '全部文字恢复备份已保存；原录音的保存状态未改变。', kind='success',
                                    action=(lambda: self.finish_text_recovery(snapshot)) if self.save_error else None,
                                    action_text='使用备份关闭录音')
        else:
            self.status.setText(f"已导出录音定稿：{snapshot.item['path']}")

    def update_caption_insets(self, *_):
        width = self.scroll.viewport().width()
        margin = max(20, (width-900)//2) + 12
        self.feed_layout.setContentsMargins(margin, 24, margin, self.control_island.height()+46)
        self.place_recording_hint()

    def place_recording_hint(self):
        viewport = self.scroll.viewport()
        center = viewport.mapFrom(self.workspace_frame, self.workspace_frame.rect().center())
        width = min(448, max(1, viewport.width()-32))
        height = max(220, self.empty.minimumSizeHint().height())
        self.empty.setGeometry(max(0, center.x()-width//2), max(0, center.y()-height//2), width, height)
        self.empty.raise_()
        self.control_island.raise_()
        if self.playback_volume.isVisible():
            self.playback_volume.raise_()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and watched is getattr(self, 'workspace_header', None):
            self.update_recording_header()
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
            if self.custom_frame:
                expanded = maximized or self.isFullScreen()
                self.setContentsMargins(*([0 if expanded else WINDOW_SHADOW_MARGIN] * 4))
                self.centralWidget().set_corner_radius(0 if expanded else WINDOW_RADIUS)
                self.update()
            self.title_bar.maximize.update()
            self.title_bar.maximize.setToolTip("还原" if maximized else "最大化")

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.custom_frame and not (self.isMaximized() or self.isFullScreen()):
            painter = QPainter(self)
            paint_window_shadow(painter, self.contentsRect(), WINDOW_RADIUS)
            painter.end()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.centralWidget() is not None:
            self.centralWidget().update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.integrated_titlebar and not self._native_titlebar_attempted:
            self._native_titlebar_attempted = True
            configure_main_window(int(self.winId()))
            # In fullscreen, a notched display can need more room than the
            # normal title controls. Keep the content below that safe area.
            handle = self.windowHandle()
            handle.safeAreaMarginsChanged.connect(self.update_titlebar_inset)
            self.update_titlebar_inset(handle.safeAreaMargins())
        if (not self._backdrop_attempted
                and sys.platform == "win32"
                and os.environ.get("QT_QPA_PLATFORM") != "offscreen"):
            self._backdrop_attempted = True
            self._native_resize_applied = enable_native_resize(int(self.winId()))

    def update_titlebar_inset(self, margins):
        self.title_bar.setFixedHeight(max(36, margins.top()))

    def closeEvent(self, event):
        diag.periodic('app_close_requested', seconds=2., recording_active=self.session is not None,
                      preparing=self.model_manager.worker is not None, saving=self.recording_saver.busy)
        # Invalidate a pending start before any save/cleanup enters a nested
        # event loop; a check finishing during shutdown must never start audio.
        self.cancel_model_check()
        if self.library_reader.busy:
            self.closing = True
            self.library_reader.cancel()
            diag.periodic('app_close_deferred', seconds=2., key='library_read', reason='library_read')
            event.ignore()
            return
        if self.native_updater.shutdown_job is not None:
            diag.periodic('app_close_deferred', seconds=2., key='update_shutdown', reason='update_shutdown')
            event.ignore()
            return
        if self.library_migration.busy:
            self.closing = True
            self.library_migration.cancel()
            self.notifications.post('migration', '正在结束迁移，原录音会保留。', kind='progress')
            diag.periodic('app_close_deferred', seconds=2., key='library_migration', reason='library_migration')
            event.ignore()
            return
        if self.model_manager.worker is not None:
            self.model_manager.cancel_preparation()
            self.model_manager.worker.finished.connect(self.close)
            diag.periodic('app_close_deferred', seconds=2., key='model_preparation', reason='model_preparation')
            event.ignore()
            return
        if self.session is not None:
            self.closing = True
            self.stop()
            self.status.setText("正在释放模型，请等待当前加载或推理结束…")
            diag.periodic('app_close_deferred', seconds=2., key='recording_session', reason='recording_session')
            event.ignore()
            return
        if not self.export_saver.flush():
            diag.periodic('app_close_deferred', seconds=2., key='text_export', reason='text_export')
            event.ignore()
            return
        if not self.persist_session():
            diag.periodic('app_close_deferred', seconds=2., key='recording_save', reason='recording_save')
            event.ignore()
            return
        if self.knowledge_panel and not self.knowledge_panel.confirm_exit():
            self.closing = False
            diag.periodic('app_close_deferred', seconds=2., key='knowledge_confirmation', reason='knowledge_confirmation')
            event.ignore()
            return
        if not self.close_knowledge():
            self.knowledge_client.closed.connect(self.close)
            diag.periodic('app_close_deferred', seconds=2., key='knowledge_shutdown', reason='knowledge_shutdown')
            event.ignore()
            return
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.close_playback_stream()
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
            diag.periodic('app_close_deferred', seconds=2., key='background_checks', reason='background_checks')
            event.ignore()
            return
        if not self.centralWidget().shutdown():
            diag.periodic('app_close_deferred', seconds=2., key='ui_shutdown', reason='ui_shutdown')
            event.ignore()
            return
        self.native_updater.close()
        diag.event('app_close_accepted')
        event.accept()


def main():
    diag.start_logging('desktop')
    diag.install_exception_hooks()
    from .process_platform import hold_installation_mutex
    from .runtime_paths import packaged
    hold_installation_mutex(installed=packaged())
    app = QApplication(sys.argv)
    app.setApplicationName("AgentScribe")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    runtime = RuntimePreparation()
    window = Window(runtime=runtime)
    window.show()
    diag.event('app_ready')
    from .resource_monitor import ResourceMonitor
    resources = ResourceMonitor()
    resources.start()
    def report_log_error():
        if diag.log_error():
            window.notifications.post('diagnostic-log', diag.log_error(), kind='error', details=str(diag.log_directory()))
    log_health = QTimer(window)
    log_health.setInterval(10000)
    log_health.timeout.connect(report_log_error)
    log_health.start()
    QTimer.singleShot(0, report_log_error)
    from .update_recovery import mark_startup_healthy, take_recovery_notice
    def startup_feedback():
        if mark_startup_healthy():
            window.notifications.post('update', f'已更新到 {__version__}。', kind='success')
        notice = take_recovery_notice()
        if notice:
            window.notifications.post('update', notice['text'], kind='error', details=notice['details'])
    QTimer.singleShot(0, startup_feedback)
    QTimer.singleShot(0, window.show_first_run)
    QTimer.singleShot(1500, window.check_startup_updates)
    QTimer.singleShot(0, runtime.prepare)
    app.aboutToQuit.connect(lambda: runtime.close(wait=False))
    try:
        exit_code = app.exec()
    finally:
        resources.close()
        diag.event('app_event_loop_stopped')
        diag.close_logging()
    sys.exit(exit_code)
