"""Model preparation lives outside the listening flow."""
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class Preparation(QThread):
    result = Signal(str)

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
        self.backend.addItem("Whisper · 近实时回听修订", "whisper-live")
        self.backend.addItem("Qwen3-ASR · 持续音频流式接口（需本地服务）", "qwen-stream")
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
        self.endpoint_seconds.setValue(1)
        self.endpoint_seconds.setSuffix(" 秒")
        self.advanced_form.addRow("原文刷新间隔（更短会增加计算量）", self.update_seconds)
        self.advanced_form.addRow("停顿多久后定稿（更长保留更多上下文）", self.endpoint_seconds)
        self.add_page(advanced, "聆听行为")
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
        self.whisper_widgets = [window.asr, window.compute]
        self.hint(self.whisper_form, "Whisper 原本面向完整音频。这里通过重叠回听和多次识别一致性实现近实时原文修订；不保证零延迟。Mac 当前使用 CPU。")
        download = QPushButton("下载 / 检查 Whisper 模型")
        download.clicked.connect(lambda: self.prepare_whisper(window.asr.currentText().strip()))
        self.whisper_form.addRow(download)
        self.qwen_model = QComboBox()
        self.qwen_model.addItems(["Qwen/Qwen3-ASR-0.6B", "Qwen/Qwen3-ASR-1.7B"])
        self.service_url = QLineEdit("http://127.0.0.1:8765")
        self.qwen_form.addRow("Qwen 服务模型", self.qwen_model)
        self.qwen_form.addRow("本机服务地址", self.service_url)
        check = QPushButton("检查流式服务是否就绪")
        check.clicked.connect(self.check_service)
        self.qwen_form.addRow(check)
        self.hint(self.qwen_form, "Qwen 使用官方会话接口，持续接收音频并回退修订原文；需要独立 Linux / WSL + vLLM 服务。下载与显存由该服务管理，不能直接把权重交给 Whisper。Mac 暂未接入 Qwen 实时后端。配置步骤见 docs/QWEN_STREAMING.md。")
        self.hint(self.translation_form, "NLLB 在 CPU 翻译已定稿原文。关闭翻译仍可实时转写；翻译加载失败不会阻止原文显示。")
        translation_download = QPushButton("下载 / 检查翻译模型")
        translation_download.clicked.connect(lambda: self.prepare_translation(window.translation.currentText().strip()))
        self.translation_form.addRow(translation_download)
        self.hint(self.advanced_form, "识别期间连续音频暂存于本机临时文件，积压时保留音频并显示延迟；会话结束删除。停顿后原文定稿才进入翻译。停止会处理剩余音频，关闭窗口则取消剩余任务。")
        self.hint(self.advanced_form, "8GB 目标配置：先选较小识别模型，翻译留在 CPU。Qwen 0.6B 是优先候选，尚未完成本机实际推理验收；1.7B 不承诺符合 8GB 总预算。")
        self.backend.currentIndexChanged.connect(self.update_backend)
        self.update_backend()

    def update_backend(self):
        qwen = self.backend.currentData() == "qwen-stream"
        self.whisper_page.setVisible(not qwen)
        self.qwen_page.setVisible(qwen)
        for widget in self.whisper_widgets:
            widget.setEnabled(not qwen)
        for widget in [self.qwen_model, self.service_url]:
            widget.setEnabled(qwen)

    def prepare(self, action):
        if self.worker is not None:
            return
        self.tabs.setEnabled(False)
        self.done_button.setEnabled(False)
        self.status.setText("正在准备，请保留此窗口。下载进度见启动终端；已存在的权重会复用。")
        self.worker = Preparation(action, self)
        self.worker.result.connect(self.status.setText)
        self.worker.finished.connect(self.prepared)
        self.worker.start()

    def prepared(self):
        self.worker.deleteLater()
        self.worker = None
        self.tabs.setEnabled(True)
        self.done_button.setEnabled(True)

    def prepare_whisper(self, model):
        def action():
            from faster_whisper.utils import download_model
            path = Path(model) if Path(model).is_dir() else Path(download_model(model))
            if not all((path / name).is_file() for name in ["model.bin", "config.json", "tokenizer.json"]):
                raise ValueError("目录缺少 CTranslate2 模型或 tokenizer.json")
            return f"Whisper 文件已就绪：{path}"
        self.prepare(action)

    def prepare_translation(self, model):
        def action():
            from .model_cache import has_weights, resolve_translation
            path = resolve_translation(model, False, lambda message: None)
            if not has_weights(path):
                raise ValueError("翻译权重不完整")
            return f"翻译模型文件已就绪：{path}"
        self.prepare(action)

    def check_service(self):
        url, model = self.service_url.text(), self.qwen_model.currentText()
        def action():
            from .qwen_client import LocalService
            info = LocalService(url).health()
            if info["model"] != model:
                raise ValueError(f"服务实际加载 {info['model']}，与所选模型不符")
            return f"流式服务已就绪：{model} · 可接收连续音频、修订原文"
        self.prepare(action)

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            event.accept()
