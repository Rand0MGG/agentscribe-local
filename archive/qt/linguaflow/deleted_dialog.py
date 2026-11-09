"""Recently deleted UI; changes are reported without knowing the main window."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QMessageBox, QPushButton

from .qt_controls import text_label
from .ui_components import SurfaceDialog


class DeletedDialog(SurfaceDialog):
    changed = Signal()

    def __init__(self, library, parent=None, *, warn=None):
        super().__init__('最近删除', '恢复后回到原文件夹；同名文件会自动添加序号。', parent)
        self.library = library
        self.warn = warn or (lambda title, message: QMessageBox.warning(self, title, message))
        self.setWindowTitle("最近删除")
        self.resize(560, 440)
        layout = self.body
        self.entries = QListWidget()
        self.entries.setObjectName("deletedEntries")
        layout.addWidget(self.entries, 1)
        self.empty = text_label('这里还没有删除的录音\n从侧栏移除的文件会先保留在这里。', 'infoBanner')
        layout.addWidget(self.empty)
        self.restore = QPushButton("恢复选中项")
        self.restore.setObjectName('primary')
        self.purge = QPushButton("永久删除…")
        self.purge.setObjectName("danger")
        self.purge_all = QPushButton("全部删除…")
        self.purge_all.setObjectName('danger')
        self.actions.addWidget(self.purge)
        self.actions.addWidget(self.purge_all)
        self.actions.addStretch()
        self.actions.addWidget(self.restore)
        self.restore.clicked.connect(self.recover)
        self.purge.clicked.connect(self.purge_selected)
        self.purge_all.clicked.connect(self.purge_everything)
        self.populate()

    def populate(self):
        self.entries.clear()
        for button in (self.restore, self.purge, self.purge_all):
            button.setEnabled(False)
        try:
            for item in self.library.deleted():
                self.entries.addItem(item["name"] + "   ·   " + item["deleted"][:10])
                self.entries.item(self.entries.count()-1).setData(Qt.ItemDataRole.UserRole, item["token"])
            self.restore.setEnabled(self.entries.count() > 0)
            self.purge.setEnabled(self.entries.count() > 0)
            self.purge_all.setEnabled(self.entries.count() > 0)
            self.entries.setCurrentRow(0)
            self.empty.setVisible(self.entries.count() == 0)
            self.entries.setVisible(self.entries.count() > 0)
        except (OSError, ValueError) as exc:
            self.warn("无法读取最近删除", str(exc))

    def recover(self):
        row = self.entries.currentItem()
        if row:
            try:
                self.library.restore_deleted(row.data(Qt.ItemDataRole.UserRole))
                self.changed.emit()
                self.populate()
            except (OSError, ValueError) as exc:
                self.warn("恢复失败", str(exc))

    def purge_selected(self):
        row = self.entries.currentItem()
        if not row:
            return
        answer = QMessageBox.warning(self, "永久删除？", "选中项中的录音与定稿将从磁盘永久删除，无法恢复。",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.library.purge_deleted(row.data(Qt.ItemDataRole.UserRole))
                self.populate()
            except (OSError, ValueError) as exc:
                self.warn("删除失败", str(exc))

    def purge_everything(self):
        # Freeze the displayed items before confirmation; newly deleted files are excluded.
        items = [(self.entries.item(i).data(Qt.ItemDataRole.UserRole), self.entries.item(i).text())
                 for i in range(self.entries.count())]
        if not items:
            return
        answer = QMessageBox.warning(self, '全部永久删除？',
            f'最近删除中显示的 {len(items)} 项及其中的录音、字幕和文件将从磁盘永久删除，无法恢复。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        failures = []
        for token, name in items:
            try:
                self.library.purge_deleted(token)
            except (OSError, ValueError) as exc:
                failures.append(f'{name}：{exc}')
        self.populate()
        if len(failures) < len(items):
            self.changed.emit()
        if failures:
            detail = '\n'.join(failures[:5])
            if len(failures) > 5:
                detail += f'\n另有 {len(failures)-5} 项未删除。'
            self.warn('部分项目未删除', f'{len(failures)} 项未能删除，仍保留在最近删除中。\n{detail}')

