"""Recording-library tree presentation; no session or main-window dependencies."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem

from .ui_theme import interaction_color


class LibraryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(200, 38)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        light = QApplication.instance().property("appearance") != "dark"
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            appearance = QApplication.instance().property('appearance')
            painter.setBrush(QColor(*interaction_color(appearance, 'secondary_hover' if selected else 'row_hover')))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(2, 2, -2, -2), 8, 8)
        depth, parent = 0, index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        x = option.rect.x() + depth * 14
        kind, _ = index.data(Qt.ItemDataRole.UserRole)
        y = option.rect.center().y()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor('#666670' if light else '#aaaab2'))
        if kind == 'folder':
            expanded = bool(option.state & QStyle.StateFlag.State_Open)
            points = [(x + 30, y - 2), (x + 33, y + 1), (x + 36, y - 2)] if expanded else [
                (x + 31, y - 4), (x + 34, y - 1), (x + 31, y + 2)]
            painter.drawLine(QPointF(*points[0]), QPointF(*points[1]))
            painter.drawLine(QPointF(*points[1]), QPointF(*points[2]))
            painter.drawRoundedRect(QRectF(x + 12, y - 5, 15, 11), 2, 2)
            painter.drawLine(QPointF(x + 13, y - 7), QPointF(x + 19, y - 7))
            text_x = x + 41
        else:
            painter.drawRoundedRect(QRectF(x + 10, y - 7, 11, 14), 2, 2)
            painter.drawLine(QPointF(x + 13, y - 2), QPointF(x + 18, y - 2))
            painter.drawLine(QPointF(x + 13, y + 2), QPointF(x + 18, y + 2))
            text_x = x + 30
        painter.setFont(option.font)
        painter.setPen(QColor(("#303034" if selected else "#60606a") if light else ("#eeeeef" if selected else "#bdbdc3")))
        rect = option.rect.adjusted(text_x - option.rect.x(), 0, -28 if kind == 'folder' else -53, 0)
        title = str(index.data())
        if option.fontMetrics.horizontalAdvance(title) <= rect.width():
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, title)
        elif rect.width() > 0:
            ratio = painter.device().devicePixelRatioF()
            layer = QPixmap(round(rect.width() * ratio), round(rect.height() * ratio))
            layer.setDevicePixelRatio(ratio)
            layer.fill(Qt.GlobalColor.transparent)
            ink = QPainter(layer)
            ink.setFont(option.font)
            ink.setPen(painter.pen())
            bounds = QRectF(0, 0, rect.width(), rect.height())
            ink.drawText(bounds, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine, title)
            ink.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            fade = QLinearGradient(max(0, rect.width() - 28), 0, rect.width(), 0)
            fade.setColorAt(0, QColor(0, 0, 0, 255))
            fade.setColorAt(1, QColor(0, 0, 0, 0))
            ink.fillRect(bounds, fade)
            ink.end()
            painter.drawPixmap(rect.topLeft(), layer)
        if hover or selected:
            painter.drawText(option.rect.adjusted(option.rect.width() - 27, 0, -4, 0), Qt.AlignmentFlag.AlignCenter, "···")
        painter.restore()


class LibraryTree(QTreeWidget):
    menuRequested = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.rows = {}
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setIconSize(QSize(18, 18))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setItemDelegate(LibraryDelegate(self))

    def populate(self, index, *, current_id=None, folder_id=None):
        expanded = {identifier: row.isExpanded() for identifier, row in self.rows.items()}
        self.clear()
        self.rows = {}
        folders, current = {}, None
        for folder in index['folders']:
            row = QTreeWidgetItem([folder['name']])
            row.setData(0, Qt.ItemDataRole.UserRole, ('folder', folder['id']))
            row.setToolTip(0, '点击选中文件夹 · ＋ 新建录音 · 双击折叠/展开 · 右键更多操作')
            parent = folders.get(folder.get('parent'))
            if parent:
                parent.addChild(row)
            else:
                self.addTopLevelItem(row)
            folders[folder['id']] = self.rows[folder['id']] = row
            row.setExpanded(expanded.get(folder['id'], True))
        for item in index['sessions']:
            parent = folders.get(item['folder'])
            if parent is None:
                continue
            row = QTreeWidgetItem([item['name']])
            row.setToolTip(0, item['name'] + '\n右键可重命名、移动或删除')
            row.setData(0, Qt.ItemDataRole.UserRole, ('session', item['id']))
            parent.addChild(row)
            self.rows[item['id']] = row
            if item['id'] == current_id:
                current = item
                self.setCurrentItem(row)
        if current_id is None and folder_id in folders:
            self.setCurrentItem(folders[folder_id])
        return current

    def drawBranches(self, painter, rect, index):
        pass

    def mousePressEvent(self, event):
        row = self.itemAt(event.position().toPoint())
        if row and event.button() == Qt.MouseButton.LeftButton:
            rect = self.visualItemRect(row)
            kind, identifier = row.data(0, Qt.ItemDataRole.UserRole)
            depth, parent = 0, row.parent()
            while parent is not None:
                depth += 1
                parent = parent.parent()
            arrow_x = rect.x() + depth * 14
            if kind == 'folder' and arrow_x <= event.position().x() <= arrow_x + 39:
                row.setExpanded(not row.isExpanded())
                event.accept()
                return
            offset = rect.right() - event.position().x()
            if offset < 27:
                self.menuRequested.emit(row, self.viewport().mapToGlobal(event.position().toPoint()))
                return
        super().mousePressEvent(event)
