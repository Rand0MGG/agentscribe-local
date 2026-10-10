"""Presentation tokens shared by settings, menus and secondary windows."""
import sys

PLATFORM_STYLE = ("\nQWidget { font-family: 'PingFang SC', 'Helvetica Neue'; }\n"
                  if sys.platform == 'darwin' else '')

SURFACE_STYLE = """
QLabel#captionFinal { color: #efeff1; }
QLabel#captionDraft { color: #98989f; }
QLabel#captionTranslation { color: #bababe; font-size: 15px; }
QListWidget#modelInventory { background: transparent; border: none; outline: none; }
QListWidget#modelInventory::item { padding: 14px 16px; margin-bottom: 8px; border-radius: 10px; border: 1px solid #39393f; }
QListWidget#modelInventory::item:selected { background: #343439; color: #f0f0f5; }
QListWidget#modelInventory::item:hover:!selected { background: #29292d; }
QLabel#muted { color: #a5a5ad; line-height: 1.5; }
QLabel#settingsTitle { font-size: 26px; font-weight: 600; }
QLabel#dialogTitle { font-size: 21px; font-weight: 600; color: #f1f1f3; }
QLabel#pageDescription { color: #a6a6ae; font-size: 13px; }
QLabel#settingsLabel { font-size: 13px; font-weight: 500; }
QLabel#settingsSection { font-size: 13px; font-weight: 600; color: #d2d2d9; }
QLabel#settingsHint { color: #9999a4; font-size: 12px; padding: 4px 0; }
QLabel#infoBanner { color: #bdbdc8; background: #24262b; border: 1px solid #363940;
    border-radius: 10px; padding: 14px 16px; font-size: 12px; }
QLabel#stepBadge { background: #303238; color: #bfc7da; border-radius: 8px; padding: 7px 12px; font-size: 12px; }
QFrame#dialogSurface { background: #202022; border: 1px solid #48484e; border-radius: 18px; }
QFrame#settingsGroup, QWidget#modelSettingsGroup { background: #222224; border: 1px solid #353538; border-radius: 14px; }
QWidget#modelSubsection { background: #272729; border: none; border-radius: 10px; }
QFrame#settingsRow { border: none; border-bottom: 1px solid #323235; }
QLabel#preparationStatus { background: #25272b; border: 1px solid #373a40; border-radius: 10px; padding: 12px 16px; color: #b9bfcb; font-size: 12px; }
QLineEdit { background: #27272a; border: 1px solid #414147; border-radius: 9px; padding: 10px 12px; selection-background-color: #454e63; selection-color: #ffffff; }
QLineEdit:hover { border-color: #606068; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #98a9cc; }
QLineEdit[invalid="true"] { border-color: #de8e8e; }
QComboBox, QSpinBox, QDoubleSpinBox { border-radius: 8px; background: #2b2b2e; border: 1px solid #414147; padding: 9px 12px; }
QComboBox QAbstractItemView { background: #29292d; border: 1px solid #505057; padding: 5px; selection-background-color: #41434b; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 4px 8px; }
QPushButton { min-height: 18px; }
QPushButton#primary:disabled { background: #333337; color: #74747e; }
QPushButton#dialogClose { background: transparent; border: none; border-radius: 8px; padding: 0; font-size: 22px; color: #9797a1; }
QPushButton#dialogClose:hover { background: #37373d; color: #fafafa; }
QPushButton#danger { color: #efa4a4; background: transparent; border: 1px solid #604247; }
QPushButton#danger:hover { background: #422b31; }
QPushButton#danger:disabled { color: #777077; border-color: #3a343a; }
QMenu#actionMenu { background: transparent; border: none; padding: 8px; }
QMenu::item { min-height: 22px; padding: 9px 26px 9px 14px; border-radius: 6px; color: #dedee5; }
QMenu::item:selected { background: #3c3d43; }
QMenu::item:disabled { color: #73737e; }
QMenu::separator { height: 1px; background: #414146; margin: 6px 9px; }
QMenu::icon { margin-left: 5px; }
QListWidget#settingsNavigation::item { padding: 10px 14px; margin-bottom: 4px; }
QListWidget#settingsNavigation::item:selected { background: #343439; color: #f0f0f5; }
QListWidget#settingsNavigation::item:focus { border: 1px solid #818897; }
QListWidget#deletedEntries { background: #27272a; border: 1px solid #39393f; border-radius: 10px; padding: 6px; outline: none; }
QListWidget#deletedEntries::item { padding: 14px; border-radius: 7px; }
QListWidget#deletedEntries::item:selected { background: #3b3d45; }
QToolTip { background: #303036; color: #e6e6ed; border: 1px solid #555560; padding: 8px 10px; }
"""


def appearance_style(dark_style, appearance='light'):
    """Keep one shared stylesheet geometry and supply a matching light palette."""
    if appearance == 'dark':
        return dark_style + ACCENT_STYLE + '\nQFrame#sidebar, QFrame#glassTopBar { background: rgba(28,28,30,40); }\n'
    import re
    palette = {
        '#171717': '#ffffff', '#191919': '#ffffff', '#202022': '#ffffff',
        '#222224': '#ffffff', '#242425': '#ffffff', '#272729': '#f7f7f8',
        '#f1f1f1': '#242428', '#f1f1f3': '#242428', '#fafafa': '#242428',
        '#ffffff': '#242428', '#eeeeee': '#303034', '#ededed': '#303034',
    }
    def color(match):
        value = match[0].lower()
        if value in palette:
            return palette[value]
        r, g, b = (int(value[i:i+2], 16) for i in (1, 3, 5))
        # Neutral theme tokens share a reversed lightness, preserving hue accents.
        if max(r, g, b) - min(r, g, b) < 42:
            level = int((r + g + b) / 3)
            level = max(32, min(250, 282 - level))
            return f'#{level:02x}{level:02x}{level:02x}'
        return value
    style = re.sub(r'#[0-9a-fA-F]{6}', color, dark_style)
    return style + LIGHT_SURFACES + ACCENT_STYLE


LIGHT_SURFACES = """
QFrame#sidebar, QFrame#glassTopBar { background: rgba(247,247,249,40); border: none; }
QFrame#sidebar { border-right: 1px solid #e5e5e8; }
QFrame#workspaceHeader, QWidget#workspaceContent { background: #ffffff; }
QFrame#settingsGroup, QWidget#modelSettingsGroup { background: #ffffff; border-color: #e7e7eb; }
QFrame#footer { background: #fafafa; border-color: #e5e5e8; }
QPushButton#primary { background: #29292d; color: #ffffff; border-color: #29292d; }
QPushButton#primary:hover { background: #414146; color: #ffffff; }
QLabel#settingsTitle, QLabel#dialogTitle, QLabel#settingsSection { color: #29292d; }
QLabel#settingsHint, QLabel#pageDescription, QLabel#muted, QLabel#timestamp { color: #666670; }
QListWidget#settingsNavigation::item:selected, QTreeWidget::item:selected { background: #ededf0; color: #29292d; }
QPushButton#danger { color: #b42318; border-color: #e5c0bf; }
QPushButton#danger:disabled { color: #9999a1; border-color: #dedee3; }
QProgressBar { background: #ededf1; border: none; border-radius: 7px; color: #303034; text-align: center; }
QProgressBar::chunk { background: #a3b9dd; border-radius: 7px; }
"""


# Warm highlights identify actions without tinting the opaque reading surfaces.
ACCENT_STYLE = """
QPushButton#primary:enabled { background: #f3c547; color: #29251a; border-color: #f3c547; }
QPushButton#primary:hover:enabled { background: #ffd46a; border-color: #ffd46a; }
QPushButton#primary:pressed:enabled { background: #e8b62e; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #c59b2d; }
QPushButton#accentAction:enabled { color: #a87911; }
QPushButton#modelBack { background: transparent; border: none; color: #a87911; text-align: left; }
QCheckBox::indicator:checked { background: #f3c547; border-color: #c59b2d; }
QProgressBar::chunk { background: #f3c547; border-radius: 7px; }
"""
