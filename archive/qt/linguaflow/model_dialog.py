"""One draft editor for model inspection, selection and explicit downloads."""
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .llama_assets import hub_gguf
from .model_options import (
    asr_backends,
    asr_devices,
    download_catalog,
    recommended_selection,
    translation_devices,
)
from .model_options import (
    model_catalog as catalog,
)
from .qt_controls import text_label
from .translation_models import HY_GENERATION, NLLB_GENERATION
from .ui_components import ChoiceBox, SurfaceDialog
from .ui_components import DoubleSpinBox as QDoubleSpinBox

ENGINE_LABELS = {'wlk-whisper': 'WhisperLiveKit · Whisper / AlignAtt',
                 'qwen3-streaming': 'WhisperLiveKit · Qwen3-ASR / PyTorch',
                 'qwen3-mlx': 'Qwen3-ASR · MLX（试验）',
                 'pytorch': 'PyTorch', 'llama': 'llama.cpp · GGUF'}


class ModelDialog(SurfaceDialog):
    applied = Signal(dict)
    download_requested = Signal(dict, str)

    def __init__(self, snapshot, *, kind='asr', entry=None, parent=None):
        super().__init__(entry['name'] if entry else '模型设置',
                         '点击使用后，用于下一次聆听。', parent)
        self.original = snapshot['selection'].copy()
        self.asr_device = snapshot['asr_device']
        self.inventory_busy = snapshot['inventory_busy']
        self.entry = entry
        self.setMinimumWidth(min(620, self.screen().availableGeometry().width()-48))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(300)
        scroll.setMaximumHeight(max(300, min(480, self.screen().availableGeometry().height()-230)))
        self.scroll = scroll
        content = QWidget()
        scroll.setWidget(content)
        self.body.addWidget(scroll)
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(0, 4, 8, 4)
        self.body.setSpacing(12)
        self.kind = ChoiceBox()
        self.kind.addItem('语音识别', 'asr')
        self.kind.addItem('翻译', 'translation')
        self.kind.setCurrentIndex(self.kind.findData(kind))
        self.kind.setEnabled(entry is None)
        self.engine = ChoiceBox()
        self.model = ChoiceBox()
        self.model.setEditable(True)
        self.model.setMinimumContentsLength(24)
        self.model.setSizeAdjustPolicy(ChoiceBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device = ChoiceBox()
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.addRow('用途', self.kind)
        self.form.addRow('对应引擎', self.engine)
        self.form.addRow('模型 / 下载地址', self.model)
        self.form.addRow('计算设备', self.device)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.addLayout(self.form)
        if entry:
            self.body.addWidget(text_label(f"本地文件 · {entry['size']/1024**3:.2f} GB", 'settingsLabel'))
            location = text_label(entry['path'], 'muted')
            location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.body.addWidget(location)
        self.hint = text_label('', 'muted')
        advanced_layout.addWidget(self.hint)
        self.parameters = {}
        self.parameter_labels = {}
        for name, title in [('draft_seconds', '草稿刷新目标'), ('update_seconds', '音频合并间隔'),
                            ('endpoint_seconds', '停顿检测阈值')]:
            original = snapshot['parameters'][name]
            control = QDoubleSpinBox()
            control.setRange(original['minimum'], original['maximum'])
            control.setSingleStep(original['step'])
            control.setValue(original['value'])
            control.setSuffix(' 秒')
            control.setToolTip(original['tooltip'])
            label = text_label(title, 'settingsLabel')
            label.setToolTip(original['tooltip'])
            self.form.addRow(label, control)
            self.parameters[name], self.parameter_labels[name] = control, label
        self.translation_parameters = text_label(
            f"生成参数 · 最大 {HY_GENERATION['max_new_tokens']} tokens · 温度 {HY_GENERATION['temperature']}"
            f" · top-p {HY_GENERATION['top_p']} · top-k {HY_GENERATION['top_k']}\n"
            '初译参考前后各 1 段；定稿参考前 5 段、后 1 段。仅使用已有的定稿原文。', 'muted')
        advanced_layout.addWidget(self.translation_parameters)
        self.summary = text_label('', 'settingsLabel')
        self.body.addWidget(self.summary)
        self.advanced_toggle = QPushButton('高级设置…')
        self.advanced_toggle.setObjectName('quiet')
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self.show_advanced)
        self.body.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(self.advanced)
        self.advanced.hide()
        self.error = text_label('', 'muted')
        self.error.hide()
        self.body.addWidget(self.error)
        self.body.addStretch()
        local = QPushButton('导入本地模型…')
        local.clicked.connect(self.choose_local)
        advanced_layout.addWidget(local, 0, Qt.AlignmentFlag.AlignLeft)
        self.actions.addStretch()
        self.download = QPushButton('下载模型')
        self.download.clicked.connect(self.request_download)
        advanced_layout.addWidget(self.download, 0, Qt.AlignmentFlag.AlignLeft)
        use = QPushButton('使用此模型')
        use.setObjectName('primary')
        use.clicked.connect(self.apply)
        self.actions.addWidget(use)
        self.kind.currentIndexChanged.connect(self.update_kind)
        self.engine.currentIndexChanged.connect(self.update_engine)
        self.model.currentTextChanged.connect(self.update_hint)
        self.update_kind()
        self.set_preparing(snapshot['preparing'])
        self.show_advanced(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def show_advanced(self, visible):
        self.advanced.setVisible(visible)
        self.advanced_toggle.setText('收起高级设置' if visible else '高级设置…')
        self.scroll.setMinimumHeight(300 if visible else 150)
        self.scroll.setMaximumHeight(max(300, min(480, self.screen().availableGeometry().height()-230)) if visible else 220)
        self.adjustSize()

    def set_preparing(self, active):
        self.preparing = active
        self.download.setEnabled(not active and not self.inventory_busy)
        self.download.setToolTip('请等待当前准备或删除任务完成。' if active or self.inventory_busy
                                else '只下载文件，不改变当前模型选择。')

    def set_inventory_busy(self, busy):
        self.inventory_busy = busy
        self.set_preparing(self.preparing)

    def update_kind(self):
        kind = self.kind.currentData()
        self.engine.blockSignals(True)
        self.engine.clear()
        for engine in asr_backends() if kind == 'asr' else ('pytorch', 'llama'):
            self.engine.addItem(ENGINE_LABELS[engine], engine)
        selected = self.entry['engine'] if self.entry else self.original['backend' if kind == 'asr' else 'translation_engine']
        self.engine.setCurrentIndex(max(0, self.engine.findData(selected)))
        self.engine.blockSignals(False)
        self.update_engine()
        model = self.entry['path'] if self.entry else self.original['asr_model' if kind == 'asr' else 'translation_model']
        index = self.model.findData(model)
        self.model.setCurrentIndex(index if index >= 0 else -1)
        if index < 0:
            self.model.setEditText(model)
        self.update_hint()

    def update_engine(self):
        engine = self.engine.currentData()
        self.model.clear()
        for title, value in catalog(engine):
            self.model.addItem(title, value)
        self.device.clear()
        devices = ('mlx',) if engine == 'qwen3-mlx' else (asr_devices() if self.kind.currentData() == 'asr'
                                                       else translation_devices(engine))
        for device in devices:
            self.device.addItem(device.upper(), device)
        selected = self.asr_device if self.kind.currentData() == 'asr' else self.original['translation_device']
        self.device.setCurrentIndex(max(0, self.device.findData(selected)))
        for name, control in self.parameters.items():
            visible = self.kind.currentData() == 'asr' and (name != 'draft_seconds' or engine != 'wlk-whisper')
            control.setVisible(visible)
            self.parameter_labels[name].setVisible(visible)
        self.update_hint()

    def model_value(self):
        index = self.model.currentIndex()
        # Editing a catalog label makes it a custom address, never the stale itemData.
        if index >= 0 and self.model.currentText() == self.model.itemText(index):
            return self.model.itemData(index) or self.model.currentText().strip()
        return self.model.currentText().strip()

    def update_hint(self):
        engine = self.engine.currentData()
        self.summary.setText(('语音识别' if self.kind.currentData() == 'asr' else '翻译') + ' · ' +
                             ENGINE_LABELS.get(engine, str(engine)))
        if engine == 'llama':
            text = ('Q4_K_M 是 4-bit 量化。可选目录中的版本，或输入 hf://作者/仓库/文件.gguf 下载。'
                    '自选 GGUF 需要兼容当前 llama.cpp 和翻译提示词；下载完成不等于推理已验收。')
        elif engine == 'qwen3-mlx':
            text = 'MLX 识别需要 Apple Silicon Mac；8-bit 尚待实机验收。'
        elif engine == 'qwen3-streaming':
            text = '使用 Qwen3-ASR 原始权重、兼容仓库 ID 或本地目录。当前 Windows 识别后端不支持 MLX 4-bit 权重。'
        elif engine == 'wlk-whisper':
            text = '选择 Whisper 模型大小，或导入兼容的原始 .pt 权重。'
        else:
            text = '选择 HY-MT2 / NLLB 模型，也可输入兼容仓库 ID 或本地目录。量化 GGUF 请切换到 llama.cpp。'
        self.hint.setText(text)
        hy = engine == 'llama' or 'hy-mt2' in self.model_value().lower()
        self.translation_parameters.setVisible(self.kind.currentData() == 'translation')
        self.translation_parameters.setText(
            f"HY-MT2 生成参数 · 最大 {HY_GENERATION['max_new_tokens']} tokens · 温度 {HY_GENERATION['temperature']}"
            f" · top-p {HY_GENERATION['top_p']} · top-k {HY_GENERATION['top_k']}"
            f" · 重复惩罚 {HY_GENERATION['repetition_penalty']}\n"
            '初译参考前后各 1 段；定稿参考前 5 段、后 1 段。仅使用已有的定稿原文。' if hy else
            f"NLLB 生成参数 · 最大 {NLLB_GENERATION['max_new_tokens']} tokens · beams {NLLB_GENERATION['num_beams']}\n"
            '逐段翻译；单段输入最多 512 tokens，超长时保留原文并提示。')

    def draft(self):
        model = self.model_value()
        if not model:
            raise ValueError('请选择模型或输入下载地址。')
        if self.engine.currentData() == 'llama' and model.startswith('hf://'):
            hub_gguf(model)
        if self.engine.currentData() == 'qwen3-streaming' and model.startswith('mlx-community/'):
            raise ValueError('MLX 权重需要 Apple Silicon Mac 的 MLX 引擎，当前引擎不能使用。')
        selection = self.original.copy()
        if self.kind.currentData() == 'asr':
            selection.update(backend=self.engine.currentData(), asr_model=model)
        else:
            selection.update(translation_engine=self.engine.currentData(), translation_model=model,
                             translation_device=self.device.currentData())
        return selection

    def choose_local(self):
        if self.engine.currentData() in ('llama', 'wlk-whisper'):
            path, _ = QFileDialog.getOpenFileName(self, '导入本地模型', '',
                'GGUF 模型 (*.gguf)' if self.engine.currentData() == 'llama' else 'Whisper 权重 (*.pt)')
        else:
            path = QFileDialog.getExistingDirectory(self, '导入模型目录')
        if path:
            self.model.setCurrentIndex(-1)
            self.model.setEditText(path)

    def request_download(self):
        try:
            selection = self.draft()
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.download_requested.emit(selection, self.kind.currentData())
        self.accept()

    def apply(self):
        try:
            selection = self.draft()
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.applied.emit(dict(kind=self.kind.currentData(), selection=selection, device=self.device.currentData(),
                               parameters={name: control.value() for name, control in self.parameters.items()}))
        self.accept()


class ModelCatalogDialog(SurfaceDialog):
    """A small curated catalogue; runtime settings stay in explicit advanced details."""
    download_requested = Signal(dict, str)
    bundle_selected = Signal(dict)
    advanced_requested = Signal()

    def __init__(self, snapshot, parent=None):
        super().__init__('下载模型', '选择模型即可下载，无需设置运行参数。已下载的模型会自动复用。', parent)
        self.original = snapshot['selection'].copy()
        self.inventory_busy = snapshot['inventory_busy']
        self.apple = sys.platform == 'darwin'
        self.system = sys.platform
        self.setMinimumWidth(min(620, self.screen().availableGeometry().width()-48))
        self.download_buttons = []
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(300)
        scroll.setMaximumHeight(min(430, self.screen().availableGeometry().height()-230))
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 6, 0)
        rows.setSpacing(0)
        scroll.setWidget(content)
        self.body.addWidget(scroll)
        items = download_catalog(self.system)
        for title, description, kind, engine, model in items:
            frame = QFrame()
            frame.setObjectName('settingsRow')
            row = QHBoxLayout(frame)
            row.setContentsMargins(0, 16, 0, 16)
            words = QVBoxLayout()
            words.setSpacing(5)
            words.addWidget(text_label(title, 'settingsLabel'))
            words.addWidget(text_label(description, 'muted'))
            row.addLayout(words, 1)
            button = QPushButton('下载')
            button.clicked.connect(lambda checked=False, kind=kind, engine=engine, model=model:
                                   self.request_download(kind, engine, model))
            row.addWidget(button)
            self.download_buttons.append(button)
            rows.addWidget(frame)
        rows.addStretch()
        scroll.setFixedHeight(min(len(items)*80 + 12, self.screen().availableGeometry().height()-330))
        if not self.apple:
            self.body.addWidget(text_label('Windows 的 Qwen 4-bit / 8-bit 识别尚未接入，当前提供原始版本。', 'muted'))
        self.error = text_label('', 'muted')
        self.error.hide()
        self.body.addWidget(self.error)
        self.body.addWidget(text_label('推荐组合', 'settingsSection'))
        self.body.addWidget(text_label(items[0][0] + '  +  ' + items[-1][0], 'settingsLabel'))
        self.body.addWidget(text_label('一次备齐识别和翻译，并设为下一次聆听使用的模型。', 'muted'))
        advanced = QPushButton('高级…')
        advanced.setObjectName('quiet')
        advanced.setToolTip('导入本地模型或设置自选模型')
        advanced.clicked.connect(self.open_advanced)
        self.actions.addWidget(advanced)
        self.actions.addStretch()
        bundle = QPushButton('下载并使用推荐组合')
        bundle.setObjectName('primary')
        bundle.clicked.connect(self.request_bundle)
        self.actions.addWidget(bundle)
        self.download_buttons.append(bundle)
        self.set_preparing(snapshot['preparing'])
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def open_advanced(self):
        self.reject()
        self.advanced_requested.emit()

    def set_preparing(self, active):
        self.preparing = active
        for button in self.download_buttons:
            button.setEnabled(not active and not self.inventory_busy)
            button.setToolTip('请等待当前准备或删除任务完成。' if active or self.inventory_busy else '')

    def set_inventory_busy(self, busy):
        self.inventory_busy = busy
        self.set_preparing(self.preparing)

    def selection_for(self, kind, engine, model):
        selection = self.original.copy()
        if kind == 'asr':
            selection.update(backend=engine, asr_model=model)
        else:
            # Reuse the user's device choice. CUDA/CPU remain valid for llama.cpp.
            selection.update(translation_engine=engine, translation_model=model)
            if selection['translation_device'] not in translation_devices(engine, 'darwin' if self.apple else 'win32'):
                raise ValueError('当前设备不适用于此模型，请在高级设置中选择对应设备。')
        return selection

    def request_download(self, kind, engine, model):
        try:
            selection = self.selection_for(kind, engine, model)
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.download_requested.emit(selection, kind)
        self.accept()

    def request_bundle(self):
        defaults = recommended_selection(self.system)
        try:
            selection = self.selection_for('translation', defaults['translation_engine'], defaults['translation_model'])
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        selection.update(backend=defaults['backend'], asr_model=defaults['asr_model'])
        self.bundle_selected.emit(selection)
        self.download_requested.emit(selection, '')
        self.accept()
