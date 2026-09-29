"""Presentation tokens shared by settings, menus and secondary windows."""

SURFACE_STYLE = """
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
