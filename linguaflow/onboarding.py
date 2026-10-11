"""Missing-model guidance, using the same preparation and storage actions as settings."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton

from .ui_components import SurfaceDialog


class FirstRunDialog(SurfaceDialog):
    choose_storage = Signal()
    prepare_models = Signal()

    def __init__(self, root, parent=None, *, asr_label='Qwen3-ASR 1.7B'):
        super().__init__('准备本地模型', '指定的模型尚未准备好。模型在本机运行，录音保存在你选择的位置。', parent)
        self.body.addWidget(QLabel('1  录音保存位置'))
        self.storage = QLabel(str(root))
        self.storage.setWordWrap(True)
        self.storage.setObjectName('muted')
        self.body.addWidget(self.storage)
        choose = QPushButton('更改保存位置…')
        choose.clicked.connect(self.choose_storage.emit)
        self.body.addWidget(choose)
        self.body.addWidget(QLabel('2  准备识别与翻译模型'))
        self.asr_label = asr_label
        self.models = QLabel()
        self.models.setObjectName('muted')
        self.body.addWidget(self.models)
        self.model_state = QLabel('正在检查已有模型…')
        self.model_state.setWordWrap(True)
        self.model_state.setObjectName('muted')
        self.body.addWidget(self.model_state)
        self.download = QPushButton('下载并使用推荐组合')
        self.set_translation_enabled(True)
        self.download.clicked.connect(self.prepare_models.emit)
        self.body.addWidget(self.download)
        later = QPushButton('稍后准备')
        later.clicked.connect(self.reject)
        self.finish = QPushButton('开始使用')
        self.finish.setObjectName('primary')
        self.finish.setEnabled(False)
        self.finish.clicked.connect(self.complete)
        self.actions.addStretch()
        self.actions.addWidget(later)
        self.actions.addWidget(self.finish)

    def set_models(self, missing, *, preparing=False):
        ready = missing is not None and not missing and not preparing
        self.model_state.setText('正在后台准备模型，可以先浏览应用。' if preparing else
                                 '所需模型已就绪。' if ready else
                                 '正在检查已有模型…' if missing is None else
                                 '下载一次，之后可在本机使用。已有文件会复用。')
        self.download.setEnabled(not preparing and not ready)
        self.finish.setEnabled(ready)

    def set_translation_enabled(self, enabled):
        self.models.setText(self.asr_label + ' · 语音识别' +
                            ('\nHY-MT2 1.8B Q4_K_M · 翻译' if enabled else ''))
        self.download.setText('下载并使用推荐组合' if enabled else '下载并使用推荐识别模型')

    def complete(self):
        if self.finish.isEnabled():
            self.accept()
