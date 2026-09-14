"""Quiet navigation, explicit recording creation and the full-page settings view."""

from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
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


def text_label(text, name=None):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        label.setObjectName(name)
    return label


class Switch(QCheckBox):
    def __init__(self, text=""):
        super().__init__(text)
        self.setAccessibleName(text)
        self.setFixedSize(38, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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
        painter.drawEllipse(QRectF(19 if self.isChecked() else 3, 5, 16, 16))


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


class RecordingDialog(QDialog):
    def __init__(self, library, folder_id, parent):
        super().__init__(parent)
        self.setWindowTitle("新建录音")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(text_label("新建录音", "title"))
        layout.addWidget(text_label("先起个名字，稍后开始聆听。", "muted"))
        layout.addSpacing(8)
        layout.addWidget(text_label("录音名称"))
        self.name = QLineEdit(datetime.now().strftime("录音 %m月%d日 %H时%M分"))
        self.name.setMaxLength(64)
        self.name.selectAll()
        layout.addWidget(self.name)
        layout.addWidget(text_label("保存到文件夹"))
        self.folder = QComboBox()
        for item in library.index["folders"]:
            self.folder.addItem(library.folder_label(item["id"]), item["id"])
        self.folder.setCurrentIndex(max(0, self.folder.findData(folder_id)))
        layout.addWidget(self.folder)
        self.error = text_label("同名录音会自动添加序号，已有文件不会被覆盖。", "muted")
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        create = QPushButton("创建录音")
        create.setObjectName("primary")
        create.clicked.connect(lambda: self.validate(library))
        create.setDefault(True)
        buttons.addWidget(create)
        layout.addLayout(buttons)

    def validate(self, library):
        try:
            library.validate_name(self.name.text())
            if self.folder.currentData() is None:
                raise ValueError("请先创建文件夹。")
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class SettingsWorkspace(QWidget):
    def __init__(self, host, frame_factory):
        super().__init__()
        self.host = host
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
        back.clicked.connect(host.leave_settings)
        nav.addWidget(back)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索设置…")
        self.search.setClearButtonEnabled(True)
        nav.addWidget(self.search)
        nav.addSpacing(12)
        nav.addWidget(text_label("工作空间", "section"))
        self.navigation = QListWidget()
        self.navigation.setObjectName("settingsNavigation")
        self.categories = ["常规", "聆听", "识别模型", "翻译模型", "字幕与延迟", "音频处理", "运行环境"]
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
        outer.addSpacing(18)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        layout.addWidget(right, 1)
        self.mapping = {}
        general, body = self.page("常规")
        body.addWidget(text_label("文件与存储", "settingsSection"))
        card, rows = self.group()
        self.storage_path = text_label(str(host.library.root), "muted")
        self.storage_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        controls = QWidget()
        buttons = QHBoxLayout(controls)
        buttons.setContentsMargins(0, 0, 0, 0)
        for title, callback in [("打开", host.reveal_library), ("更改…", host.choose_library)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        self.row(rows, "录音保存位置", "录音与定稿按文件夹、录音名称保存，随时可以直接打开。", controls)
        rows.addWidget(self.storage_path)
        deleted = QPushButton("查看最近删除")
        deleted.clicked.connect(host.show_deleted)
        self.row(rows, "最近删除", "删除的文件先保留在原保存目录，可随时恢复。", deleted)
        body.addWidget(card)
        body.addSpacing(24)
        body.addWidget(text_label("使用习惯", "settingsSection"))
        card, rows = self.group()
        self.row(rows, "跟随最新字幕", "新文字出现时，自动滚动到最新位置。", host.follow)
        body.addWidget(card)
        body.addStretch()
        listening, body = self.page("聆听")
        host.settings_panel = listening
        body.addWidget(text_label("输入与语言", "settingsSection"))
        card, rows = self.group()
        self.row(rows, "音频来源", "选择麦克风或正在播放声音的设备。", host.device)
        refresh = QPushButton("刷新设备")
        refresh.clicked.connect(host.refresh_devices)
        self.row(rows, "设备列表", "连接新设备后刷新。", refresh)
        self.row(rows, "原文语言", "Qwen 需要明确选择原文语言。", host.source)
        self.row(rows, "翻译语言", "选择定稿与实时译文使用的语言。", host.target)
        self.row(rows, "显示翻译", "关闭后仅保存原文字幕与录音。", host.translate)
        body.addWidget(card)
        body.addStretch()
        _, body = self.page("音频处理")
        body.addWidget(text_label("增强与回听", "settingsSection"))
        card, rows = self.group()
        lab = QPushButton("打开音频实验室")
        lab.clicked.connect(host.manage_audio)
        self.row(rows, "音频实验室", "先回听，再调整降噪、去混响与响度。", lab)
        rows.addWidget(host.audio_summary)
        body.addWidget(card)
        body.addStretch()
        self.audio_page = self.pages.widget(self.mapping["音频处理"])
        manager = host.model_manager
        manager.setWindowFlags(Qt.WindowType.Widget)
        manager.tabs.tabBar().hide()
        manager.done_button.hide()
        manager.cancel_button.setVisible(manager.worker is not None)
        manager.setObjectName("embeddedModels")
        manager.setStyleSheet("QDialog#embeddedModels { background: transparent; } QTabWidget::pane { border: none; }")
        for form in manager.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setVerticalSpacing(18)
            form.setHorizontalSpacing(24)
            form.setContentsMargins(18, 18, 18, 18)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for row in range(form.rowCount()):
                field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if field and field.widget() and isinstance(field.widget(), (QComboBox, QAbstractSpinBox, QCheckBox)):
                    field.widget().setMaximumWidth(320)
                    form.setAlignment(field.widget(), Qt.AlignmentFlag.AlignRight)
        for button in manager.findChildren(QPushButton):
            button.setMaximumWidth(340)
            if button.parentWidget().layout():
                button.parentWidget().layout().setAlignment(button, Qt.AlignmentFlag.AlignRight)
        for tab in range(manager.tabs.count()):
            page = manager.tabs.widget(tab).widget()
            page.setObjectName("modelSettingsGroup")
            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        for hint in manager.findChildren(QLabel):
            hint.setWordWrap(True)
            if hint.wordWrap():
                hint.setStyleSheet("font-size: 12px; color: #aaaab0; border: none;")
        index = self.pages.addWidget(manager)
        for category in ["识别模型", "翻译模型", "字幕与延迟", "运行环境"]:
            self.mapping[category] = index
        self.navigation.currentRowChanged.connect(self.select)
        self.search.textChanged.connect(self.filter)
        self.navigation.setCurrentRow(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sidebar.setFixedWidth(max(220, min(250, int(self.width() * .2))))
        margin = max(24, (self.right.width() - 1000) // 2)
        self.content_layout.setContentsMargins(margin, 40, margin, 24)

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
        self.pages.setCurrentIndex(self.mapping[name])
        tabs = {"识别模型": 0, "翻译模型": 1, "字幕与延迟": 2, "运行环境": 3}
        if name in tabs:
            self.host.model_manager.tabs.setCurrentIndex(tabs[name])

    def filter(self, query):
        aliases = {"常规": "文件 存储 目录 路径 删除 恢复 跟随", "聆听": "设备 输入 语言",
                   "识别模型": "Qwen Whisper GPU CPU 下载", "翻译模型": "NLLB 下载 译文",
                   "字幕与延迟": "分句 草稿 刷新 停顿", "音频处理": "降噪 响度 增强 回听",
                   "运行环境": "安装 修复"}
        visible = []
        for i, name in enumerate(self.categories):
            match = query.casefold() in (name + " " + aliases[name]).casefold()
            self.navigation.item(i).setHidden(not match)
            if match:
                visible.append(i)
        if visible and self.navigation.currentRow() not in visible:
            self.navigation.setCurrentRow(visible[0])
        self.pages.setVisible(bool(visible))
        if not visible:
            self.title.setText("没有匹配的设置")
        elif self.navigation.currentRow() in visible:
            self.select(self.navigation.currentRow())
