"""Model preparation lives outside the listening flow."""
import os
import signal
import subprocess
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class Preparation(QThread):
    result = Signal(str)
    progress = Signal(str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action
        self.process = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.process and self.process.poll() is None:
            if sys.platform == "win32":
                subprocess.Popen(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def run(self):
        try:
            self.result.emit(self.action())
        except Exception as exc:
            self.result.emit(f"未完成：{exc}")


class ModelManager(QDialog):
    def __init__(self, parent=None, *, compute_device=lambda: "cpu"):
        super().__init__(parent)
        self.compute_device = compute_device
        self.setWindowTitle("模型管理 · 准备一次，随后直接聆听")
        self.resize(660, 640)
        self.worker = None
        self.close_requested = False
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.backend = QComboBox()
        self.backend.addItem("WhisperLiveKit · Whisper / AlignAtt", "wlk-whisper")
        self.backend.addItem("WhisperLiveKit · Qwen3-ASR 流式", "qwen3-streaming")
        if sys.platform == 'darwin':
            self.backend.addItem('Qwen3-ASR · MLX 4-bit（试验）', 'qwen3-mlx')
        self.asr_page = QWidget()
        self.asr_form = QFormLayout(self.asr_page)
        self.asr_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
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
        self.advanced_form.addRow("音频合并间隔", self.update_seconds)
        self.update_seconds.setToolTip("请求识别前合并新音频的目标；当草稿刷新目标更短时优先采用草稿目标。不是上下文窗口长度，也不是承诺的字幕刷新频率。")
        self.draft_seconds = QDoubleSpinBox()
        self.draft_seconds.setRange(.25, 3.)
        self.draft_seconds.setSingleStep(.25)
        self.draft_seconds.setValue(.5)
        self.draft_seconds.setSuffix(" 秒")
        self.draft_seconds.setToolTip("更小值更早请求原文草稿，也会增加计算量。实际更新受模型速度限制，可能一次出现几个词；不使用假打字动画。草稿优先于较长的音频合并间隔。")
        self.advanced_form.addRow("Qwen 原文草稿刷新目标", self.draft_seconds)
        self.advanced_form.addRow("ASR 停顿检测（不直接定稿）", self.endpoint_seconds)
        self.endpoint_seconds.setToolTip("Qwen：连续静音达到该时间后才结束语音段，保留犹豫和短停顿的上下文。Whisper 保留原有检测节奏，此值仅辅助上游分段。两者都不直接决定字幕定稿。")
        classroom = QPushButton("课堂逐词草稿 · 保留短停顿")
        classroom.clicked.connect(self.classroom_drafts)
        self.advanced_form.addRow(classroom)
        self.semantic_device = QComboBox()
        self.semantic_device.addItem("CPU", "cpu")
        if sys.platform != "darwin":
            self.semantic_device.addItem("NVIDIA CUDA", "cuda")
        self.advanced_form.addRow("分句模型设备", self.semantic_device)
        prepare_semantic = QPushButton("准备 / 检查 SaT 分句模型")
        prepare_semantic.clicked.connect(lambda: self.prepare(lambda: self.run_preparation(
            [sys.executable, "scripts/install_semantic.py"])))
        self.advanced_form.addRow(prepare_semantic)
        self.semantic_lookahead = QDoubleSpinBox()
        self.semantic_lookahead.setRange(1, 12)
        self.semantic_lookahead.setValue(3)
        self.semantic_lookahead.setSuffix(" 秒后文")
        self.advanced_form.addRow("定稿前保留后文", self.semantic_lookahead)
        self.hint(self.advanced_form, "SaT 根据上下文分句：听写 → 暂定分段 → 定稿。暂定译文会跟随原文更新。开始聆听前请准备 SaT；模型异常会提示并停止会话。")
        self.behavior_hint = QLabel()
        self.behavior_hint.setWordWrap(True)
        self.advanced_form.addRow(self.behavior_hint)
        self.add_page(advanced, "字幕与延迟")
        environment = QWidget()
        environment_form = QFormLayout(environment)
        from .runtime_paths import runtime_python
        self.runtime_status = QLabel()
        self.runtime_status.setWordWrap(True)
        self.runtime_status.setText(("推理环境已创建" if runtime_python().is_file() else "尚未安装推理环境")
                                   + f"\n{runtime_python()}\n文件存在不代表依赖和 GPU 已通过检查；启动时会显示各阶段进度。")
        environment_form.addRow(self.runtime_status)
        install = QPushButton("安装 / 修复本地推理环境")
        install.clicked.connect(self.install_runtime)
        environment_form.addRow(install)
        if sys.platform == 'darwin':
            install_mlx = QPushButton('安装 / 修复 Apple GPU · MLX 识别环境')
            install_mlx.clicked.connect(lambda: self.prepare(lambda: self.run_preparation(
                [sys.executable, 'scripts/install_mlx.py'])))
            environment_form.addRow(install_mlx)
        self.hint(environment_form, "桌面界面与模型推理使用独立环境。无需手动启动服务。安装后请先到识别模型和翻译模型页下载所需权重，再开始聆听。")
        self.add_page(environment, "运行环境")
        self.status = QLabel("下载只准备文件；开始聆听时才加载模型。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.cancel_button = QPushButton("取消准备")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_preparation)
        layout.addWidget(self.cancel_button)
        self.done_button = QPushButton("完成")
        self.done_button.clicked.connect(self.accept)
        layout.addWidget(self.done_button)

    def add_page(self, widget, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)

    def classroom_drafts(self):
        self.draft_seconds.setValue(.5)
        self.endpoint_seconds.setValue(1.5)
        self.status.setText("Qwen 课堂草稿：每 0.5 秒请求更新，停顿 1.5 秒才结束语音段；点击完成后用于下一次聆听。Whisper 保留原有节奏。")

    def hint(self, form, text):
        widget = QLabel(text)
        widget.setWordWrap(True)
        form.addRow(widget)
        return widget

    def finish_setup(self, *, asr, translation):
        self.whisper_widgets = [asr]
        self.hint(self.whisper_form, "由 WhisperLiveKit 的 AlignAtt 解码和连续语音检测驱动。使用完整 PyTorch Whisper 权重，旧 CTranslate2 目录不能用于这个解码器。")
        download = QPushButton("下载 / 检查 Whisper 模型")
        download.clicked.connect(lambda: self.prepare_whisper(asr.currentText().strip()))
        self.whisper_form.addRow(download)
        self.qwen_model = QComboBox()
        self.qwen_model.setEditable(True)
        self.qwen_model.addItems(["Qwen/Qwen3-ASR-0.6B", "Qwen/Qwen3-ASR-1.7B"])
        if sys.platform == 'darwin':
            self.qwen_model.addItem('mlx-community/Qwen3-ASR-1.7B-4bit')
        self.qwen_form.addRow("Qwen 识别模型", self.qwen_model)
        check = QPushButton("下载 / 检查 Qwen 模型")
        check.clicked.connect(lambda: self.prepare_qwen(self.qwen_model.currentText()))
        self.qwen_form.addRow(check)
        self.qwen_hint = self.hint(self.qwen_form, '')
        self.translation_device = QComboBox()
        self.translation_device.addItem("CPU", "cpu")
        if sys.platform != "darwin":
            self.translation_device.addItem("NVIDIA GPU · FP16", "cuda")
        self.translation_form.addRow("翻译计算设备", self.translation_device)
        self.translation_before = QComboBox()
        self.translation_after = QComboBox()
        for count in range(7):
            self.translation_before.addItem(f'{count} 段' if count else '不参考', count)
        for count in range(3):
            self.translation_after.addItem(f'{count} 段' if count else '不参考', count)
        self.translation_before.setCurrentIndex(3)
        self.translation_after.setCurrentIndex(1)
        self.translation_form.addRow('参考前文', self.translation_before)
        self.translation_form.addRow('参考后文', self.translation_after)
        def update_context_controls():
            from .translation_models import is_hy_model
            enabled = is_hy_model(translation.currentText().strip())
            self.translation_before.setEnabled(enabled)
            self.translation_after.setEnabled(enabled)
        translation.currentTextChanged.connect(update_context_controls)
        update_context_controls()
        self.hint(self.translation_form, 'HY-MT2：先翻译当前段，后续短句就绪后自动修订；前后文只供参考，不会合并进译文。NLLB 仅支持逐句翻译。')
        self.hint(self.translation_form, "翻译独立排队运行，可使用 GPU。已确认的句子先翻译，原文尾部继续修订。")
        translation_download = QPushButton("下载 / 检查翻译模型")
        translation_download.clicked.connect(lambda: self.prepare_translation(translation.currentText().strip()))
        self.translation_form.addRow(translation_download)
        self.hint(self.advanced_form, "识别期间连续音频暂存于本机临时文件，积压时保留音频并显示延迟；会话结束删除。确认的短句进入翻译，原文尾部继续修订。停止会处理剩余音频，关闭窗口则取消剩余任务。")
        self.hint(self.advanced_form, "识别与翻译设备可以独立选择。共用 GPU 会竞争显存；8GB 预算需同时考虑两个模型及运行开销。字幕尾部可修改，已确认短句进入翻译队列。")
        self.backend.currentIndexChanged.connect(self.update_backend)
        self.update_backend()

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
            'MLX 4-bit 使用 Apple GPU。当前为试验功能。请选择原文语言；8GB Mac 可用下方按钮关闭翻译，分句使用 SaT。'
            if mlx else
            'Qwen 在本机识别，近期原文可随语音修订。请选择原文语言。0.6B 占用较少内存，1.7B 需要更多资源。')
        self.whisper_page.setVisible(not qwen)
        self.qwen_page.setVisible(qwen)
        for widget in self.whisper_widgets:
            widget.setEnabled(not qwen)
        for widget in [self.qwen_model]:
            widget.setEnabled(qwen)

    def prepare(self, action):
        if self.worker is not None:
            return
        self.tabs.setEnabled(False)
        self.done_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.status.setText("正在准备，请保留此窗口。下载进度见启动终端；已存在的权重会复用。")
        self.worker = Preparation(action, self)
        self.worker.result.connect(self.status.setText)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self.prepared)
        self.worker.start()

    def prepared(self):
        self.worker.deleteLater()
        self.worker = None
        self.tabs.setEnabled(True)
        self.done_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.cancel_button.hide()
        if self.close_requested:
            self.close_requested = False
            self.reject()

    def cancel_preparation(self):
        if self.worker:
            self.worker.cancel()
            self.status.setText("已请求取消；正在结束准备任务…")

    def prepare_whisper(self, model):
        def action():
            from .runtime_paths import runtime_python
            return self.run_preparation([str(runtime_python()), "-m", "linguaflow.wlk_prepare", "whisper", model])
        self.prepare(action)

    def run_preparation(self, command):
        tail = deque(maxlen=20)
        with subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[1]),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                              start_new_session=sys.platform != "win32",
                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0) as process:
            self.worker.process = process
            if self.worker.cancelled:
                self.worker.cancel()
            for line in process.stdout:
                if line.strip():
                    tail.append(line.strip())
                    self.worker.progress.emit(line.strip()[-350:])
            if process.wait():
                raise RuntimeError("\n".join(tail)[-1500:])
        return tail[-1] if tail else "准备完成"

    def install_runtime(self):
        command = [sys.executable, "scripts/install_runtime.py"]
        if (self.compute_device() == "cpu"
                and self.translation_device.currentData() == "cpu"):
            command.append("--cpu")
        self.prepare(lambda: self.run_preparation(command))

    def prepare_translation(self, model):
        def action():
            from .model_cache import has_weights, resolve_translation
            path = resolve_translation(model, False, lambda message: None)
            if not has_weights(path):
                raise ValueError("翻译权重不完整")
            return f"翻译模型文件已就绪：{path}"
        self.prepare(action)

    def prepare_qwen(self, model):
        def action():
            from pathlib import Path

            from huggingface_hub import snapshot_download
            if Path(model).is_dir():
                from .model_cache import resolve_qwen_cached
                return f"Qwen 模型文件已就绪：{resolve_qwen_cached(model)}"
            options = {}
            if model == 'mlx-community/Qwen3-ASR-1.7B-4bit':
                from .mlx_asr import MLX_REVISION
                options = {'revision': MLX_REVISION, 'local_dir': str(
                    Path(__file__).resolve().parents[1] / 'models' / 'Qwen3-ASR-1.7B-4bit')}
            path = snapshot_download(model, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"],
                                     max_workers=1, **options)
            from .model_cache import resolve_qwen_cached
            resolve_qwen_cached(path)
            return f"Qwen 模型已下载：{path}"
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
