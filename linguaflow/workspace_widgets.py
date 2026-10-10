"""Quiet navigation, explicit recording creation and the full-page settings view."""

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from .library import default_recording_name
from .qt_controls import text_label
from .ui_components import ChoiceBox as QComboBox
from .ui_components import PageTransition, SurfaceDialog, motion_enabled
from .ui_theme import theme_colors

PAGE_DESCRIPTIONS = {
    '模型管理': '查看、设置或删除已下载的识别与翻译模型。',
    '常规': '管理本地录音、保存位置和使用习惯。',
    '聆听': '从哪里听、听什么语言，以及你想看到的译文。',
    '识别模型': '把声音变成原文。选择引擎和计算设备，再准备模型。',
    '翻译模型': '提交后先看初译，识别定稿后再结合上下文生成最终译文。',
    '字幕与延迟': '调整识别请求频率与计算量；实际草稿速度取决于模型，不直接控制字幕定稿。',
    '运行环境': '准备本地组件、修复运行环境和检查软件更新。',
    '使用指南': '从第一次聆听，到整理和分享你的录音。',
}


class Switch(QCheckBox):
    def __init__(self, text=""):
        super().__init__(text)
        self.setAccessibleName(text)
        self.setFixedSize(38, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.position = 0.
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(150)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self.set_position)
        self.toggled.connect(self.animate)

    def set_position(self, value):
        self.position = float(value)
        self.update()

    def animate(self, checked):
        self.motion.stop()
        if not self.isVisible() or not motion_enabled():
            self.set_position(float(checked))
            return
        self.motion.setStartValue(self.position)
        self.motion.setEndValue(float(checked))
        self.motion.start()

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setOpacity(1 if self.isEnabled() else .4)
        c = theme_colors(QApplication.instance().property('appearance'))
        painter.setBrush(QColor(c['primary'] if self.isChecked() else c['disabled']))
        painter.drawRoundedRect(QRectF(1, 3, 36, 20), 10, 10)
        painter.setBrush(QColor(c['primary_text'] if self.isChecked() else c['surface']))
        painter.drawEllipse(QRectF(3 + 16 * self.position, 5, 16, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(c['focus']))
            painter.drawRoundedRect(QRectF(.5, .5, 37, 23), 11, 11)


class LanguagePopup(QDialog):
    """Three views of the existing language controls, with no independent settings."""
    def __init__(self, source, target, translate, parent):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(320)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        surface = QFrame()
        surface.setObjectName('dialogSurface')
        outer.addWidget(surface)
        form = QFormLayout(surface)
        form.setContentsMargins(18, 14, 18, 14)
        form.setSpacing(10)
        self.source_choice, self.target_choice = QComboBox(), QComboBox()
        for view, control in ((self.source_choice, source), (self.target_choice, target)):
            view.setModel(control.model())
            view.setCurrentIndex(control.currentIndex())
            view.currentIndexChanged.connect(control.setCurrentIndex)
            control.currentIndexChanged.connect(view.setCurrentIndex)
        form.addRow('原文', self.source_choice)
        form.addRow('译文', self.target_choice)
        self.translation_switch = Switch('启用翻译')
        self.translation_switch.setChecked(translate.isChecked())
        self.translation_switch.toggled.connect(translate.setChecked)
        translate.toggled.connect(self.translation_switch.setChecked)
        form.addRow('启用翻译', self.translation_switch)
        self.hint = text_label('修改用于下一次聆听。', 'muted')
        form.addRow(self.hint)

    def show_at(self, anchor, *, next_session=False):
        self.hint.setVisible(next_session)
        self.adjustSize()
        point = anchor.mapToGlobal(QPoint(0, 0))
        bounds = anchor.screen().availableGeometry()
        x = max(bounds.left()+8, min(point.x(), bounds.right()-self.width()-8))
        y = max(bounds.top()+8, point.y()-self.height()-6)
        self.move(x, y)
        self.show()
        self.source_choice.setFocus()


class LibraryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(200, 38)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        light = QApplication.instance().property("appearance") != "dark"
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            colors = theme_colors(QApplication.instance().property('appearance'))
            painter.setBrush(QColor(colors['selected' if selected else 'hover']))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(2, 2, -2, -2), 8, 8)
        depth, parent = 0, index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        x = option.rect.x() + 12 + depth * 14
        kind, _ = index.data(Qt.ItemDataRole.UserRole)
        y = option.rect.center().y()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor('#666670' if light else '#aaaab2'))
        if kind == 'folder':
            expanded = bool(option.state & QStyle.StateFlag.State_Open)
            points = [(x + 2, y - 2), (x + 5, y + 1), (x + 8, y - 2)] if expanded else [
                (x + 3, y - 4), (x + 6, y - 1), (x + 3, y + 2)]
            painter.drawLine(QPointF(*points[0]), QPointF(*points[1]))
            painter.drawLine(QPointF(*points[1]), QPointF(*points[2]))
            painter.drawRoundedRect(QRectF(x + 15, y - 5, 15, 11), 2, 2)
            painter.drawLine(QPointF(x + 16, y - 7), QPointF(x + 22, y - 7))
            text_x = x + 37
        else:
            painter.drawRoundedRect(QRectF(x + 10, y - 7, 11, 14), 2, 2)
            painter.drawLine(QPointF(x + 13, y - 2), QPointF(x + 18, y - 2))
            painter.drawLine(QPointF(x + 13, y + 2), QPointF(x + 18, y + 2))
            text_x = x + 30
        painter.setFont(option.font)
        painter.setPen(QColor(("#303034" if selected else "#60606a") if light else ("#eeeeef" if selected else "#bdbdc3")))
        rect = option.rect.adjusted(text_x - option.rect.x(), 0, -53, 0)
        title = str(index.data())
        if option.fontMetrics.horizontalAdvance(title) <= rect.width():
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, title)
        elif rect.width() > 0:
            ratio = painter.device().devicePixelRatioF()
            layer = QPixmap(round(rect.width() * ratio), round(rect.height() * ratio))
            layer.setDevicePixelRatio(ratio)
            layer.fill(Qt.GlobalColor.transparent)
            ink = QPainter(layer)
            ink.setFont(option.font)
            ink.setPen(painter.pen())
            bounds = QRectF(0, 0, rect.width(), rect.height())
            ink.drawText(bounds, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine, title)
            ink.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            fade = QLinearGradient(max(0, rect.width() - 28), 0, rect.width(), 0)
            fade.setColorAt(0, QColor(0, 0, 0, 255))
            fade.setColorAt(1, QColor(0, 0, 0, 0))
            ink.fillRect(bounds, fade)
            ink.end()
            painter.drawPixmap(rect.topLeft(), layer)
        if kind == "folder":
            painter.setPen(QColor("#9999a1"))
            painter.drawText(option.rect.adjusted(option.rect.width() - 50, 0, -26, 0), Qt.AlignmentFlag.AlignCenter, "+")
        if hover or selected:
            painter.drawText(option.rect.adjusted(option.rect.width() - 27, 0, -4, 0), Qt.AlignmentFlag.AlignCenter, "···")
        painter.restore()


class LibraryTree(QTreeWidget):
    newRequested = Signal(str)
    menuRequested = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setItemDelegate(LibraryDelegate(self))

    def drawBranches(self, painter, rect, index):
        pass

    def mousePressEvent(self, event):
        row = self.itemAt(event.position().toPoint())
        if row and event.button() == Qt.MouseButton.LeftButton:
            rect = self.visualItemRect(row)
            kind, identifier = row.data(0, Qt.ItemDataRole.UserRole)
            depth, parent = 0, row.parent()
            while parent is not None:
                depth += 1
                parent = parent.parent()
            arrow_x = rect.x() + 12 + depth * 14
            if kind == 'folder' and arrow_x - 4 <= event.position().x() <= arrow_x + 12:
                row.setExpanded(not row.isExpanded())
                event.accept()
                return
            offset = rect.right() - event.position().x()
            if offset < 27:
                self.menuRequested.emit(row, self.viewport().mapToGlobal(event.position().toPoint()))
                return
            if kind == "folder" and offset < 52:
                self.newRequested.emit(identifier)
                return
        super().mousePressEvent(event)


class RecordingDialog(SurfaceDialog):
    def __init__(self, library, folder_id, parent):
        super().__init__('新建录音', '为这次聆听留一个位置。创建后，你可以再开始录音。', parent)
        layout = self.body
        layout.addWidget(text_label('本地保存 · 原文与译文自动记录', 'stepBadge'))
        layout.addSpacing(6)
        layout.addWidget(text_label("录音名称", 'settingsLabel'))
        self.name = QLineEdit(default_recording_name())
        self.name.setMaxLength(64)
        self.name.selectAll()
        self.name.setPlaceholderText('例如：第 02 讲 · 梯度与优化')
        layout.addWidget(self.name)
        layout.addWidget(text_label("保存到文件夹", 'settingsLabel'))
        self.folder = QComboBox()
        for item in library.index["folders"]:
            self.folder.addItem(library.folder_label(item["id"]), item["id"])
        if not self.folder.count():
            self.folder.addItem('我的录音 · 创建录音时建立', None)
        self.folder.setCurrentIndex(max(0, self.folder.findData(folder_id)))
        layout.addWidget(self.folder)
        self.error = text_label("同名录音会自动添加序号，已有文件不会被覆盖。", "muted")
        layout.addWidget(self.error)
        buttons = self.actions
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        create = QPushButton("创建录音")
        create.setObjectName("primary")
        create.clicked.connect(lambda: self.validate(library))
        create.setDefault(True)
        create.setEnabled(bool(self.name.text().strip()) and self.folder.count() > 0)
        self.name.textChanged.connect(lambda value: create.setEnabled(bool(value.strip()) and self.folder.count() > 0))
        buttons.addWidget(create)
        self.name.setFocus()

    def validate(self, library):
        try:
            library.validate_name(self.name.text())
            if self.folder.currentData() is None and library.index['folders']:
                raise ValueError("请先创建文件夹。")
        except ValueError as exc:
            self.error.setText(str(exc))
            self.name.setProperty('invalid', True)
            self.name.style().polish(self.name)
            self.name.setFocus()
            return
        self.accept()


class SettingsWorkspace(QWidget):
    prepare_models_requested = Signal()
    back_requested = Signal()
    open_storage_requested = Signal()
    choose_storage_requested = Signal()
    deleted_requested = Signal()
    refresh_devices_requested = Signal()
    model_settings_changed = Signal()

    def __init__(self, frame_factory, *, storage_root, controls, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        self.sidebar = sidebar
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(14, 20, 14, 16)
        nav.setSpacing(14)
        back = QPushButton("←  返回录音")
        back.setObjectName("navigation")
        back.clicked.connect(self.back_requested.emit)
        nav.addWidget(back)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索设置…")
        self.search.setAccessibleName('搜索设置')
        self.search.setToolTip('搜索设置')
        self.search.setClearButtonEnabled(True)
        nav.addWidget(self.search)
        nav.addSpacing(12)
        nav.addWidget(text_label("工作空间", "section"))
        self.navigation = QListWidget()
        self.navigation.setMouseTracking(True)
        self.navigation.setObjectName("settingsNavigation")
        self.categories = ["常规", "聆听", "模型管理", "字幕与延迟", "运行环境", '使用指南']
        self.navigation.addItems(self.categories)
        nav.addWidget(self.navigation, 1)
        nav.addWidget(text_label("更改将用于下一次录音", "timestamp"))
        layout.addWidget(sidebar)
        right = frame_factory()
        right.setObjectName("workspace")
        outer = QVBoxLayout(right)
        self.right = right
        self.content_layout = outer
        outer.setContentsMargins(36, 44, 36, 24)
        self.title = text_label("常规", "settingsTitle")
        outer.addWidget(self.title)
        self.description = text_label(PAGE_DESCRIPTIONS['常规'], 'pageDescription')
        outer.addWidget(self.description)
        outer.addSpacing(10)
        self.pages = QStackedWidget()
        self.transition = PageTransition(self.pages)
        outer.addWidget(self.pages, 1)
        self.no_results = QWidget()
        empty_layout = QVBoxLayout(self.no_results)
        empty_layout.addStretch()
        empty_layout.addWidget(text_label('没有找到这个设置', 'dialogTitle'))
        empty_layout.addWidget(text_label('试试「字幕」「GPU」「保存位置」或「翻译」。', 'muted'))
        clear = QPushButton('清除搜索')
        clear.clicked.connect(self.search.clear)
        empty_layout.addWidget(clear, 0, Qt.AlignmentFlag.AlignLeft)
        empty_layout.addStretch()
        outer.addWidget(self.no_results, 1)
        self.no_results.hide()
        layout.addWidget(right, 1)
        self.mapping = {}
        general, body = self.page("常规")
        body.addWidget(text_label("文件与存储", "settingsSection"))
        card, rows = self.group()
        self.storage_path = text_label(str(storage_root), "muted")
        self.storage_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        storage_controls = QWidget()
        buttons = QHBoxLayout(storage_controls)
        buttons.setContentsMargins(0, 0, 0, 0)
        for title, callback in [("打开", self.open_storage_requested.emit), ("更改…", self.choose_storage_requested.emit)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        self.row(rows, "录音保存位置", self.storage_path, storage_controls)
        self.set_storage_root(storage_root)
        deleted = QPushButton("查看最近删除")
        deleted.clicked.connect(self.deleted_requested.emit)
        self.row(rows, "最近删除", "删除的文件先保留在录音目录的「垃圾桶」文件夹，可随时恢复。", deleted)
        body.addWidget(card)
        body.addSpacing(24)
        body.addWidget(text_label("使用习惯", "settingsSection"))
        card, rows = self.group()
        self.row(rows, '外观', '白色或深色，切换后立即生效。', controls['appearance'])
        self.row(rows, '减少动态效果', '关闭平滑跟随、切页、弹窗和开关动画。', controls['reduce_motion'])
        self.row(rows, '体验 Beta 功能', '开启后显示课件解析、识别提示整理和课堂笔记入口。关闭会停止相关任务，已有资料保留。', controls['beta_features'])
        body.addWidget(card)
        body.addStretch()
        listening, body = self.page("聆听")
        self.listening_page = listening
        body.addWidget(text_label("输入与语言", "settingsSection"))
        card, rows = self.group()
        self.row(rows, "音频来源", "选择麦克风或正在播放声音的设备。", controls['device'])
        refresh = QPushButton("刷新设备")
        refresh.clicked.connect(self.refresh_devices_requested.emit)
        self.row(rows, "设备列表", "连接新设备后刷新。", refresh)
        self.row(rows, "原文语言", "Qwen 需要明确选择原文语言。", controls['source'])
        self.row(rows, "翻译语言", "选择定稿与实时译文使用的语言。", controls['target'])
        self.row(rows, "启用翻译", "开启本地翻译并保存译文；关闭后仅识别和保存原文。", controls['translate'])
        body.addWidget(card)
        body.addStretch()
        from .model_browser import ModelBrowser
        _, body = self.page('模型管理')
        from .model_options import asr_backends
        self.model_browser = ModelBrowser(manager.preparation_selection, manager.inventory_selection,
                                          asr_backends())
        manager.selection_changed.connect(lambda *_: self.model_browser.sync_roles())
        manager.session_changed.connect(self.model_browser.set_session_active)
        manager.preparation_changed.connect(self.model_browser.set_preparing)
        self.model_browser.deletion_changed.connect(manager.set_inventory_busy)
        self.model_browser.selected.connect(self.select_model)
        self.model_browser.assigned.connect(self.assign_model)
        model_settings = QHBoxLayout()
        self.download_model = QPushButton('下载模型…')
        self.download_model.clicked.connect(self.open_model_catalog)
        model_settings.addWidget(self.download_model)
        model_settings.addStretch()
        body.addLayout(model_settings)
        body.addWidget(self.model_browser, 1)
        prepare = QPushButton('检查 / 补齐当前模型')
        prepare.clicked.connect(self.prepare_models_requested.emit)
        prepare.setObjectName('primary')
        manager.register_preparation_button(prepare)
        body.addWidget(prepare, 0, Qt.AlignmentFlag.AlignLeft)
        _, body = self.page('使用指南')
        body.addWidget(text_label('第一次使用', 'settingsSection'))
        card, rows = self.group()
        for title, detail, category, action in [
            ('01  准备本地模型', '首次安装运行环境，再下载 / 检查识别模型；必要组件会一起准备。', '运行环境', '准备环境'),
            ('02  选择音频与语言', '选择麦克风或系统声音。使用 Qwen 时，指定原文语言。', '聆听', '设置聆听'),
            ('03  按需开启翻译', '选择翻译模型和目标语言；只需要原文时，可关闭翻译。', '模型管理', '设置翻译'),
        ]:
            button = QPushButton(action + '  →')
            button.clicked.connect(lambda checked=False, category=category:
                self.navigation.setCurrentRow(self.categories.index(category)))
            self.row(rows, title, detail, button)
        body.addWidget(card)
        body.addWidget(text_label('聆听中的文字会发生什么？', 'settingsSection'))
        body.addWidget(text_label('未提交  →  已提交，可修订  →  原文已定稿\n\n首次提交和已提交原文的变化立即排队初译，固定参考前后各 1 段已有的已定稿原文。识别段结束后原文独立定稿，再参考前 5 段、后 1 段已有的已定稿原文生成最终译文。相邻待译内容可以合并、共享背景；等待更新时保留已有译文并标注。翻译不阻挡原文更新，也不等待尚未出现的后文。暂停会停止收音并继续处理已有内容；点击“继续录音”可接着录，暂停时间不计入录音。停止聆听会处理剩余内容，请等待收尾完成。', 'infoBanner'))
        body.addWidget(text_label('录音结束以后', 'settingsSection'))
        body.addWidget(text_label('从侧栏打开录音，可回听音频或导出双语 SRT、TXT 和 Markdown。使用「···」重命名、移动或打开保存位置；删除的录音先进入「最近删除」，可在那里恢复。', 'muted'))
        body.addStretch()
        self.model_back = QPushButton('← 返回模型管理')
        self.model_back.setObjectName('modelBack')
        self.model_back.setMaximumWidth(230)
        self.model_back.clicked.connect(lambda: self.select(self.categories.index('模型管理')))
        self.model_back.hide()
        manager.embed_model_settings(self.model_back)
        outer.addWidget(manager.download_card)
        index = self.pages.addWidget(manager)
        self.manager_page = index
        for category in ["字幕与延迟", "运行环境"]:
            self.mapping[category] = index
        self.navigation.currentRowChanged.connect(self.select)
        self.search.textChanged.connect(self.filter)
        self.navigation.setCurrentRow(0)
        self.filter('')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sidebar.setFixedWidth(max(170, min(250, int(self.width() * .2))))
        margin = max(16 if self.width() < 850 else 24, (self.right.width() - 850) // 2)
        self.content_layout.setContentsMargins(margin, 32, margin, 24)

    def set_storage_root(self, root):
        self.storage_path.setText(str(root))

    def page(self, name):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(0, 12, 6, 12)
        body.setSpacing(16)
        scroll.setWidget(page)
        self.mapping[name] = self.pages.addWidget(scroll)
        return page, body

    @staticmethod
    def group():
        card = QFrame()
        card.setObjectName("settingsGroup")
        rows = QVBoxLayout(card)
        rows.setContentsMargins(20, 6, 20, 10)
        rows.setSpacing(0)
        return card, rows

    @staticmethod
    def row(rows, title, description, control):
        frame = QFrame()
        frame.setObjectName("settingsRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 20, 0, 20)
        row.setSpacing(20)
        words = QVBoxLayout()
        words.setSpacing(6)
        words.addWidget(text_label(title, "settingsLabel"))
        words.addWidget(description if isinstance(description, QWidget) else text_label(description, "muted"))
        row.addLayout(words, 1)
        control.setMaximumWidth(270)
        control.setMinimumWidth(0)
        if isinstance(control, Switch):
            control.setFixedSize(38, 24)
        if isinstance(control, QComboBox):
            control.setMinimumContentsLength(10)
            control.setFixedWidth(210)
        control.show()
        row.addWidget(control)
        rows.addWidget(frame)

    def select(self, index):
        if index < 0:
            return
        name = self.categories[index]
        self.title.setText(name)
        self.description.setText(PAGE_DESCRIPTIONS[name])
        entering = self.pages.currentIndex() != self.mapping[name]
        self.pages.setCurrentIndex(self.mapping[name])
        self.model_back.hide()
        tabs = {"字幕与延迟": 2, "运行环境": 3}
        if name in tabs:
            self.manager.show_section(tabs[name])
        if name == "模型管理" and entering:
            self.model_browser.refresh()
        self.transition.start()

    def assign_model(self, entry):
        self.manager.assign_model(entry)

    def select_model(self, entry):
        if not entry:
            return
        self.open_model_settings(entry['kind'], entry=entry)

    def open_model_settings(self, kind, *, entry=None):
        from .model_dialog import ModelDialog
        dialog = ModelDialog(self.manager.model_settings_snapshot(), kind=kind, entry=entry, parent=self)
        self.manager.preparation_changed.connect(dialog.set_preparing)
        self.manager.inventory_changed.connect(dialog.set_inventory_busy)
        dialog.applied.connect(self.apply_model_settings)
        dialog.download_requested.connect(lambda selection, only: self.manager.prepare_selected(selection, only=only))
        dialog.open()
        return dialog

    def open_model_catalog(self):
        from .model_dialog import ModelCatalogDialog
        dialog = ModelCatalogDialog(self.manager.model_settings_snapshot(), parent=self)
        self.manager.preparation_changed.connect(dialog.set_preparing)
        self.manager.inventory_changed.connect(dialog.set_inventory_busy)
        dialog.bundle_selected.connect(self.select_model_bundle)
        dialog.advanced_requested.connect(lambda: self.open_model_settings('asr').advanced_toggle.setChecked(True))
        dialog.download_requested.connect(lambda selection, only: self.manager.prepare_selected(selection, only=only))
        dialog.open()
        return dialog

    def select_model_bundle(self, selection):
        self.manager.apply_selection(selection)
        self.model_browser.sync_roles()
        self.model_settings_changed.emit()

    def apply_model_settings(self, values):
        self.manager.apply_model_settings(values)
        self.model_browser.sync_roles()
        self.model_settings_changed.emit()

    def filter(self, query):
        aliases = {"模型管理": "下载 缓存 删除 ASR 翻译 Qwen HY-MT2 Whisper 本地 参数 前文 后文 GPU CPU MLX NLLB", "常规": "文件 存储 目录 路径 删除 恢复 跟随", "聆听": "设备 输入 语言",
                   "识别模型": "Qwen Whisper GPU CPU MLX 下载", "翻译模型": "NLLB HY-MT2 前文 后文 GPU CPU 下载 译文",
                   "字幕与延迟": "字幕 草稿 刷新 停顿",
                   "运行环境": "安装 修复 更新 版本 GitHub", '使用指南': '首次 使用 帮助 入门 导出 SRT 开始 说明'}
        aliases['常规'] += ' 动画 减少动态效果'
        query = query.strip().casefold()
        visible = []
        for i, name in enumerate(self.categories):
            match = all(term in (name + ' ' + aliases[name] + ' ' + PAGE_DESCRIPTIONS[name]).casefold()
                        for term in query.split())
            self.navigation.item(i).setHidden(not match)
            if match:
                visible.append(i)
        if visible and self.navigation.currentRow() not in visible:
            self.navigation.setCurrentRow(visible[0])
        self.pages.setVisible(bool(visible))
        self.no_results.setVisible(not visible)
        if not visible:
            self.title.setText('搜索设置')
            self.description.setText('没有与「' + query + '」匹配的设置。')
        elif self.navigation.currentRow() in visible:
            self.select(self.navigation.currentRow())
