"""Settings model list; inspection and deletion use owned background processes."""
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ModelBrowser(QWidget):
    selected = Signal(dict)
    changed = Signal()
    assigned = Signal(dict)
    deletion_changed = Signal(bool)

    def __init__(self, selection, selected_models, supported_backends, parent=None):
        super().__init__(parent)
        self.selection = selection
        self.supported_backends = supported_backends
        self.preparing = False
        self.session_active = False
        self.selected_models = selected_models
        self.start_check = None
        self.entries = []
        self.busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        from .ui_components import ChoiceBox
        roles = QFormLayout()
        self.role_choices = {}
        for kind, title in [('asr', '语音识别'), ('translation', '翻译')]:
            choice = ChoiceBox()
            choice.setMinimumContentsLength(22)
            choice.setSizeAdjustPolicy(ChoiceBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            choice.activated.connect(lambda index, kind=kind: self.choose_role(kind, index))
            self.role_choices[kind] = choice
            roles.addRow(title, choice)
        layout.addLayout(roles)
        self.status = QLabel('查看已下载的识别与翻译模型。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.list = QListWidget()
        self.list.setObjectName('modelInventory')
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemDoubleClicked.connect(lambda _: self.open_selected())
        self.list.currentItemChanged.connect(lambda *_: self.update_actions())
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.refresh_button = QPushButton('刷新')
        self.refresh_button.clicked.connect(self.refresh)
        self.open_button = QPushButton('参数设置 →')
        self.open_button.setObjectName('accentAction')
        self.open_button.clicked.connect(self.open_selected)
        self.delete_button = QPushButton('删除模型')
        self.delete_button.setObjectName('danger')
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.refresh_button, self.open_button, self.delete_button):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.sync_roles()
        self.update_actions()

    def set_preparing(self, active):
        self.preparing = active
        self.update_actions()
        if not active:
            self.refresh()

    def set_session_active(self, active):
        self.session_active = active
        self.update_actions()

    def sync_roles(self):
        """Inventory refresh never changes the saved model selection."""
        selection = self.selection()
        selected = {'asr': (selection['backend'], selection['asr_model']),
                    'translation': (selection['translation_engine'], selection['translation_model'])}
        for kind, choice in self.role_choices.items():
            choice.blockSignals(True)
            choice.clear()
            engine, path = selected[kind]
            choice.addItem(path.rsplit('/', 1)[-1] + ' · 当前', None)
            choice.setToolTip(path + '\n修改用于下一次聆听。')
            for entry in self.entries:
                if entry['kind'] != kind or (kind == 'asr' and entry['engine'] not in self.supported_backends):
                    continue
                if entry['path'] == path and entry['engine'] == engine:
                    choice.setItemText(0, entry['name'])
                else:
                    choice.addItem(entry['name'], entry)
            choice.setCurrentIndex(0)
            choice.blockSignals(False)

    def choose_role(self, kind, index):
        entry = self.role_choices[kind].itemData(index)
        if entry:
            self.assigned.emit(entry)
            self.status.setText('模型选择已保存，下次开始聆听生效。')

    def current(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def update_actions(self):
        entry = self.current()
        self.refresh_button.setEnabled(not self.busy)
        self.open_button.setEnabled(bool(entry and entry['kind'] != 'alignment') and not self.busy)
        locked = self.busy or self.preparing or self.session_active
        self.delete_button.setEnabled(bool(entry and entry['deletable']) and not locked)
        self.delete_button.setToolTip('录音或下载期间不能删除模型。' if locked else
                                      '自选目录请在文件管理器中处理；这里只删除应用管理的模型缓存。')

    def request(self, identifier=None):
        if self.busy or self.start_check is None:
            return
        self.busy = True
        self.deletion_changed.emit(bool(identifier))
        self.status.setText('正在删除模型…' if identifier else '正在读取本地模型…')
        self.update_actions()
        arguments = ['--selected', json.dumps(self.selected_models(), ensure_ascii=False)]
        if identifier:
            arguments += ['--delete', identifier]
        job = self.start_check('linguaflow.model_inventory', self.receive, *arguments)
        # Large caches may need more than the short-check deadline to delete.
        if identifier and job is not None:
            job.timeout.start(300000)

    def receive(self, result):
        self.busy = False
        self.deletion_changed.emit(False)
        if not isinstance(result, dict) or 'error' in result:
            self.status.setText(result.get('error', '读取模型未完成，请刷新重试。') if isinstance(result, dict)
                                else '读取模型未完成，请刷新重试。')
        else:
            self.entries = result.get('models', [])
            self.list.clear()
            for entry in self.entries:
                kind = {'asr': '识别', 'translation': '翻译', 'alignment': '时间对齐 · 当前流程未使用'}.get(entry['kind'], '模型')
                item = QListWidgetItem(f"{kind}  ·  {entry['name']}\n{entry['size'] / 1024**3:.2f} GB")
                item.setToolTip(entry['path'])
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self.list.addItem(item)
            self.status.setText('选择模型查看参数；双击也可打开。' if self.entries else
                                '还没有下载模型。请先准备识别与翻译模型。')
            if self.entries:
                self.list.setCurrentRow(0)
            self.sync_roles()
            self.changed.emit()
        self.update_actions()

    def refresh(self):
        self.request()

    def open_selected(self):
        if entry := self.current():
            if entry["kind"] == "alignment":
                self.status.setText("此模型用于时间戳对齐，当前识别流程不加载它，不能选作识别模型。")
                return
            if entry["kind"] == "asr" and entry["engine"] not in self.supported_backends:
                self.status.setText("这个识别模型的引擎不适用于当前平台。")
                return
            self.selected.emit(entry)

    def delete_selected(self):
        self.update_actions()
        entry = self.current()
        if not entry or not self.delete_button.isEnabled():
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle('删除模型')
        dialog.setText(f"删除 {entry['name']}？")
        dialog.setInformativeText('删除后需要重新下载才能使用；录音与字幕会保留。\n' + entry['id'])
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        def confirmed():
            self.update_actions()
            if dialog.standardButton(dialog.clickedButton()) == QMessageBox.StandardButton.Yes and self.delete_button.isEnabled():
                self.request(entry['id'])
            dialog.deleteLater()
        dialog.finished.connect(confirmed)
        dialog.open()
