"""Presentation tokens shared by settings, menus and secondary windows."""
import sys

WORKSPACE_RADIUS = 18
CONTROL_RADIUS = 9
GLASS_BLUR_RADIUS = 112
GLASS_WALLPAPER_OPACITY = .08

# ARGB keeps the original surface/wallpaper colour beneath hover and selection.
# This is the recording-list delegate's translucent overlay, not an opaque grey fill.
THEMES = {
    'light': dict(surface='#ffffff', glass='#f7f5f5', text='#29292d', muted='#666670',
                  draft='#707078', translation='#515158', border='#e7e5e7',
                  control='#f5f5f6', hover='#16141419', selected='#26141419', disabled='#8b8b93',
                  primary='#29292d', primary_text='#ffffff', focus='#74747e', error='#a62d27'),
    'dark': dict(surface='#191919', glass='#272629', text='#ededf0', muted='#aaaab2',
                 draft='#aaaab2', translation='#c4c4cb', border='#353538',
                 control='#2b2b2e', hover='#24000000', selected='#40000000', disabled='#8d8d96',
                 primary='#ededf0', primary_text='#242428', focus='#b1b1bb', error='#efa4a4'),
}


def theme_colors(appearance='light'):
    return THEMES['dark' if appearance == 'dark' else 'light']


def semantic_style(appearance):
    """Authoritative surface and state colours for both desktop platforms."""
    c = theme_colors(appearance)
    return f'''
QWidget {{ color: {c['text']}; }}
QFrame#glassTopBar, QFrame#sidebar {{ background: transparent; border: none; }}
QFrame#workspaceHeader {{ background: transparent; border: none; border-radius: 0;
    border-bottom: 1px solid {c['border']}; }}
QWidget#workspaceContent {{ background: transparent; }}
QLabel#captionFinal {{ color: {c['text']}; }}
QLabel#captionDraft {{ color: {c['draft']}; }}
QLabel#captionTranslation {{ color: {c['translation']}; }}
QLabel#settingsHint, QLabel#pageDescription, QLabel#muted, QLabel#timestamp,
QLabel#section, QLabel#eyebrow {{ color: {c['muted']}; }}
QLabel#translationPending {{ color: {c['muted']}; font-size: 12px; }}
QLabel#status[saveError="true"] {{ color: {c['error']}; }}
QFrame#overlayShell {{ background: {c['surface']}; border-color: {c['border']}; border-radius: {WORKSPACE_RADIUS}px; }}
QFrame#footer {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {WORKSPACE_RADIUS}px; }}
QFrame#settingsGroup, QWidget#modelSettingsGroup {{ background: {c['surface']}; border-color: {c['border']}; }}
QFrame#settingsRow {{ border-color: {c['border']}; }}
QFrame#dialogSurface {{ background: {c['surface']}; border-color: {c['border']}; border-radius: {WORKSPACE_RADIUS}px; }}
QLabel#infoBanner, QLabel#preparationStatus, QLabel#stepBadge {{ background: {c['control']};
    color: {c['muted']}; border-color: {c['border']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDialog QComboBox, QDialog QSpinBox,
QDialog QDoubleSpinBox, QPushButton, QDialog QPushButton {{ background: {c['control']};
    color: {c['text']}; border-color: {c['border']}; border-radius: {CONTROL_RADIUS}px; }}
QPushButton:hover, QDialog QPushButton:hover {{ background: {c['hover']}; border-color: {c['border']}; }}
QPushButton:checked, QPushButton:checked:hover, QPushButton:pressed {{ background: {c['selected']}; color: {c['text']}; border-color: {c['focus']}; }}
QPushButton#secondary {{ background: {c['control']}; color: {c['text']}; border-color: {c['border']}; }}
QPushButton#secondary:hover {{ background: {c['hover']}; }}
QPushButton:disabled {{ color: {c['disabled']}; background: {c['control']}; border-color: {c['border']}; }}
QPushButton#primary:enabled {{ background: {c['primary']}; color: {c['primary_text']}; border-color: {c['primary']}; }}
QPushButton#primary:hover:enabled {{ background: {'#171719' if appearance != 'dark' else '#d8d8dc'};
    color: {c['primary_text']}; border-color: {c['primary']}; }}
QPushButton#primary:pressed:enabled {{ background: {'#111113' if appearance != 'dark' else '#c9c9cf'};
    color: {c['primary_text']}; border-color: {c['primary']}; }}
QPushButton#primary:disabled {{ background: {c['control']}; color: {c['disabled']}; }}
QPushButton#quiet, QPushButton#navigation, QPushButton#modelBack, QPushButton#dialogClose,
QPushButton#windowControl, QPushButton#windowClose {{ background: transparent; border-color: transparent; }}
QPushButton#quiet:hover, QPushButton#navigation:hover, QPushButton#modelBack:hover,
QPushButton#dialogClose:hover, QPushButton#windowControl:hover {{ background: {c['hover']}; color: {c['text']}; }}
QPushButton#accentAction, QPushButton#modelBack {{ color: {c['text']}; }}
QPushButton#windowClose:hover {{ background: #c42b1c; color: #ffffff; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPushButton:focus {{ border-color: {c['focus']}; }}
QLineEdit[invalid="true"] {{ border-color: {c['error']}; }}
QFrame#controlIsland {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {WORKSPACE_RADIUS}px; }}
QFrame#controlIsland QComboBox {{ padding: 6px 28px 6px 10px; border-radius: 8px; }}
QFrame#controlIsland QPushButton {{ padding: 5px 9px; min-height: 18px; }}
QFrame#controlIsland QPushButton#primary {{ padding: 7px 12px; }}
QFrame#controlIsland QPushButton#quiet {{ padding: 4px 6px; }}
QFrame#controlIsland QProgressBar {{ background: {c['control']}; border: none; border-radius: 2px; }}
QFrame#downloadCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#downloadCard QLabel#preparationStatus {{ background: transparent; border: none; padding: 0;
    color: {c['muted']}; font-size: 12px; }}
QProgressBar#downloadProgress {{ background: {c['control']}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar#downloadProgress::chunk {{ background: {c['text']}; border-radius: 3px; }}
QListWidget#modelInventory::item {{ border-color: {c['border']}; }}
QListWidget#modelInventory::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
QListWidget#modelInventory::item:hover:!selected {{ background: {c['hover']}; }}
QSlider::groove:horizontal {{ background: {c['border']}; }}
QSlider::sub-page:horizontal, QSlider::handle:horizontal {{ background: {c['focus']}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: none; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ background: transparent; border: none;
    subcontrol-origin: padding; subcontrol-position: top right; width: 22px; border-top-right-radius: 7px; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ background: transparent; border: none;
    subcontrol-origin: padding; subcontrol-position: bottom right; width: 22px; border-bottom-right-radius: 7px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c['hover']}; }}
QSpinBox::up-arrow, QSpinBox::down-arrow,
QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{ image: none; }}
QMenu::item:selected {{ background: {c['hover']}; color: {c['text']}; }}
QMenu::item:disabled {{ color: {c['disabled']}; }}
QPushButton#danger:hover {{ background: {c['hover']}; }}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{ background: {c['hover']}; border-color: {c['border']}; }}
QListWidget#settingsNavigation::item:hover:!selected, QListWidget#deletedEntries::item:hover:!selected,
QTreeWidget::item:hover:!selected {{ background: {c['hover']}; }}
QListWidget#settingsNavigation::item:selected, QListWidget#deletedEntries::item:selected,
QTreeWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
QWidget#modelSubsection {{ background: {c['control']}; }}
QTabBar::tab:hover:!selected {{ background: {c['hover']}; color: {c['text']}; }}
QTabBar::tab:selected {{ background: {c['selected']}; color: {c['text']}; }}
QLabel#dialogTitle, QLabel#settingsTitle, QLabel#settingsSection {{ color: {c['text']}; }}
QProgressBar::chunk {{ background: {c['focus']}; }}
'''

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
        return dark_style + semantic_style('dark')
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
    return style + LIGHT_SURFACES + semantic_style('light')


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


STYLE = """
QWidget { background: transparent; color: #f1f1f1; font-family: 'Microsoft YaHei UI', 'PingFang SC', sans-serif; font-size: 13px; }
QMainWindow, QWidget#appRoot { background: transparent; }
QLabel { background: transparent; }
QLabel#title { font-size: 23px; font-weight: 700; letter-spacing: 0.3px; }
QLabel#brand { font-size: 19px; font-weight: 700; letter-spacing: -0.2px; }
QLabel#muted { color: #a8a8a8; }
QLabel#section { color: #a6a6a6; font-size: 11px; font-weight: 700; letter-spacing: 1.1px; }
QLabel#eyebrow { color: #b8b8b8; font-size: 11px; font-weight: 700; letter-spacing: 0.6px; }
QLabel#pill { color: #d8d8d8; background: rgba(74, 74, 74, 120); border: 1px solid rgba(145, 145, 145, 90); border-radius: 9px; padding: 5px 9px; font-size: 11px; font-weight: 700; }
QFrame#glassTopBar, QFrame#sidebar { background: rgba(28, 28, 28, 195); border: none; }
QFrame#sidebar { border-right: 1px solid rgba(125, 125, 125, 80); }
QFrame#workspace { background: transparent; border: none; }
QFrame#workspaceHeader { background: #171717; border: none; border-bottom: 1px solid #343434; border-top-left-radius: 13px; }
QWidget#workspaceContent { background: #171717; }
QFrame#footer { background: #252525; border: 1px solid #454545; border-radius: 12px; }
QWidget#settingsPanel { background: transparent; }
QWidget#feed { background: transparent; }
QWidget#overlay { background: rgba(20, 20, 20, 235); }
QFrame#panel { background: #292929; border: 1px solid #454545; border-radius: 10px; }
QFrame#panel:hover { background: #2d2d2d; border-color: #565656; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #2d2d2d; border: 1px solid #4d4d4d;
    padding: 8px 10px; border-radius: 7px; min-height: 18px; selection-background-color: #494949; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { background: #323232; border-color: #626262; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #888888; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #292929; color: #f1f1f1; border: 1px solid #515151; outline: none; selection-background-color: #454545; }
QPushButton { background: #2d2d2d; border: 1px solid #484848; border-radius: 7px; padding: 8px 13px; color: #ededed; }
QPushButton:hover { background: #383838; border-color: #626262; }
QPushButton:focus { border-color: #787878; }
QPushButton:pressed { background: #242424; border-color: #505050; }
QPushButton:checked { background: #404040; border-color: #6a6a6a; color: #ffffff; }
QPushButton:checked:hover { background: #464646; }
QPushButton#primary { background: #eeeeee; color: #171717; font-weight: 700; border: 1px solid #ffffff; padding: 10px 22px; }
QPushButton#primary:hover { background: #ffffff; border-color: #ffffff; }
QPushButton#primary:pressed { background: #d2d2d2; border-color: #d2d2d2; }
QPushButton#secondary { background: #323232; color: #f0f0f0; border-color: #535353; }
QPushButton#secondary:hover { background: #3d3d3d; border-color: #696969; }
QPushButton:disabled { color: #707070; background: #232323; border-color: #333333; }
QPushButton#windowControl { background: transparent; border: none; border-radius: 0; padding: 0; min-width: 46px; min-height: 44px; font-size: 16px; }
QPushButton#windowControl:hover { background: rgba(255, 255, 255, 24); }
QPushButton#windowControl:pressed { background: rgba(255, 255, 255, 14); }
QPushButton#windowClose { background: transparent; border: none; border-radius: 0; padding: 0; min-width: 48px; min-height: 44px; font-size: 18px; }
QPushButton#windowClose:hover { background: #c42b1c; color: #ffffff; }
QPushButton#windowClose:pressed { background: #a52117; }
QProgressBar { background: #2d2d2d; border: none; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #d8d8d8; border-radius: 3px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 3px; }
QScrollBar::handle:vertical { background: #454545; min-height: 30px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #626262; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QSplitter::handle { background: rgba(110, 110, 110, 55); width: 1px; }
QSplitter::handle:hover { background: rgba(160, 160, 160, 100); }
QCheckBox { spacing: 8px; padding: 4px 0; }
QCheckBox:hover { color: #ffffff; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #626262; border-radius: 4px; background: #292929; }
QCheckBox::indicator:hover { border-color: #8a8a8a; background: #333333; }
QCheckBox::indicator:checked { background: #e3e3e3; border-color: #f2f2f2; }
QPlainTextEdit { background: #1c1c1c; border: 1px solid #404040; border-radius: 7px; padding: 8px; selection-background-color: #4a4a4a; }
QTabWidget::pane { border: 1px solid #404040; border-radius: 8px; top: -1px; }
QTabBar::tab { background: #252525; color: #aaaaaa; border: 1px solid transparent; border-bottom: none; border-radius: 7px 7px 0 0; padding: 9px 12px; margin-right: 3px; }
QTabBar::tab:selected { background: #393939; color: #f2f2f2; border-color: #555555; }
QTabBar::tab:hover:!selected { background: #303030; color: #e4e4e4; }
QDialog { background: #1d1d1d; }
QDialog QWidget { background-color: transparent; }
QDialog QComboBox, QDialog QSpinBox, QDialog QDoubleSpinBox { background: #2d2d2d; }
QDialog QPushButton { background: #2d2d2d; }
QDialog QPushButton:hover { background: #383838; }
QDialog QPlainTextEdit { background: #1c1c1c; }
QToolTip { background: #303030; color: #f5f5f5; border: 1px solid #707070; padding: 5px; }
"""


STYLE += """
QWidget { font-family: 'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC'; font-size: 13px; color: #e4e4e7; }
QLabel#brand { font-size: 19px; font-weight: 600; }
QLabel#title { font-size: 21px; font-weight: 600; }
QLabel#section { color: #838389; font-size: 12px; font-weight: 500; letter-spacing: 0; }
QLabel#timestamp { color: #77777e; font-size: 11px; }
QFrame#glassTopBar, QFrame#sidebar { background: rgba(25, 25, 27, 105); border: none; }
QFrame#workspaceHeader { background: transparent; border: none; border-bottom: 1px solid #303032; }
QSplitter::handle { background: transparent; }
QTreeWidget::branch:selected { background: transparent; }
QWidget#workspaceContent { background: #191919; }
QFrame#captionRow { background: transparent; border: none; }
QFrame#footer { background: #242425; border: 1px solid #353537; border-radius: 18px; }
QPushButton { background: #2a2a2c; border: 1px solid #3b3b3e; border-radius: 8px; padding: 8px 12px; }
QPushButton#quiet, QPushButton#navigation { background: transparent; border: 1px solid transparent; font-weight: 400; }
QPushButton#navigation { text-align: left; padding: 10px 8px; }
QPushButton#quiet:hover, QPushButton#navigation:hover { background: rgba(255,255,255,14); }
QPushButton#quiet { padding: 6px; }
QPushButton#quiet::menu-indicator { image: none; width: 0; }
QPushButton#primary { background: #e9e9eb; color: #1c1c1e; border: none; border-radius: 12px; font-weight: 600; padding: 10px 18px; }
QTreeWidget { background: transparent; border: none; outline: none; color: #c8c8cd; }
QTreeWidget::item { height: 36px; padding: 0 5px; border: none; border-radius: 7px; }
QTreeWidget::item:selected { background: rgba(255,255,255,22); color: #f4f4f5; }
QTreeWidget::item:hover:!selected { background: rgba(255,255,255,10); }
QTreeWidget::branch { background: transparent; }
QMenu { background: #262628; border: 1px solid #404044; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 9px 24px; border-radius: 5px; }
QMenu::item:selected { background: #3a3a3d; }
QLineEdit { background: #29292c; border: 1px solid #444448; border-radius: 6px; padding: 9px; }
QFrame#overlayShell { background: rgba(25,25,28,242); border: 1px solid rgba(180,180,190,40); border-radius: 18px; }
QSlider::groove:horizontal { background: #38383c; height: 3px; border-radius: 1px; }
QSlider::sub-page:horizontal { background: #a9a9af; }
QSlider::handle:horizontal { background: #e1e1e4; width: 10px; margin: -4px 0; border-radius: 5px; }
QProgressBar { background: transparent; }
QProgressBar::chunk { background: #74777b; }
QLabel#settingsTitle { font-size: 27px; font-weight: 600; color: #e8e8eb; }
QLabel#settingsSection { font-size: 15px; font-weight: 600; color: #d5d5d9; }
QLabel#settingsLabel { font-size: 14px; font-weight: 600; }
QFrame#settingsGroup { background: #242425; border: 1px solid #333335; border-radius: 15px; }
QWidget#modelSettingsGroup { background: #242425; border: 1px solid #333335; border-radius: 15px; }
QFrame#settingsRow { border: none; border-bottom: 1px solid #343436; }
QListWidget#settingsNavigation { background: transparent; border: none; outline: none; }
QListWidget#settingsNavigation::item { padding: 12px 14px; border-radius: 8px; margin-bottom: 3px; }
QListWidget#settingsNavigation::item:selected { background: #353033; color: #f3f3f5; }
QListWidget#settingsNavigation::item:hover:!selected { background: rgba(255,255,255,10); }
"""
STYLE += SURFACE_STYLE + PLATFORM_STYLE
