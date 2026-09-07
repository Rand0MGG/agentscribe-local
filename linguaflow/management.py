"""Model preparation lives outside the listening flow."""
import os
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

    def run(self):
        try:
            self.result.emit(self.action())
        except Exception as exc:
            self.result.emit(f"未完成：{exc}")


class ModelManager(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("模型管理 · 准备一次，随后直接聆听")
        self.resize(660, 640)
        self.worker = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.backend = QComboBox()
        self.backend.addItem("WhisperLiveKit · Whisper / AlignAtt", "wlk-whisper")
        self.backend.addItem("WhisperLiveKit · Qwen3-ASR 流式", "qwen3-streaming")
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
        self.update_seconds.setToolTip("积累至少这段新音频后交给内核；不是识别窗口长度，也不是承诺的字幕刷新频率。")
        self.advanced_form.addRow("停顿分段阈值", self.endpoint_seconds)
        self.endpoint_seconds.setToolTip("检测到停顿后推进分段；连续语音中的文字确认由所选流式内核决定。")
        self.behavior_hint = QLabel()
        self.behavior_hint.setWordWrap(True)
        self.advanced_form.addRow(self.behavior_hint)
        self.add_page(advanced, "字幕与延迟")
        environment = QWidget()
        environment_form = QFormLayout(environment)
        from .wlk_session import runtime_python
        self.runtime_status = QLabel()
        self.runtime_status.setWordWrap(True)
        self.runtime_status.setText(("推理环境已创建" if runtime_python().is_file() else "尚未安装推理环境")
                                   + f"\n{runtime_python()}\n文件存在不代表依赖和 GPU 已通过检查；启动时会显示各阶段进度。")
        environment_form.addRow(self.runtime_status)
        install = QPushButton("安装 / 修复本地推理环境")
        install.clicked.connect(self.install_runtime)
        environment_form.addRow(install)
        self.hint(environment_form, "桌面界面与模型推理使用独立环境。无需手动启动服务。安装后请先到识别模型和翻译模型页下载所需权重，再开始聆听。")
        self.add_page(environment, "运行环境")
        self.status = QLabel("下载只准备文件；开始聆听时才加载模型。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.done_button = QPushButton("完成")
        self.done_button.clicked.connect(self.accept)
        layout.addWidget(self.done_button)

    def add_page(self, widget, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)

    def hint(self, form, text):
        widget = QLabel(text)
        widget.setWordWrap(True)
        form.addRow(widget)

    def finish_setup(self, window):
        self.whisper_widgets = [window.asr]
        self.hint(self.whisper_form, "由 WhisperLiveKit 的 AlignAtt 解码和连续语音检测驱动。使用完整 PyTorch Whisper 权重，旧 CTranslate2 目录不能用于这个解码器。")
        download = QPushButton("下载 / 检查 Whisper 模型")
        download.clicked.connect(lambda: self.prepare_whisper(window.asr.currentText().strip()))
        self.whisper_form.addRow(download)
        self.qwen_model = QComboBox()
        self.qwen_model.setEditable(True)
        self.qwen_model.addItems(["Qwen/Qwen3-ASR-0.6B", "Qwen/Qwen3-ASR-1.7B"])
        self.qwen_form.addRow("Qwen 识别模型", self.qwen_model)
        check = QPushButton("下载 / 检查 Qwen 模型")
        check.clicked.connect(lambda: self.prepare_qwen(self.qwen_model.currentText()))
        self.qwen_form.addRow(check)
        self.hint(self.qwen_form, "本机直接运行 Qwen 窗口式流式后端，不需要 WSL 或手动启动服务。请选择原文语言。0.6B 优先用于较小显存；1.7B 需要更多资源。")
        self.translation_device = QComboBox()
        self.translation_device.addItem("CPU", "cpu")
        if sys.platform != "darwin":
            self.translation_device.addItem("NVIDIA GPU · FP16", "cuda")
        self.translation_form.addRow("翻译计算设备", self.translation_device)
        self.hint(self.translation_form, "翻译独立排队运行，可使用 GPU。已确认的句子先翻译，原文尾部继续修订。")
        translation_download = QPushButton("下载 / 检查翻译模型")
        translation_download.clicked.connect(lambda: self.prepare_translation(window.translation.currentText().strip()))
        self.translation_form.addRow(translation_download)
        self.hint(self.advanced_form, "识别期间连续音频暂存于本机临时文件，积压时保留音频并显示延迟；会话结束删除。确认的短句进入翻译，原文尾部继续修订。停止会处理剩余音频，关闭窗口则取消剩余任务。")
        self.hint(self.advanced_form, "识别与翻译设备可以独立选择。共用 GPU 会竞争显存；8GB 预算需同时考虑两个模型及运行开销。字幕尾部可修改，已确认短句进入翻译队列。")
        self.backend.currentIndexChanged.connect(self.update_backend)
        self.update_backend()

    def update_backend(self):
        qwen = self.backend.currentData() == "qwen3-streaming"
        self.behavior_hint.setText(
            "Qwen：窗口式流式识别，使用缓存和稳定前缀确认原文。请在主界面指定原文语言；音频合并间隔不是模型上下文窗口。"
            if qwen else
            "Whisper：AlignAtt 根据注意力决定继续输出还是等待新音频。连续说话也能确认原文，不需要等整段停顿；调小合并间隔会增加计算频率。")
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

    def prepare_whisper(self, model):
        def action():
            from .wlk_session import runtime_python
            return self.run_preparation([str(runtime_python()), "-m", "linguaflow.wlk_prepare", "whisper", model])
        self.prepare(action)

    def run_preparation(self, command):
        tail = deque(maxlen=20)
        with subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[1]),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0) as process:
            for line in process.stdout:
                if line.strip():
                    tail.append(line.strip())
                    self.worker.progress.emit(line.strip()[-350:])
            if process.wait():
                raise RuntimeError("\n".join(tail)[-1500:])
        return tail[-1] if tail else "准备完成"

    def install_runtime(self):
        command = [sys.executable, "scripts/install_runtime.py"]
        if (self.parent().compute.currentData() == "cpu"
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
            path = snapshot_download(model, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"], max_workers=1)
            from .model_cache import resolve_qwen_cached
            resolve_qwen_cached(path)
            return f"Qwen 模型已下载：{path}"
        self.prepare(action)

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            event.accept()
