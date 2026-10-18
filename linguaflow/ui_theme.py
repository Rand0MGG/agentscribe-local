"""One explicit palette and stylesheet for both desktop appearances."""
import sys

WORKSPACE_RADIUS = 18
WINDOW_RADIUS = 8
WINDOW_SHADOW_MARGIN = 16
CONTROL_RADIUS = 9
GLASS_BLUR_RADIUS = 112
GLASS_WALLPAPER_OPACITY = .08

THEMES = {
    'light': dict(surface='#ffffff', glass='#f7f5f5', text='#29292d', muted='#666670',
                  draft='#707078', translation='#515158', border='#e7e5e7',
                  control='#f5f5f6', hover='#e6e6eb', selected='#dcdce2', pressed='#d3d3dc',
                  selected_hover='#ccccd4', disabled='#8b8b93',
                  primary='#29292d', primary_text='#ffffff', primary_hover='#505057',
                  primary_pressed='#171719', focus='#74747e', error='#a62d27',
                  accent='#666670', warning='#a16b25', playback='#f3f3f5'),
    'dark': dict(surface='#191919', glass='#272629', text='#ededf0', muted='#aaaab2',
                 draft='#aaaab2', translation='#c4c4cb', border='#353538',
                 control='#2b2b2e', hover='#424249', selected='#35353d', pressed='#555560',
                 selected_hover='#555560', disabled='#8d8d96',
                 primary='#ededf0', primary_text='#242428', primary_hover='#bebec8',
                 primary_pressed='#9e9eaa', focus='#b1b1bb', error='#efa4a4',
                 accent='#aaaab2', warning='#d7ac6a', playback='#252528'),
}


def theme_colors(appearance='light'):
    return THEMES['dark' if appearance == 'dark' else 'light']


def interaction_color(appearance, state):
    """Codex desktop button/row tint strengths, blended over the actual surface."""
    dark = appearance == 'dark'
    ink = (255, 255, 255) if dark else (13, 13, 13)
    opacity = {'secondary': .05, 'secondary_hover': .10, 'primary_hover': .80,
               'ghost_hover': .12 if dark else .08,
               'row_hover': .08 if dark else .05}[state]
    return (*ink, round(255 * opacity))


def appearance_style(appearance='light'):
    """Generate geometry and colors together, without inversion or legacy overlays."""
    c = theme_colors(appearance)
    def tint(state):
        return 'rgba(' + ','.join(map(str, interaction_color(appearance, state))) + ')'
    fonts = "'PingFang SC', 'Helvetica Neue'" if sys.platform == 'darwin' else "'Segoe UI', 'Microsoft YaHei UI'"
    return f'''
QWidget {{ background: transparent; color: {c['text']}; font-family: {fonts}; font-size: 13px; }}
QMainWindow, QWidget#appRoot, QWidget#workspaceContent, QWidget#feed,
QFrame#glassTopBar, QFrame#sidebar, QFrame#workspace, QFrame#workspaceHeader,
QFrame#captionRow {{ background: transparent; border: none; }}
QLabel {{ background: transparent; }}
QLabel#title, QLabel#brand, QLabel#dialogTitle {{ font-size: 21px; font-weight: 600; }}
QLabel#settingsTitle {{ font-size: 26px; font-weight: 600; }}
QLabel#settingsLabel {{ font-size: 13px; font-weight: 500; }}
QLabel#settingsSection {{ font-size: 13px; font-weight: 600; }}
QLabel#muted, QLabel#settingsHint, QLabel#pageDescription,
QLabel#timestamp, QLabel#section, QLabel#eyebrow {{ color: {c['muted']}; }}
QLabel#section, QLabel#eyebrow {{ font-size: 12px; font-weight: 500; }}
QLabel#timestamp {{ font-size: 11px; }}
QLabel#settingsHint {{ font-size: 12px; padding: 4px 0; }}
QLabel#pageDescription {{ font-size: 13px; }}
QLabel#captionFinal {{ color: {c['text']}; }}
QLabel#captionDraft {{ color: {c['draft']}; }}
QLabel#captionTranslation {{ color: {c['translation']}; font-size: 15px; }}
QLabel#translationPending {{ color: {c['muted']}; font-size: 12px; }}
QLabel#status[saveError="true"], QLabel[validationError="true"] {{ color: {c['error']}; }}
QLabel#pill, QLabel#stepBadge {{ color: {c['muted']}; background: {c['control']};
    border: 1px solid {c['border']}; border-radius: 8px; padding: 6px 12px; font-size: 12px; }}
QLabel#infoBanner, QLabel#preparationStatus {{ color: {c['muted']}; background: {c['control']};
    border: 1px solid {c['border']}; border-radius: 10px; padding: 12px 16px; font-size: 12px; }}
QFrame#settingsGroup, QWidget#modelSettingsGroup {{ background: {c['surface']};
    border: 1px solid {c['border']}; border-radius: 14px; }}
QWidget#modelSubsection {{ background: {c['control']}; border: none; border-radius: 10px; }}
QFrame#settingsRow {{ border: none; border-bottom: 1px solid {c['border']}; }}
QFrame#panel {{ background: {c['control']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#dialogSurface, QFrame#overlayShell, QFrame#footer, QFrame#controlIsland {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {WORKSPACE_RADIUS}px; }}

QPushButton {{ background: {tint('secondary')}; color: {c['text']}; border: 1px solid transparent;
    border-radius: {CONTROL_RADIUS}px; min-height: 18px; padding: 6px 12px; }}
QPushButton:hover:enabled, QPushButton:checked:enabled,
QPushButton:pressed:enabled {{ background: {tint('secondary_hover')}; }}
QPushButton[keyboardFocus="true"]:focus {{ border-color: {c['focus']}; }}
QPushButton#primary {{ background: {c['primary']}; color: {c['primary_text']};
    border-color: {c['primary']}; font-weight: 600; padding: 8px 18px; }}
QPushButton#primary:hover:enabled, QPushButton#primary:pressed:enabled {{ background: {tint('primary_hover')}; border-color: transparent; }}
QPushButton#primary[keyboardFocus="true"]:focus {{ border-color: {c['focus']}; }}
QPushButton#quiet, QPushButton#navigation, QPushButton#modelBack, QPushButton#dialogClose,
QPushButton#windowControl, QPushButton#windowClose {{ background: transparent; border-color: transparent; font-weight: 400; }}
QPushButton#quiet {{ padding: 6px; }}
QPushButton#navigation {{ text-align: left; padding: 8px; }}
QPushButton#quiet::menu-indicator {{ image: none; width: 0; }}
QPushButton#quiet:hover:enabled, QPushButton#navigation:hover:enabled,
QPushButton#modelBack:hover:enabled, QPushButton#dialogClose:hover:enabled,
QPushButton#windowControl:hover:enabled {{ background: {tint('ghost_hover')}; }}
QPushButton#quiet:pressed:enabled, QPushButton#navigation:pressed:enabled,
QPushButton#modelBack:pressed:enabled, QPushButton#dialogClose:pressed:enabled,
QPushButton#windowControl:pressed:enabled {{ background: {tint('ghost_hover')}; }}
QPushButton#danger {{ color: {c['error']}; background: transparent; border-color: {c['error']}; }}
QPushButton#danger:hover:enabled, QPushButton#danger:pressed:enabled {{ background: {tint('ghost_hover')}; }}
QPushButton#dialogClose {{ font-size: 22px; padding: 0; }}
QPushButton#windowControl, QPushButton#windowClose {{ border: none; border-radius: 0;
    min-width: 38px; min-height: 32px; padding: 0; }}
QPushButton#windowClose {{ border-top-right-radius: {WINDOW_RADIUS}px; }}
QPushButton#windowClose:hover:enabled {{ background: #c42b1c; color: #ffffff; }}
QPushButton#windowClose:pressed:enabled {{ background: #a52117; color: #ffffff; }}
QPushButton:disabled, QPushButton#primary:disabled, QPushButton#secondary:disabled,
QPushButton#danger:disabled, QPushButton#quiet:disabled, QPushButton#navigation:disabled {{
    color: {c['disabled']}; background: transparent; border-color: transparent; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {c['control']}; color: {c['text']};
    border: 1px solid {c['border']}; border-radius: {CONTROL_RADIUS}px; min-height: 18px;
    padding: 6px 10px; selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
QLineEdit:hover:enabled, QComboBox:hover:enabled, QSpinBox:hover:enabled,
QDoubleSpinBox:hover:enabled {{ background: {c['hover']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {c['focus']}; }}
QComboBox[keyboardFocus="false"]:focus {{ border-color: {c['border']}; }}
QComboBox[keyboardFocus="true"]:focus {{ border-color: {c['focus']}; }}
QLineEdit[invalid="true"] {{ border-color: {c['error']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {c['disabled']}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['text']};
    border: 1px solid {c['border']}; outline: none; selection-background-color: {c['selected']}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ background: transparent; border: none;
    subcontrol-origin: padding; subcontrol-position: top right; width: 22px; border-top-right-radius: 7px; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ background: transparent; border: none;
    subcontrol-origin: padding; subcontrol-position: bottom right; width: 22px; border-bottom-right-radius: 7px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c['hover']}; }}
QSpinBox::up-arrow, QSpinBox::down-arrow, QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{ image: none; }}
QCheckBox {{ spacing: 8px; padding: 4px 0; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['focus']};
    border-radius: 4px; background: {c['control']}; }}
QCheckBox::indicator:hover {{ background: {c['hover']}; }}
QCheckBox::indicator:checked {{ background: {c['primary']}; border-color: {c['primary']}; }}
QCheckBox:disabled {{ color: {c['disabled']}; }}

QDialog {{ background: {c['surface']}; }}
QPlainTextEdit, QTextBrowser, QTableWidget {{ background: {c['control']}; color: {c['text']};
    border: 1px solid {c['border']}; border-radius: 6px; padding: 8px;
    selection-background-color: {c['selected']}; selection-color: {c['text']}; }}
QHeaderView::section {{ background: {c['control']}; color: {c['text']};
    border: none; border-bottom: 1px solid {c['border']}; padding: 8px; }}
QTableWidget::indicator {{ width: 16px; height: 16px; background: {c['surface']}; border: 1px solid {c['focus']}; }}
QTableWidget::indicator:checked {{ background: {c['primary']}; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 8px; }}
QTabBar::tab {{ background: {c['control']}; color: {c['muted']}; border: 1px solid transparent;
    border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; padding: 8px 12px; margin-right: 4px; }}
QTabBar::tab:selected {{ background: {c['selected']}; color: {c['text']}; }}
QTabBar::tab:hover:!selected {{ background: {c['hover']}; color: {c['text']}; }}
QTreeWidget, QListWidget#settingsNavigation, QListWidget#modelInventory {{ background: transparent; border: none; outline: none; }}
QTreeWidget::branch {{ background: transparent; }}
QTreeWidget::item {{ height: 36px; padding: 0 5px; border: none; border-radius: 7px; }}
QListWidget#settingsNavigation::item {{ padding: 10px 14px; margin-bottom: 4px; border-radius: 8px; border: 1px solid transparent; }}
QListWidget#modelInventory::item {{ padding: 14px 16px; margin-bottom: 8px;
    border-radius: 10px; border: 1px solid {c['border']}; }}
QListWidget#deletedEntries, QDialog#knowledgePanel QListWidget {{ background: {c['control']};
    color: {c['text']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 6px; outline: none; }}
QListWidget#deletedEntries::item {{ padding: 14px; border-radius: 7px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {tint('secondary_hover')}; color: {c['text']}; }}
QTreeWidget::item:hover:!selected, QListWidget::item:hover:!selected {{ background: {tint('row_hover')}; }}
QTreeWidget::item:selected:hover, QListWidget::item:selected:hover {{ background: {tint('secondary_hover')}; }}
QListWidget#settingsNavigation[keyboardFocus="true"]::item:focus {{ border: 1px solid {c['focus']}; }}

QMenu {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']};
    border-radius: 12px; padding: 8px; }}
QMenu#actionMenu {{ background: transparent; border: none; padding: 16px; }}
QMenu::item {{ min-height: 22px; padding: 8px 24px 8px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['hover']}; color: {c['text']}; }}
QMenu::item:disabled {{ color: {c['disabled']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 6px 8px; }}
QMenu::icon {{ margin-left: 4px; }}
QMenu#actionMenu::indicator, QMenu#scrollActions::indicator {{ width: 14px; height: 14px; image: none; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 8px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 30px; border-radius: 3px; }}
QScrollBar::handle:vertical:hover {{ background: {c['focus']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QSplitter::handle {{ background: transparent; width: 1px; }}
QSlider::groove:horizontal {{ background: {c['border']}; height: 3px; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {c['focus']}; }}
QSlider::handle:horizontal {{ background: {c['focus']}; width: 10px; margin: -4px 0; border-radius: 5px; }}
QSlider::handle:horizontal:hover {{ background: {c['text']}; }}
QSlider#playbackSeek::groove:horizontal {{ height: 4px; border-radius: 2px; }}
QSlider#playbackSeek::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider#playbackSeek::sub-page:horizontal {{ border-radius: 2px; }}
QSlider#playbackVolumeSlider::groove:vertical {{ width: 4px; background: {c['border']}; border-radius: 2px; }}
QSlider#playbackVolumeSlider::add-page:vertical {{ background: {c['focus']}; border-radius: 2px; }}
QSlider#playbackVolumeSlider::handle:vertical {{ height: 14px; margin: 0 -5px;
    background: {c['text']}; border: none; border-radius: 7px; }}
QProgressBar {{ background: {c['control']}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {c['focus']}; border-radius: 3px; }}

QFrame#feedbackToast {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 9px; }}
QLabel#feedbackText {{ color: {c['muted']}; font-size: 12px; }}
QLabel#feedbackText[error="true"] {{ color: {c['error']}; }}
QFrame#feedbackToast QPushButton {{ padding: 4px 6px; min-height: 18px; }}
QFrame#downloadCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#downloadCard QLabel#preparationStatus {{ background: transparent; border: none; padding: 0; }}
QFrame#controlIsland QComboBox[islandChoice="true"], QFrame#controlIsland QPushButton[islandChoice="true"] {{
    min-height: 0; padding: 0; background: transparent; border: none; }}
QFrame#controlIsland QPushButton {{ padding: 0; min-height: 0; }}
QFrame#controlIsland QPushButton#primary[transportControl="true"],
QFrame#controlIsland QPushButton#secondary[transportControl="true"] {{ background: transparent; border: none;
    border-radius: 20px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; }}
QLabel#recordingState {{ color: {c['text']}; font-weight: 600; }}
'''


# Existing preview/package entrypoints import this ready-to-use default.
STYLE = appearance_style('light')
