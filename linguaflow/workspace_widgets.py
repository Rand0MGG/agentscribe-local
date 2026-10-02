"""Quiet navigation, explicit recording creation and the full-page settings view."""

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QKeySequence, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
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

PAGE_DESCRIPTIONS = {
    '常规': '管理本地录音、保存位置和使用习惯。',
    '聆听': '从哪里听、听什么语言，以及你想看到的译文。',
    '识别模型': '把声音变成原文。选择引擎和计算设备，再准备模型。',
    '翻译模型': '提交后先看初译，识别定稿后再结合上下文生成最终译文。',
    '字幕与延迟': '让听写更连贯，让分句与定稿的节奏适合你。',
    '音频处理': '先听原声，再决定是否需要降噪、去混响或响度调整。',
    '运行环境': '首次使用时准备本地组件；遇到依赖问题时在这里修复。',
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
        painter.setBrush(QColor("#4277c8" if self.isChecked() else "#4b4b50"))
        painter.drawRoundedRect(QRectF(1, 3, 36, 20), 10, 10)
        painter.setBrush(QColor("#f7f7f9"))
        painter.drawEllipse(QRectF(3 + 16 * self.position, 5, 16, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor('#c5d2ed'))
            painter.drawRoundedRect(QRectF(.5, .5, 37, 23), 11, 11)


class LibraryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(200, 38)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            painter.setBrush(QColor(255, 255, 255, 22 if selected else 10))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(2, 2, -2, -2), 8, 8)
        depth, parent = 0, index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        x = option.rect.x() + 12 + depth * 14
        # All levels use the same neutral, narrow rounded marker.
        painter.setBrush(QColor("#d1d1d6" if selected else "#68686f"))
        painter.drawRoundedRect(QRectF(x, option.rect.center().y() - 7, 3, 14), 1.5, 1.5)
        painter.setFont(option.font)
        painter.setPen(QColor("#eeeeef" if selected else "#bdbdc3"))
        rect = option.rect.adjusted(x - option.rect.x() + 13, 0, -53, 0)
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
        kind, _ = index.data(Qt.ItemDataRole.UserRole)
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
            if self.folder.currentData() is None:
                raise ValueError("请先创建文件夹。")
        except ValueError as exc:
            self.error.setText(str(exc))
            self.name.setProperty('invalid', True)
            self.name.style().polish(self.name)
            self.name.setFocus()
            return
        self.accept()


class SettingsWorkspace(QWidget):
    back_requested = Signal()
    open_storage_requested = Signal()
    choose_storage_requested = Signal()
    deleted_requested = Signal()
    refresh_devices_requested = Signal()
    audio_requested = Signal()

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
        self.search.setToolTip('搜索设置 · ' + QKeySequence('Ctrl+F').toString(QKeySequence.SequenceFormat.NativeText))
        self.search.setClearButtonEnabled(True)
        nav.addWidget(self.search)
        nav.addSpacing(12)
        nav.addWidget(text_label("工作空间", "section"))
        self.navigation = QListWidget()
        self.navigation.setObjectName("settingsNavigation")
        self.categories = ["常规", "聆听", "识别模型", "翻译模型", "字幕与延迟", "音频处理", "运行环境", '使用指南']
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
        empty_layout.addWidget(text_label('试试「SaT」「GPU」「保存位置」或「翻译」。', 'muted'))
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
        self.row(rows, "录音保存位置", "录音与定稿按文件夹、录音名称保存，随时可以直接打开。", storage_controls)
        rows.addWidget(self.storage_path)
        deleted = QPushButton("查看最近删除")
        deleted.clicked.connect(self.deleted_requested.emit)
        self.row(rows, "最近删除", "删除的文件先保留在原保存目录，可随时恢复。", deleted)
        body.addWidget(card)
        body.addSpacing(24)
        body.addWidget(text_label("使用习惯", "settingsSection"))
        card, rows = self.group()
        rows.addWidget(text_label('字幕停留在底部时自动跟随；向上翻阅会暂停。点击字幕区的向下箭头可回到最新位置。', 'infoBanner'))
        self.row(rows, '减少动态效果', '关闭平滑跟随、切页、弹窗和开关动画。', controls['reduce_motion'])
        body.addWidget(card)
        shortcuts = '    ·    '.join(
            QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText) + '  ' + title
            for key, title in [('Ctrl+,', '打开设置'), ('Ctrl+N', '新录音'), ('Escape', '返回录音')])
        body.addWidget(text_label('键盘操作    ' + shortcuts, 'infoBanner'))
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
        self.row(rows, "显示翻译", "关闭后仅保存原文字幕与录音。", controls['translate'])
        body.addWidget(card)
        body.addStretch()
        _, body = self.page("音频处理")
        body.addWidget(text_label("增强与回听", "settingsSection"))
        card, rows = self.group()
        lab = QPushButton("打开音频实验室")
        lab.clicked.connect(self.audio_requested.emit)
        self.row(rows, "音频实验室", "先回听，再调整降噪、去混响与响度。", lab)
        rows.addWidget(controls['audio_summary'])
        body.addWidget(card)
        body.addStretch()
        self.audio_page = self.pages.widget(self.mapping["音频处理"])
        _, body = self.page('使用指南')
        body.addWidget(text_label('第一次使用', 'settingsSection'))
        card, rows = self.group()
        for title, detail, category, action in [
            ('01  准备本地模型', '首次安装运行环境，下载识别模型，并准备必需的 SaT 分句模型。', '运行环境', '准备环境'),
            ('02  选择音频与语言', '选择麦克风或系统声音。使用 Qwen 时，指定原文语言。', '聆听', '设置聆听'),
            ('03  按需开启翻译', '选择翻译模型和目标语言；只需要原文时，可关闭显示翻译。', '翻译模型', '设置翻译'),
        ]:
            button = QPushButton(action + '  →')
            button.clicked.connect(lambda checked=False, category=category:
                self.navigation.setCurrentRow(self.categories.index(category)))
            self.row(rows, title, detail, button)
        body.addWidget(card)
        body.addWidget(text_label('聆听中的文字会发生什么？', 'settingsSection'))
        body.addWidget(text_label('未提交  →  已提交，可修订  →  原文已定稿\n\n首次提交和已提交原文的变化立即排队初译，默认参考前 1 段已定稿原文。识别段结束后原文独立定稿，再参考前 10 段已定稿原文生成最终译文。相邻待译内容可以合并、共享背景；等待更新时保留已有译文并标注。翻译不阻挡原文更新，也不等待尚未出现的后文。暂停会停止收音并继续处理已有内容；点击“继续录音”可接着录，暂停时间不计入录音。停止聆听会处理剩余内容，请等待收尾完成。', 'infoBanner'))
        body.addWidget(text_label('录音结束以后', 'settingsSection'))
        body.addWidget(text_label('从侧栏打开录音，可回听音频或导出双语 SRT。使用「···」重命名、移动或打开保存位置；删除的录音先进入「最近删除」，可在那里恢复。', 'muted'))
        body.addStretch()
        manager.setWindowFlags(Qt.WindowType.Widget)
        manager.tabs.tabBar().hide()
        manager.done_button.hide()
        manager.cancel_button.setVisible(manager.worker is not None)
        manager.setObjectName("embeddedModels")
        manager.setStyleSheet("QDialog#embeddedModels { background: transparent; } QTabWidget::pane { border: none; }")
        manager.layout().setContentsMargins(0, 0, 0, 0)
        manager.layout().setSpacing(14)
        for form in manager.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setAlignment(Qt.AlignmentFlag.AlignTop)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setVerticalSpacing(16)
            form.setHorizontalSpacing(24)
            form.setContentsMargins(18, 18, 18, 18)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for row in range(form.rowCount()):
                field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if field and field.widget() and isinstance(field.widget(), (QComboBox, QAbstractSpinBox)):
                    field.widget().setMaximumWidth(380)
                    field.widget().setMinimumWidth(170)
        for button in manager.findChildren(QPushButton):
            button.setMaximumWidth(340)
            if button.parentWidget().layout():
                button.parentWidget().layout().setAlignment(button, Qt.AlignmentFlag.AlignLeft)
        for tab in range(manager.tabs.count()):
            scroll = manager.tabs.widget(tab)
            page = scroll.takeWidget()
            page.setObjectName("modelSettingsGroup")
            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            wrapper = QWidget()
            column = QVBoxLayout(wrapper)
            column.setContentsMargins(0, 0, 6, 0)
            column.addWidget(page)
            column.addStretch()
            scroll.setWidget(wrapper)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for hint in manager.findChildren(QLabel):
            hint.setWordWrap(True)
            if hint.objectName() not in ('settingsSection', 'preparationStatus'):
                hint.setObjectName('settingsHint')
        for subsection in (manager.whisper_page, manager.qwen_page):
            subsection.setObjectName('modelSubsection')
            subsection.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        index = self.pages.addWidget(manager)
        for category in ["识别模型", "翻译模型", "字幕与延迟", "运行环境"]:
            self.mapping[category] = index
        self.navigation.currentRowChanged.connect(self.select)
        self.search.textChanged.connect(self.filter)
        self.navigation.setCurrentRow(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sidebar.setFixedWidth(max(220, min(250, int(self.width() * .2))))
        margin = max(24, (self.right.width() - 850) // 2)
        self.content_layout.setContentsMargins(margin, 32, margin, 24)

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
        words.addWidget(text_label(description, "muted"))
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
        self.pages.setCurrentIndex(self.mapping[name])
        tabs = {"识别模型": 0, "翻译模型": 1, "字幕与延迟": 2, "运行环境": 3}
        if name in tabs:
            self.manager.tabs.setCurrentIndex(tabs[name])
        self.transition.start()

    def filter(self, query):
        aliases = {"常规": "文件 存储 目录 路径 删除 恢复 跟随", "聆听": "设备 输入 语言",
                   "识别模型": "Qwen Whisper GPU CPU MLX 下载", "翻译模型": "NLLB HY-MT2 前文 后文 GPU CPU 下载 译文",
                   "字幕与延迟": "SaT 分句 草稿 刷新 停顿", "音频处理": "降噪 响度 增强 回听",
                   "运行环境": "安装 修复", '使用指南': '首次 使用 帮助 入门 导出 SRT 开始 说明'}
        aliases['常规'] += ' 动画 减少动态效果 快捷键'
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
