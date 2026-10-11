"""Find and locate existing transcript segments without playing audio."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QPushButton

from .ui_components import SurfaceDialog


class RecordingSearchDialog(SurfaceDialog):
    located = Signal(int)

    def __init__(self, captions, parent=None):
        super().__init__('查找字幕', '搜索原文或译文，选择结果定位；不会自动播放录音。', parent)
        self.resize(560, 440)
        self.entries = [(caption, (caption.source+'\n'+caption.translation).casefold()) for caption in captions]
        self.query = QLineEdit()
        self.query.setPlaceholderText('搜索原文或译文…')
        self.query.setAccessibleName('搜索当前录音字幕')
        self.body.addWidget(self.query)
        self.results = QListWidget()
        self.body.addWidget(self.results, 1)
        self.locate = QPushButton('定位')
        self.locate.setObjectName('primary')
        self.actions.addStretch()
        self.actions.addWidget(self.locate)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.search)
        self.query.textChanged.connect(lambda _: self.timer.start())
        self.query.returnPressed.connect(self.search)
        self.results.currentItemChanged.connect(lambda item, _: self.locate.setEnabled(bool(item)))
        self.results.itemActivated.connect(lambda _: self.choose())
        self.locate.clicked.connect(self.choose)
        self.search()

    def search(self):
        self.timer.stop()
        query = self.query.text().strip().casefold()
        self.results.clear()
        for caption, searchable in self.entries:
            if not query or query in searchable:
                seconds = int(caption.start)
                excerpt = ' '.join((caption.source+' '+caption.translation).split())
                row = QListWidgetItem(f'{seconds//60:02d}:{seconds%60:02d}  {excerpt[:140]}')
                row.setData(Qt.ItemDataRole.UserRole, caption.id)
                self.results.addItem(row)
                if self.results.count() >= 100:
                    break  # Bound widget creation; refine the query for later matches.
        self.results.setCurrentRow(0)
        self.locate.setEnabled(self.results.count() > 0)
        self.query.setToolTip('最多显示 100 个匹配段落；可继续输入缩小范围。' if self.results.count() == 100 else
                              '没有匹配内容。' if not self.results.count() else '')

    def choose(self):
        row = self.results.currentItem()
        if row:
            self.located.emit(row.data(Qt.ItemDataRole.UserRole))
            self.accept()
