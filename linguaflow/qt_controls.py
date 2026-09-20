"""Small reusable Qt presentation adapters with no application dependencies."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


def text_label(text, name=None):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        label.setObjectName(name)
    return label


def data_index(combo, value):
    """Python equality also handles tuple item data (QVariant matching does not)."""
    return next((i for i in range(combo.count()) if combo.itemData(i) == value), -1)
