"""Recording-library tree presentation; no session or main-window dependencies."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem

from .ui_theme import interaction_color


class LibraryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(36 if self.parent().property('iconOnly') else 200, 36)

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
            painter.drawRoundedRect(QRectF(option.rect).adjusted(.5, .5, -.5, -.5), 8, 8)
        depth, parent = 0, index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        x = option.rect.x() + depth * 14
        kind, _ = index.data(Qt.ItemDataRole.UserRole)
        compact = self.parent().property('iconOnly')
        if compact:
            x = option.rect.center().x() - (19 if kind == 'folder' else 15.5)
        y = option.rect.center().y()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor('#666670' if light else '#aaaab2'), 1.45))
        if kind == 'folder':
            expanded = bool(option.state & QStyle.StateFlag.State_Open)
            points = [(x + 30, y - 2), (x + 33, y + 1), (x + 36, y - 2)] if expanded else [
                (x + 31, y - 4), (x + 34, y - 1), (x + 31, y + 2)]
            if not compact:
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
        if compact:
            painter.restore()
            return
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
        self._expanded_before_compact = set()
        self._selection_before_compact = None
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
            row.setToolTip(0, self.folder_tooltip(folder['name']))
            parent = folders.get(folder.get('parent'))
            if parent:
                parent.addChild(row)
            else:
                self.addTopLevelItem(row)
            folders[folder['id']] = self.rows[folder['id']] = row
            row.setExpanded(False if self.property('iconOnly') else expanded.get(folder['id'], True))
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
        if self.property('iconOnly'):
            self._selection_before_compact = current_id if current_id in self.rows else folder_id
            self.collapseAll()
            self.select_collapsed_parent()
        return current

    def select_collapsed_parent(self):
        row = self.currentItem()
        if row:
            while row.parent():
                row = row.parent()
            self.setCurrentItem(row)

    def folder_tooltip(self, name):
        return name if self.property('iconOnly') else name + '\n点击选中文件夹 · ＋ 新建录音 · 双击折叠/展开 · 右键更多操作'

    def set_compact(self, compact):
        if compact == bool(self.property('iconOnly')):
            return
        self.setProperty('iconOnly', compact)
        for row in self.rows.values():
            if row.data(0, Qt.ItemDataRole.UserRole)[0] == 'folder':
                row.setToolTip(0, self.folder_tooltip(row.text(0)))
        if compact:
            selected = self.currentItem()
            self._selection_before_compact = selected.data(0, Qt.ItemDataRole.UserRole)[1] if selected else None
            self._expanded_before_compact = {identifier for identifier, row in self.rows.items() if row.isExpanded()}
            self.collapseAll()
            self.select_collapsed_parent()
        else:
            for identifier, row in self.rows.items():
                if row.childCount():
                    row.setExpanded(identifier in self._expanded_before_compact)
            selected = self.rows.get(self._selection_before_compact)
            ancestor = selected
            while ancestor and ancestor.parent():
                ancestor = ancestor.parent()
            if selected and self.currentItem() is ancestor:
                self.setCurrentItem(selected)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if compact
                                        else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.doItemsLayout()
        self.viewport().update()

    def drawBranches(self, painter, rect, index):
        pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.property('iconOnly'):
            # The stretched header otherwise retains its expanded section width,
            # which puts the delegate's centered icon outside the narrow viewport.
            self.setColumnWidth(0, self.viewport().width())

    def mousePressEvent(self, event):
        row = self.itemAt(event.position().toPoint())
        if row and event.button() == Qt.MouseButton.LeftButton and not self.property('iconOnly'):
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

    def mouseDoubleClickEvent(self, event):
        if self.property('iconOnly'):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if self.property('iconOnly') and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                                                        Qt.Key.Key_Plus, Qt.Key.Key_Asterisk):
            event.accept()
            return
        super().keyPressEvent(event)
