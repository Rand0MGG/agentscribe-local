"""Find and locate existing transcript segments without playing audio."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton

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
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.body.addWidget(self.summary)
        self.previous = QPushButton('上一页')
        self.next = QPushButton('下一页')
        for button in (self.previous, self.next):
            button.setObjectName('quiet')
            button.setAutoDefault(False)
            self.actions.addWidget(button)
        self.previous.clicked.connect(lambda: self.show_page(self.page - 1))
        self.next.clicked.connect(lambda: self.show_page(self.page + 1))
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
        self.matches = [caption for caption, searchable in self.entries if not query or query in searchable]
        self.show_page(0)

    def show_page(self, page):
        self.page = max(0, min(page, max(0, (len(self.matches)-1)//100)))
        start = self.page * 100
        self.results.clear()
        for caption in self.matches[start:start+100]:
            seconds = int(caption.start)
            excerpt = ' '.join((caption.source+' '+caption.translation).split())
            row = QListWidgetItem(f'{seconds//60:02d}:{seconds%60:02d}  {excerpt[:140]}')
            row.setData(Qt.ItemDataRole.UserRole, caption.id)
            self.results.addItem(row)
        self.results.setCurrentRow(0)
        self.locate.setEnabled(self.results.count() > 0)
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start + 100 < len(self.matches))
        self.summary.setText(f'共 {len(self.matches)} 条，显示第 {start+1}–{start+self.results.count()} 条'
                             if self.matches else '没有匹配内容，请尝试其他关键词。'
                             if self.query.text().strip() else '当前录音还没有字幕。')

    def choose(self):
        row = self.results.currentItem()
        if row:
            self.located.emit(row.data(Qt.ItemDataRole.UserRole))
            self.accept()
