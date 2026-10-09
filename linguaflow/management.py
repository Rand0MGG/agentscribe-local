"""Model preparation lives outside the listening flow."""
import json
import subprocess
import sys
from collections import deque
from threading import Event, Thread

from PySide6.QtCore import QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
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
from .download_progress import PREFIX
from .listening_profiles import PROFILES
from .model_options import asr_backends, qwen_models, translation_devices
from .process_platform import spawn_options, stop_tree
from .qt_controls import text_label
from .runtime_paths import installation_command, python_environment, resource_root
from .translation_config import CONTEXT_COUNTS
from .ui_components import ChoiceBox as QComboBox


class Preparation(QThread):
    result = Signal(str)
    progress = Signal(str)
    download = Signal(dict)

    def __init__(self, action, parent, *, affects_runtime=True, beta_only=False):
        super().__init__(parent)
        self.action = action
        self.affects_runtime = affects_runtime
        self.beta_only = beta_only
        self.process = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            result = self.action()
            self.result.emit('准备已取消；已完成文件保留。' if self.cancelled else result)
        except Exception as exc:
            self.result.emit(f"未完成：{exc}")


class ModelManager(QDialog):
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
        self.profile = QComboBox()
        for key, (name, *_rest) in PROFILES.items():
            self.profile.addItem(name, key)
        self.profile.addItem('自定义', 'custom')
        self.profile.setCurrentIndex(1)
        self.advanced_form.addRow('聆听预设', self.profile)
        self.profile_hint = self.hint(self.advanced_form, PROFILES['balanced'][2])
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
        classroom = QPushButton("课堂草稿 · 保留短停顿")
        classroom.clicked.connect(self.classroom_drafts)
        parameter_form.addRow(classroom)
        self.behavior_hint = QLabel()
        self.behavior_hint.setWordWrap(True)
        parameter_form.addRow(self.behavior_hint)
        self.add_page(advanced, "字幕与延迟")
        environment = QWidget()
        environment_form = QFormLayout(environment)
        from .runtime_paths import runtime_python
        self.runtime_status = QLabel()
        self.runtime_status.setWordWrap(True)
        self.runtime_status.setToolTip('文件存在不代表依赖和 GPU 已通过检查；启动时会显示各阶段进度。')
        try:
            python = runtime_python()
            self.runtime_status.setText(("推理环境已创建" if python.is_file() else "尚未安装推理环境")
                                       + f"\n{python}")
        except RuntimeError as exc:
            self.runtime_status.setText(str(exc))
        environment_form.addRow(text_label('本地推理组件', 'settingsSection'))
        environment_form.addRow(self.runtime_status)
        install = QPushButton("安装 / 修复本地推理环境")
        install.clicked.connect(self.install_runtime)
        self.preparation_buttons.append(install)
        environment_form.addRow(install)
        self.install_documents_button = QPushButton('安装 / 修复课件渲染组件')
        self.install_documents_button.hide()
        self.install_documents_button.clicked.connect(self.install_documents)
        self.preparation_buttons.append(self.install_documents_button)
        environment_form.addRow(self.install_documents_button)
        if sys.platform == 'darwin':
            install_mlx = QPushButton('安装 / 修复 Apple GPU · MLX 识别环境')
            install_mlx.clicked.connect(lambda: self.prepare(lambda: self.run_preparation(
                installation_command('linguaflow.runtime_install', 'mlx')), affects_runtime=True))
            self.preparation_buttons.append(install_mlx)
            environment_form.addRow(install_mlx)
        self.hint(environment_form, "桌面界面与模型推理使用独立环境。无需手动启动服务。安装后请先到识别模型和翻译模型页下载所需权重，再开始聆听。")
        update = QPushButton('检查软件更新')
        update.clicked.connect(self.check_updates)
        self.preparation_buttons.append(update)
        self.update_url = ''
        self.update_link = QPushButton('查看发行页')
        self.update_link.hide()
        self.update_link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.update_url)))
        self.update_checked.connect(self.show_update)
        environment_form.addRow(text_label('版本与更新', 'settingsSection'))
        self.version_label = QLabel(f'当前版本：{__version__}')
        environment_form.addRow(self.version_label)
        environment_form.addRow(update)
        environment_form.addRow(self.update_link)
        self.hint(environment_form, '启动后后台检查 GitHub 发布版本，也可在此手动检查。源码版查看源码更新；未发布的安装包不会显示为可安装更新。目前需从发行页下载安装。')
        self.add_page(environment, "运行环境")
        self.status = QLabel("下载只准备文件；开始聆听时才加载模型。")
        self.status.setObjectName('preparationStatus')
        self.status.setWordWrap(True)
        self.progress_bar = QProgressBar()
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

    def apply_profile(self):
        key = self.profile.currentData()
        if key not in PROFILES:
            self.profile_hint.setText('使用你保存的高级参数。实际速度和效果取决于模型与设备。')
            return
        _name, interval, hint = PROFILES[key]
        self._applying_profile = True
        for control in (self.update_seconds, self.draft_seconds):
            control.setValue(interval)
        self.endpoint_seconds.setValue(1.5)
        self._applying_profile = False
        self.sync_profile()
        self.profile_hint.setText(hint + ' 不改变字幕确认规则；下次开始聆听生效。')

    def sync_profile(self):
        if getattr(self, '_applying_profile', False):
            return
        key = next((key for key, (_name, interval, _hint) in PROFILES.items()
                    if self.update_seconds.value() == self.draft_seconds.value() == interval
                    and self.endpoint_seconds.value() == 1.5),
                   'custom')
        self.profile.blockSignals(True)
        self.profile.setCurrentIndex(self.profile.findData(key))
        self.profile.blockSignals(False)
        self.profile_hint.setText(PROFILES[key][2] if key in PROFILES else '使用你保存的高级参数；可直接选择预设。')

    def add_page(self, widget, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)

    def classroom_drafts(self):
        self.draft_seconds.setValue(.5)
        self.endpoint_seconds.setValue(1.5)
        self.status.setText("已应用课堂设置：每 0.5 秒请求草稿，保留 1.5 秒短停顿。下一次聆听生效；实际更新速度取决于模型。")

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
        if sys.platform == 'darwin':
            self.hy_metal_button = QPushButton('使用 HY 1.8B · Apple GPU')
            def select_hy_metal():
                self.translation_engine.setCurrentIndex(self.translation_engine.findData('llama'))
                self.llama_model.setCurrentText(HY_GGUF)
                self.translation_device.setCurrentIndex(self.translation_device.findData('metal'))
                self.status.setText('已选择 HY 1.8B Q4_K_M · llama.cpp / Metal。首次请准备模型，下次聆听生效。')
            self.hy_metal_button.clicked.connect(select_hy_metal)
            self.translation_form.addRow(self.hy_metal_button)
        self.update_translation_engine()
        self.backend.currentIndexChanged.connect(self.update_backend)
        self.update_backend()
        self.profile.currentIndexChanged.connect(self.apply_profile)
        for control in (self.update_seconds, self.draft_seconds, self.endpoint_seconds):
            control.valueChanged.connect(self.sync_profile)
        for control in (self.translation_before, self.translation_after, self.translation_initial_before):
            control.currentIndexChanged.connect(self.sync_profile)

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
        self.translation_form.setRowVisible(self.translation_model, not llama)
        self.translation_form.setRowVisible(self.choose_translation, not llama)
        self.translation_form.setRowVisible(self.llama_model, llama)
        self.translation_form.setRowVisible(self.choose_gguf, llama)
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
        self.status.setText(message)
        self.worker = Preparation(action, self, affects_runtime=affects_runtime, beta_only=beta_only)
        self.worker.result.connect(self.preparation_status)
        self.worker.progress.connect(self.preparation_status)
        self.worker.download.connect(self.show_download)
        self.worker.finished.connect(self.prepared)
        self.worker.start()
        self.preparation_changed.emit(True)
        self.preparation_message.emit(message)

    def preparation_status(self, text):
        self.status.setText(text)
        self.preparation_message.emit(text)

    def show_download(self, event):
        total, done = event.get('total'), event.get('completed', 0)
        if total and total > 0:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(min(1000, int(1000 * done / total)))
            self.progress_bar.setTextVisible(True)
            self.progress_bar.setFormat('%p%')
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setTextVisible(False)
        detail = event.get('label', '准备中')
        if event.get('unit') == 'B':
            detail += f' · {done / 1024**2:.1f} MB'
            if total:
                detail += f' / {total / 1024**2:.1f} MB'
            rate = event.get('rate')
            if rate and rate > 0:
                detail += f' · {rate / 1024**2:.1f} MB/s'
                if total and done < total:
                    detail += f' · 约剩 {int((total - done) / rate)} 秒'
        elif total:
            detail += f' · {int(done)} / {int(total)} 个文件'
        self.preparation_status(detail)
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
        def action():
            from .runtime_paths import runtime_python
            result = self.run_preparation([str(runtime_python()), "-m", "linguaflow.wlk_prepare", "whisper", model])
            self.prepare_segmentation()
            return result
        self.prepare(action)

    def run_preparation(self, command, *, show_progress=True):
        if self.worker.cancelled:
            raise RuntimeError('准备已取消。')
        tail = deque(maxlen=20)
        if show_progress:
            self.worker.download.emit(dict(label='准备组件', unit='stage'))
        # The supervisor owns descendants even when the desktop exits unexpectedly.
        command = installation_command('linguaflow.managed_process', *command)
        with subprocess.Popen(command, cwd=resource_root(), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              env=python_environment(),
                              **spawn_options()) as process:
            self.worker.process = process
            finished = Event()
            def watch():
                while not finished.wait(.05):
                    if self.worker.cancelled:
                        process.stdin.close()  # EOF lets the supervisor reap its tree.
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            stop_tree(process, force=True)
                        return
            watcher = Thread(target=watch, daemon=True)
            watcher.start()
            try:
                for line in process.stdout:
                    if line.strip():
                        if line.startswith(PREFIX):
                            try:
                                event = json.loads(line[len(PREFIX):])
                                if isinstance(event, dict):
                                    self.worker.download.emit(event)
                                    continue
                            except ValueError:
                                pass
                        tail.append(line.strip())
                        if show_progress:
                            self.worker.progress.emit(line.strip()[-350:])
                code = process.wait(timeout=10)
                if self.worker.cancelled:
                    raise RuntimeError('准备已取消；已有文件保留，可稍后继续。')
                if code:
                    raise RuntimeError("\n".join(tail)[-1500:])
            finally:
                finished.set()
                watcher.join(timeout=10)
                self.worker.process = None
        return tail[-1] if tail else "准备完成"

    def install_runtime(self):
        command = installation_command('linguaflow.runtime_install', 'wlk')
        self.prepare(lambda: self.run_preparation(command), affects_runtime=True)

    def prepare_recommended(self):
        from .runtime_paths import mlx_python, runtime_python
        try:
            changes_runtime = not (runtime_python().is_file() and mlx_python().is_file())
        except RuntimeError:
            changes_runtime = True
        command = installation_command('linguaflow.recommended_prepare')
        self.prepare(lambda: self.run_preparation(command), affects_runtime=changes_runtime,
                     message='准备 Qwen3-ASR 1.7B 4-bit 和 HY 1.8B Q4_K_M；可离开此页，取消保留已下载缓存。')

    def check_updates(self):
        def action():
            result = json.loads(self.run_preparation(installation_command('linguaflow.updates'), show_progress=False))
            self.update_checked.emit(result)
            return result['message']
        self.update_url = ''
        self.update_link.hide()
        self.prepare(action, message='正在检查已发布的软件版本…', affects_runtime=False)

    @Slot(dict)
    def show_update(self, result, *, respect_cancel=True):
        if respect_cancel and self.worker is not None and self.worker.cancelled:
            return
        from .updates import trusted_release_url
        self.update_url = result.get('url', '')
        self.update_link.setVisible(bool(self.update_url) and trusted_release_url(self.update_url))

    def prepare_translation(self, model):
        if self.translation_engine.currentData() == 'llama':
            command = installation_command('linguaflow.llama_install',
                       '--device', self.translation_device.currentData(),
                       '--model', self.llama_model.currentText().strip())
            self.prepare(lambda: self.run_preparation(command))
            return
        def action():
            return self.run_preparation(installation_command('linguaflow.model_prepare', 'translation', model))
        self.prepare(action)

    def prepare_segmentation(self):
        """Prepare the required internal CPU model through the cancellable worker."""
        from .runtime_paths import runtime_python
        return self.run_preparation([str(runtime_python()), '-u', '-m', 'linguaflow.semantic_model'])

    def prepare_qwen(self, model):
        def action():
            result = self.run_preparation(installation_command('linguaflow.model_prepare', 'qwen', model))
            self.prepare_segmentation()
            return result
        self.prepare(action)

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
