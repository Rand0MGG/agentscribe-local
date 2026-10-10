"""Model preparation lives outside the listening flow."""
import json

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .model_options import asr_backends, qwen_models, translation_devices
from .preparation_task import Preparation
from .qt_controls import text_label
from .runtime_paths import installation_command
from .translation_config import CONTEXT_COUNTS
from .ui_components import ChoiceBox as QComboBox
from .ui_components import set_download_progress


class ModelManager(QDialog):
    selection_changed = Signal(dict)
    diagnostic = Signal(str)
    session_changed = Signal(bool)
    update_checked = Signal(dict)
    preparation_changed = Signal(bool)
    preparation_message = Signal(str)
    download_changed = Signal(dict)

    def __init__(self, parent=None, *, compute_device=lambda: "cpu"):
        super().__init__(parent)
        self.compute_device = compute_device
        self.setWindowTitle("模型管理 · 准备一次，随后直接聆听")
        self.resize(660, 640)
        self.worker = None
        self.close_requested = False
        self.session_active = False
        self.inventory_busy = False
        self.consolidated = False
        self.start_check = None
        self.update_busy = False
        self.preparation_buttons = []
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.backend = QComboBox()
        backend_labels = {'wlk-whisper': 'WhisperLiveKit · Whisper / AlignAtt',
                          'qwen3-streaming': 'WhisperLiveKit · Qwen3-ASR 流式',
                          'qwen3-mlx': 'Qwen3-ASR · MLX 4-bit（试验）'}
        for backend in asr_backends():
            self.backend.addItem(backend_labels[backend], backend)
        self.asr_page = QWidget()
        self.asr_form = QFormLayout(self.asr_page)
        self.asr_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.asr_form.addRow(text_label('识别引擎与设备', 'settingsSection'))
        self.asr_form.addRow("聆听引擎", self.backend)
        self.whisper_page = QWidget()
        self.whisper_form = QFormLayout(self.whisper_page)
        self.whisper_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.qwen_page = QWidget()
        self.qwen_form = QFormLayout(self.qwen_page)
        self.qwen_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.asr_form.addRow(self.whisper_page)
        self.asr_form.addRow(self.qwen_page)
        self.add_page(self.asr_page, "识别模型")
        self.translation_page = QWidget()
        self.translation_form = QFormLayout(self.translation_page)
        self.translation_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.add_page(self.translation_page, "翻译模型")
        advanced = QWidget()
        self.advanced_form = QFormLayout(advanced)
        self.hint(self.advanced_form, '沿用当前识别参数。以下时间是请求与停顿检测目标，不是动态窗口长度，也不保证实际刷新速度。')
        self.advanced_toggle = QPushButton('显示高级参数')
        self.advanced_toggle.setCheckable(True)
        self.advanced_form.addRow(self.advanced_toggle)
        self.advanced_parameters = QWidget()
        parameter_form = QFormLayout(self.advanced_parameters)
        self.advanced_parameters.hide()
        self.advanced_form.addRow(self.advanced_parameters)
        self.advanced_toggle.toggled.connect(self.advanced_parameters.setVisible)
        self.advanced_toggle.toggled.connect(lambda enabled:
            self.advanced_toggle.setText('收起高级参数' if enabled else '显示高级参数'))
        self.update_seconds = QDoubleSpinBox()
        self.update_seconds.setRange(0.5, 3)
        self.update_seconds.setSingleStep(0.5)
        self.update_seconds.setValue(1)
        self.update_seconds.setSuffix(" 秒")
        self.endpoint_seconds = QDoubleSpinBox()
        self.endpoint_seconds.setRange(0.5, 3)
        self.endpoint_seconds.setSingleStep(0.5)
        self.endpoint_seconds.setValue(0.5)
        self.endpoint_seconds.setSuffix(" 秒")
        parameter_form.addRow("音频合并间隔", self.update_seconds)
        self.update_seconds.setToolTip("请求识别前合并新音频的目标；当草稿刷新目标更短时优先采用草稿目标。不是上下文窗口长度，也不是承诺的字幕刷新频率。")
        self.draft_seconds = QDoubleSpinBox()
        self.draft_seconds.setRange(.25, 3.)
        self.draft_seconds.setSingleStep(.25)
        self.draft_seconds.setValue(.5)
        self.draft_seconds.setSuffix(" 秒")
        self.draft_seconds.setToolTip("更小值更早请求原文草稿，也会增加计算量。实际更新受模型速度限制，可能一次出现几个词；不使用假打字动画。草稿优先于较长的音频合并间隔。")
        parameter_form.addRow("Qwen 原文草稿刷新目标", self.draft_seconds)
        parameter_form.addRow("ASR 停顿检测（不直接定稿）", self.endpoint_seconds)
        self.endpoint_seconds.setToolTip("Qwen：连续静音达到该时间后才结束语音段，保留犹豫和短停顿的上下文。Whisper 保留原有检测节奏，此值仅辅助上游分段。两者都不直接决定字幕定稿。")
        self.behavior_hint = QLabel()
        self.behavior_hint.setWordWrap(True)
        parameter_form.addRow(self.behavior_hint)
        self.add_page(advanced, "字幕与延迟")
        environment = QWidget()
        environment_form = QFormLayout(environment)
        self.runtime_status = QLabel('统一检查识别与翻译所需组件；缺失或损坏时自动修复。')
        self.runtime_status.setWordWrap(True)
        environment_form.addRow(text_label('本地推理组件', 'settingsSection'))
        environment_form.addRow(self.runtime_status)
        install = QPushButton("检查 / 修复运行环境")
        install.clicked.connect(self.install_runtime)
        self.preparation_buttons.append(install)
        environment_form.addRow(install)
        self.install_documents_button = QPushButton('安装 / 修复课件渲染组件')
        self.install_documents_button.hide()
        self.install_documents_button.clicked.connect(self.install_documents)
        self.preparation_buttons.append(self.install_documents_button)
        environment_form.addRow(self.install_documents_button)
        self.hint(environment_form, "桌面界面与模型推理使用独立环境。无需手动启动服务。统一检查所需组件，补齐或重建损坏环境，并清理未发布的残留环境。模型在模型管理中准备。")
        update = self.update_button = QPushButton('检查软件更新')
        update.clicked.connect(self.check_updates)
        self.update_url = ''
        self.update_link = QPushButton('查看发行页')
        self.update_link.hide()
        self.update_link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.update_url)))
        self.update_checked.connect(lambda result: self.show_update(result, respect_cancel=False))
        environment_form.addRow(text_label('版本与更新', 'settingsSection'))
        self.version_label = QLabel(f'当前版本：{__version__}')
        environment_form.addRow(self.version_label)
        environment_form.addRow(update)
        environment_form.addRow(self.update_link)
        self.update_status = QLabel('')
        self.update_status.setWordWrap(True)
        self.update_status.setObjectName('settingsHint')
        environment_form.addRow(self.update_status)
        self.hint(environment_form, '启动后后台检查 GitHub 发布版本，也可在此手动检查。源码版查看源码更新；未发布的安装包不会显示为可安装更新。目前需从发行页下载安装。')
        self.add_page(environment, "运行环境")
        self.status = QLabel("下载只准备文件；开始聆听时才加载模型。")
        self.status.setObjectName('preparationStatus')
        self.status.setWordWrap(True)
        self.status.setFixedHeight(64)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(24)
        self.progress_bar.setToolTip("当前下载文件的进度；总大小未知时显示滑动条。")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status)
        self.pending_settings = QLabel('当前聆听继续使用原设置；修改已保存，下次开始聆听生效。')
        self.pending_settings.setWordWrap(True)
        self.pending_settings.hide()
        layout.addWidget(self.pending_settings)
        self.cancel_button = QPushButton("取消准备")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_preparation)
        layout.addWidget(self.cancel_button)
        self.done_button = QPushButton("完成")
        self.done_button.clicked.connect(self.accept)
        layout.addWidget(self.done_button)

    def set_session_active(self, active):
        self.session_active = active
        self.pending_settings.setVisible(active)
        self.session_changed.emit(active)

    def add_page(self, widget, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)

    def hint(self, form, text):
        widget = QLabel(text)
        widget.setWordWrap(True)
        form.addRow(widget)
        return widget

    def finish_setup(self, *, asr, translation):
        self.whisper_widgets = [asr]
        self.hint(self.whisper_form, "支持自动识别语言。小模型占用更少，大模型需要更多内存；本地导入请选择原始 Whisper .pt 权重或兼容目录。")
        download = QPushButton("下载 / 检查 Whisper 模型")
        download.clicked.connect(lambda: self.prepare_whisper(asr.currentText().strip()))
        self.preparation_buttons.append(download)
        self.whisper_form.addRow(download)
        self.qwen_model = QComboBox()
        self.qwen_model.setEditable(True)
        self.qwen_model.addItems(qwen_models())
        self.qwen_form.addRow("Qwen 识别模型", self.qwen_model)
        check = QPushButton("下载 / 检查 Qwen 模型")
        check.clicked.connect(lambda: self.prepare_qwen(self.qwen_model.currentText()))
        self.preparation_buttons.append(check)
        self.qwen_form.addRow(check)
        self.qwen_hint = self.hint(self.qwen_form, '')
        self.translation_model = translation
        self.translation_engine = QComboBox()
        self.translation_engine.addItem('PyTorch', 'pytorch')
        self.translation_engine.addItem('llama.cpp · GGUF', 'llama')
        self.translation_form.insertRow(0, '翻译推理引擎', self.translation_engine)
        self.llama_model = QComboBox()
        self.llama_model.setEditable(True)
        from .llama_assets import HY_GGUF
        self.llama_model.addItem(HY_GGUF)
        self.translation_form.addRow('GGUF 模型', self.llama_model)
        self.choose_gguf = QPushButton('选择 GGUF 文件…')
        def choose_gguf():
            path, _ = QFileDialog.getOpenFileName(self, '选择 GGUF 翻译模型', '', 'GGUF 模型 (*.gguf)')
            if path:
                self.llama_model.setCurrentText(path)
        self.choose_gguf.clicked.connect(choose_gguf)
        self.translation_form.addRow(self.choose_gguf)
        self.translation_device = QComboBox()
        self.translation_form.addRow('翻译计算设备', self.translation_device)
        self.translation_before = QComboBox()
        self.translation_after = QComboBox()
        self.translation_initial_before = QComboBox()
        for key, (default, maximum) in CONTEXT_COUNTS.items():
            control = getattr(self, key)
            for count in range(maximum + 1):
                control.addItem(f'{count} 段' if count else '不参考', count)
            control.setCurrentIndex(default)
        # Keep legacy preference controls for decoding old settings, without exposing them.
        for control in (self.translation_initial_before, self.translation_before, self.translation_after):
            control.setParent(self.translation_page)
            control.hide()
        self.translation_engine.currentIndexChanged.connect(self.update_translation_engine)
        translation.currentTextChanged.connect(self.update_translation_context)
        self.hint(self.translation_form, '上下文已固定：初译前后各 1 段，定稿前 5 段、后 1 段。只参考已有的已定稿原文，没有后文立即翻译。')
        self.translation_hint = self.hint(self.translation_form, '')
        translation_download = QPushButton('下载 / 检查翻译模型')
        translation_download.clicked.connect(lambda: self.prepare_translation(translation.currentText().strip()))
        self.preparation_buttons.append(translation_download)
        self.translation_form.addRow(translation_download)
        self.update_translation_engine()
        self.backend.currentIndexChanged.connect(self.update_backend)
        self.update_backend()
        for control in (self.backend, self.qwen_model, asr, self.translation_engine,
                        translation, self.llama_model, self.translation_device):
            control.currentTextChanged.connect(lambda *_: self.selection_changed.emit(self.preparation_selection()))

    def inventory_selection(self):
        """All configured paths, including inactive engines, for local inventory."""
        return [dict(path=control.currentText(), kind=kind, engine=engine)
                for control, kind, engine in (
                    (self.qwen_model, 'asr', 'qwen3-streaming'),
                    (self.whisper_widgets[0], 'asr', 'wlk-whisper'),
                    (self.translation_model, 'translation', 'pytorch'),
                    (self.llama_model, 'translation', 'llama'))]

    def assign_model(self, entry):
        """Select a compatible downloaded model; leave the active session untouched."""
        kind, engine = entry['kind'], entry['engine']
        choice = self.backend if kind == 'asr' else self.translation_engine
        index = choice.findData(engine)
        if kind not in ('asr', 'translation') or index < 0:
            raise ValueError('这个模型的引擎不适用于当前平台。')
        choice.setCurrentIndex(index)
        control = ((self.whisper_widgets[0] if engine == 'wlk-whisper' else self.qwen_model)
                   if kind == 'asr' else (self.llama_model if engine == 'llama' else self.translation_model))
        control.setCurrentText(entry['path'])

    @property
    def preparing(self):
        return self.worker is not None

    def start_block_reason(self):
        if self.inventory_busy:
            return '模型管理', '正在删除模型，请完成后再开始聆听。'
        if self.worker is not None and self.worker.affects_runtime:
            return '模型准备中', '请等待模型准备完成，或在设置中取消准备。'
        return None

    def register_preparation_button(self, button):
        self.preparation_buttons.append(button)
        button.setEnabled(not self.preparing)

    def show_section(self, index):
        self.tabs.setCurrentIndex(index)

    def set_inventory_busy(self, busy):
        self.inventory_busy = busy

    def embed_model_settings(self, back_button):
        """Own internal form visibility when embedded beneath the inventory page."""
        self.setWindowFlags(Qt.WindowType.Widget)
        self.tabs.tabBar().hide()
        self.done_button.hide()
        self.cancel_button.setVisible(self.worker is not None)
        self.setObjectName("embeddedModels")
        self.setStyleSheet("QDialog#embeddedModels { background: transparent; } QTabWidget::pane { border: none; }")
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(14)
        for form in self.findChildren(QFormLayout):
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
        for button in self.findChildren(QPushButton):
            button.setMaximumWidth(340)
            if button.parentWidget().layout():
                button.parentWidget().layout().setAlignment(button, Qt.AlignmentFlag.AlignLeft)
        for tab in range(self.tabs.count()):
            scroll = self.tabs.widget(tab)
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
        for hint in self.findChildren(QLabel):
            hint.setWordWrap(True)
            if hint.objectName() not in ('settingsSection', 'preparationStatus'):
                hint.setObjectName('settingsHint')
        for subsection in (self.whisper_page, self.qwen_page):
            subsection.setObjectName('modelSubsection')
            subsection.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.layout().insertWidget(0, back_button)
        self.consolidated = True
        for form, control in ((self.asr_form, self.backend), (self.qwen_form, self.qwen_model),
                              (self.whisper_form, self.whisper_widgets[0]),
                              (self.translation_form, self.translation_engine)):
            form.setRowVisible(control, False)
        self.update_translation_engine()

    def update_translation_context(self):
        from .translation_models import is_hy_model
        enabled = (self.translation_engine.currentData() == 'llama'
                   or is_hy_model(self.translation_model.currentText().strip()))
        self.translation_before.setEnabled(enabled)
        self.translation_after.setEnabled(enabled)
        self.translation_initial_before.setEnabled(enabled)

    def update_translation_engine(self):
        llama = self.translation_engine.currentData() == 'llama'
        selected = self.translation_device.currentData()
        self.translation_device.clear()
        labels = {'cpu': 'CPU', 'cuda': 'NVIDIA GPU · CUDA',
                  'metal': 'Apple GPU · Metal', 'vulkan': 'GPU · Vulkan'}
        available = translation_devices(self.translation_engine.currentData())
        for device in available:
            self.translation_device.addItem(labels[device], device)
        self.translation_device.setCurrentIndex(max(0, self.translation_device.findData(selected)))
        consolidated = self.consolidated
        self.translation_form.setRowVisible(self.translation_model, not llama and not consolidated)
        self.translation_form.setRowVisible(self.choose_translation, not llama and not consolidated)
        self.translation_form.setRowVisible(self.llama_model, llama and not consolidated)
        self.translation_form.setRowVisible(self.choose_gguf, llama and not consolidated)
        self.translation_hint.setText(
            '内置 HY 1.8B 为 Q4_K_M。也可选择受当前 llama.cpp 支持、带聊天模板的本地 GGUF 指令模型；精度由权重文件决定。新模型的翻译质量需验证。'
            if llama else '支持 HY-MT2、NLLB 及兼容模型目录。模型与 GGUF 分别保存，切换引擎不会覆盖选择。')
        self.update_translation_context()
        self.status.setText('已选择 ' + self.translation_engine.currentText() + '，下次聆听生效。')

    def update_backend(self):
        mlx = self.backend.currentData() == 'qwen3-mlx'
        qwen = self.backend.currentData() in ('qwen3-streaming', 'qwen3-mlx')
        self.behavior_hint.setText(
            "Qwen：窗口式流式识别，使用缓存和稳定前缀确认原文。请在主界面指定原文语言；音频合并间隔不是模型上下文窗口。"
            if qwen else
            "Whisper：AlignAtt 根据注意力决定继续输出还是等待新音频。连续说话也能确认原文，不需要等整段停顿；调小合并间隔会增加计算频率。")
        if mlx:
            self.behavior_hint.setText('Apple GPU / MLX 4-bit：短窗口识别，近期草稿可修订；停止时处理剩余音频。8GB Mac 可先关闭翻译；实际更新速度取决于音频与模型负载。')
        self.qwen_hint.setText(
            'MLX 4-bit 使用 Apple GPU。当前为试验功能。请选择原文语言；8GB Mac 同时识别与翻译的速度受可用内存影响。'
            if mlx else
            'Qwen 在本机识别，近期原文可随语音修订。请选择原文语言。0.6B 占用较少内存，1.7B 需要更多资源。')
        self.whisper_page.setVisible(not qwen)
        self.qwen_page.setVisible(qwen)
        for widget in self.whisper_widgets:
            widget.setEnabled(not qwen)
        for widget in [self.qwen_model]:
            widget.setEnabled(qwen)

    def prepare(self, action, *, message='正在准备，可返回录音或修改下次设置；已有文件会复用。',
                affects_runtime=False, beta_only=False):
        if self.inventory_busy:
            self.preparation_status("正在删除模型，请稍后再准备。")
            return
        if self.worker is not None:
            self.preparation_status('已有准备任务正在运行，可查看进度或取消后再准备。')
            return
        if affects_runtime and self.session_active:
            self.preparation_status('运行环境修复请在本次录音结束后进行；设置仍可修改，下次生效。')
            return
        for button in self.preparation_buttons:
            button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress_bar.show()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.status.hide()
        self.status.setText(message)
        self.worker = Preparation(action, self, affects_runtime=affects_runtime, beta_only=beta_only)
        self.worker.result.connect(self.preparation_status)
        # Raw download logs stay in the worker tail, never resize the UI.
        self.worker.download.connect(self.show_download)
        self.worker.finished.connect(self.prepared)
        self.worker.start()
        self.preparation_changed.emit(True)
        self.preparation_message.emit(message)

    def preparation_status(self, text):
        if text.startswith("未完成：") and ("Traceback" in text or "File " in text):
            self.diagnostic.emit(text)
            text = "准备未完成，请稍后重试；详细原因可在诊断记录中查看。"
        self.status.setText(text)
        self.status.setToolTip(text)
        self.preparation_message.emit(text)

    def show_download(self, event):
        set_download_progress(self.progress_bar, event)
        self.download_changed.emit(event)

    def set_beta_enabled(self, enabled):
        self.install_documents_button.setVisible(enabled)
        if not enabled and self.worker is not None and self.worker.beta_only:
            self.cancel_preparation()

    def install_documents(self):
        if self.install_documents_button.isHidden() or not self.isEnabled():
            return
        self.prepare(lambda: self.run_preparation(installation_command('linguaflow.document_install')),
                     message='正在准备课件渲染组件；首次安装需要联网，可以取消。',
                     affects_runtime=False, beta_only=True)

    def prepared(self):
        self.worker.deleteLater()
        self.worker = None
        for button in self.preparation_buttons:
            button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.cancel_button.hide()
        self.progress_bar.hide()
        self.status.setVisible(bool(self.status.text()))
        self.preparation_changed.emit(False)
        from .runtime_paths import runtime_python
        try:
            python = runtime_python()
            self.runtime_status.setText(('推理环境已创建' if python.is_file() else '尚未安装推理环境')
                                       + f'\n{python}')
        except RuntimeError as exc:
            self.runtime_status.setText(str(exc))
        if self.close_requested:
            self.close_requested = False
            self.reject()

    def cancel_preparation(self):
        if self.worker:
            self.worker.cancel()
            self.preparation_status("已请求取消；正在结束准备任务…")

    def prepare_whisper(self, model):
        selection = self.preparation_selection()
        selection.update(backend='wlk-whisper', asr_model=model)
        self.prepare_selected(selection, only='asr')

    def run_preparation(self, command, *, show_progress=True):
        return self.worker.run_command(command, show_progress=show_progress)

    def preparation_selection(self):
        backend = self.backend.currentData()
        engine = self.translation_engine.currentData()
        return dict(backend=backend,
                    asr_model=(self.whisper_widgets[0] if backend == 'wlk-whisper' else self.qwen_model).currentText().strip(),
                    translation_engine=engine,
                    translation_model=(self.llama_model if engine == 'llama' else self.translation_model).currentText().strip(),
                    translation_device=self.translation_device.currentData())

    def install_runtime(self):
        selection = json.dumps(self.preparation_selection(), ensure_ascii=False)
        command = installation_command('linguaflow.runtime_install', 'all', '--maintain', '--selection', selection)
        self.prepare(lambda: self.run_preparation(command), affects_runtime=True)

    def prepare_selected(self, selection, *, only=None):
        arguments = ['--selection', json.dumps(selection, ensure_ascii=False)]
        if only:
            arguments += ['--only', only]
        command = installation_command('linguaflow.recommended_prepare', *arguments)
        self.prepare(lambda: self.run_preparation(command), affects_runtime=True,
                     message='检查环境并准备所选模型；可离开此页，取消保留已下载缓存。')

    def prepare_recommended(self):
        self.prepare_selected(self.preparation_selection())

    def check_updates(self):
        if self.update_busy:
            return
        self.update_url = ''
        self.update_link.hide()
        self.update_status.setText('正在检查更新…')
        if self.start_check is None:
            self.update_status.setText('暂时无法检查更新，请重新打开应用后重试。')
            return
        self.update_busy = True
        self.update_button.setEnabled(False)

        def checked(result):
            self.update_busy = False
            self.update_button.setEnabled(True)
            if not isinstance(result, dict) or result.get('kind') not in ('none', 'error', 'package', 'source'):
                result = {'kind': 'error', 'url': '',
                          'message': '暂时无法检查更新，请确认网络后重试。'}
            self.update_checked.emit(result)

        self.start_check('linguaflow.updates', checked)

    @Slot(dict)
    def show_update(self, result, *, respect_cancel=True):
        if respect_cancel and self.worker is not None and self.worker.cancelled:
            return
        from .updates import trusted_release_url
        self.update_status.setText(result.get('message', ''))
        self.update_url = result.get('url', '')
        self.update_link.setVisible(bool(self.update_url) and trusted_release_url(self.update_url))

    def prepare_translation(self, model):
        selection = self.preparation_selection()
        if selection['translation_engine'] != 'llama':
            selection['translation_model'] = model
        self.prepare_selected(selection, only='translation')

    def prepare_qwen(self, model):
        selection = self.preparation_selection()
        selection.update(backend='qwen3-mlx' if self.backend.currentData() == 'qwen3-mlx' else 'qwen3-streaming',
                         asr_model=model)
        self.prepare_selected(selection, only='asr')

    def reject(self):
        if self.worker is None:
            super().reject()
        else:
            self.close_requested = True
            self.cancel_preparation()

    def closeEvent(self, event):
        if self.worker is not None:
            self.close_requested = True
            self.cancel_preparation()
            event.ignore()
        else:
            event.accept()
