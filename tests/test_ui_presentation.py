"""User-visible regressions in an isolated Qt process, with no audio discovery."""
import os
import subprocess
import sys

from ui_support import assert_ui_process, finish_ui_code


def test_mac_shared_toolbar_avoids_duplicate_controls_and_respects_notch(tmp_path):
    from test_beta_features import run_ui
    run_ui(r'''
from PySide6.QtCore import QMargins
from linguaflow.app import WindowButton
w.show(); settle_geometry(w)
if sys.platform == 'darwin' and hasattr(Qt.WindowType, 'ExpandedClientAreaHint'):
    assert w.integrated_titlebar and w.title_bar.isVisible()
    # The offscreen platform renders the app menu inside the window; Cocoa
    # places it in the system menu bar. Neither may add a second safe-area strip.
    menu_height = w.menuBar().height() if w.menuBar().isVisible() else 0
    assert w.centralWidget().geometry().top() == menu_height, w.centralWidget().geometry()
    assert not w.testAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea)
    assert all(button.isHidden() for button in w.title_bar.findChildren(WindowButton))
    w.update_titlebar_inset(QMargins(0, 59, 0, 0))
    app.processEvents()
    assert w.title_bar.height() == 59 and w.pages.y() == 59, (w.title_bar.geometry(), w.pages.geometry())
    w.update_titlebar_inset(QMargins(0, 28, 0, 0))
    app.processEvents()
    assert w.title_bar.height() == 36 and w.pages.y() == 36, (w.title_bar.geometry(), w.pages.geometry())
w.close()
''', tmp_path)


def test_caption_reveal_is_bounded_and_preserves_complete_text_and_layout():
    code = r'''
from dataclasses import replace
from types import SimpleNamespace
import time
from linguaflow import caption_view
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from linguaflow.app import CaptionCard
from linguaflow.core import Caption
app = QApplication([])
app.setProperty('reduceMotion', False)
clock = [100.]
caption_view.time = SimpleNamespace(monotonic=lambda: clock[0])
caption = Caption(1, 0, 1, '', 'en', final=False)
card = CaptionCard(caption, True)
card.resize(300, 250)
card.show()
app.processEvents()
text = '逐字呈现保留完整结果。' * 8 + '\nNext line: café 👩‍💻 ± → α'
card.update_caption(replace(caption, source=text, ready=True, translation='Full translation'))
label = card.source
app.processEvents()
assert label.text() == text and label.reveal.isActive()
assert card.meta.text() == '00:00 · 优化中'
size, hint = label.size(), label.sizeHint()
assert label._duration <= .32 and label.reveal.interval() == 16
clock[0] += .045
label._advance()
assert 0 < label._visible_units < label._boundaries[-1], (label._visible_units, label._boundaries[-1], label.reveal.isActive(), label.isVisible())
label.grab()  # Exercise shaping and painting during the reveal.
assert label.size() == size and label.sizeHint() == hint
deadline = label._started + label._duration
card.update_caption(replace(caption, source=text+'更多文字', ready=True))
assert label._started + label._duration == deadline
clock[0] = deadline + .000001
label._advance()
assert not label.reveal.isActive() and label.text() == text+'更多文字'
card.update_caption(replace(caption, source='修订后的原文', final=True))
assert not label.reveal.isActive() and label.text() == '修订后的原文'
assert card.meta.text() == '00:00 · 已定稿'
card.update_caption(replace(caption, source='修订后的原文继续扩展'))
assert label.reveal.isActive()
app.setProperty('reduceMotion', True)
real_deadline = time.monotonic() + 2
while label.reveal.isActive() and time.monotonic() < real_deadline:
    QTest.qWait(10)
assert not label.reveal.isActive()
card.update_caption(replace(caption, source='new source', translation='old translation',
                            translation_source='old source', translation_phase='initial', ready=True))
assert card.target.text() == 'old translation' and card.pending.isVisibleTo(card)
card.update_caption(replace(caption, source='new source', translation='old translation',
                            translation_source='new source', translation_phase='initial', ready=True))
assert card.pending.isHidden()
card.update_caption(replace(caption, source='历史字幕全文'), animate=False)
assert label.text() == '历史字幕全文' and not label.reveal.isActive()
app.setProperty('reduceMotion', False)
label.setText('a👩')
label.set_caption_text('a👩‍💻')
assert label._visible_units in label._boundaries
label.finish_reveal()
assert label.text() == 'a👩‍💻'
card.close()
'''
    result = subprocess.run([sys.executable, '-c', finish_ui_code(code)], capture_output=True, text=True, errors='backslashreplace', timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert_ui_process(result)


def test_caption_contrast_and_native_wallpaper_platform_guard(tmp_path):
    code = r'''
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from linguaflow import ui_backdrop
from linguaflow.ui_theme import theme_colors
app = QApplication([])
for mode in ['light', 'dark']:
    c = theme_colors(mode)
    def luminance(value):
        channels = [value.redF(), value.greenF(), value.blueF()]
        channels = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
        return sum(v*w for v,w in zip(channels, [.2126, .7152, .0722]))
    a, b = sorted([luminance(QColor(c['draft'])), luminance(QColor(c['surface']))])
    assert (b+.05)/(a+.05) >= 4.5
with patch.object(ui_backdrop, 'sys', SimpleNamespace(platform='darwin')):
    with patch.object(ui_backdrop, 'mac_wallpaper_path') as native:
        assert ui_backdrop.desktop_wallpaper_path() == ''
        native.assert_not_called()
    with patch.object(QApplication, 'platformName', return_value='cocoa'):
        with patch.object(ui_backdrop, 'mac_wallpaper_path', return_value='/fixture/wallpaper.jpg') as native:
            assert ui_backdrop.desktop_wallpaper_path(123) == '/fixture/wallpaper.jpg'
            native.assert_called_once_with(123)
with patch.object(ui_backdrop, 'sys', SimpleNamespace(platform='linux')):
    assert ui_backdrop.desktop_wallpaper_path() == ''
'''
    result = subprocess.run([sys.executable, '-c', finish_ui_code(code)], capture_output=True, text=True, errors='backslashreplace', timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert_ui_process(result)


def test_recording_actions_prompt_for_models_without_automatic_downloads(tmp_path):
    code = r"""
import os
import sys
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QPushButton
from linguaflow.app import Window
app = QApplication([])
Window.start_background_check = lambda *args, **kwargs: None
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
w.show()
app.processEvents()
w.on_model_assets_checked(w.asset_check_generation, ['识别模型：fixture'])
assert w.model_prompt is None  # Startup and browsing are silent.
checks, downloads, started = [], [], []
def check(module, callback, *arguments):
    checks.append((callback, arguments))
    return object()
w.start_background_check = check
w.model_manager.prepare_selected = lambda selection, **kwargs: downloads.append((selection.copy(), kwargs))
assert w.new_recording(name='保留这份录音名称')
checks[-1][0](['识别模型：fixture'])
assert w.model_prompt.isVisible() and w.current_item['name'] == '保留这份录音名称'
w.model_prompt.reject()
assert not downloads
# Explicit model checks still prompt without downloading; recording no longer waits for this check.
start = lambda: w.check_models_for_action('start')
start()
assert w.session is None and w.model_action == 'start'
checks[-1][0](['识别模型：fixture'])
assert w.model_prompt.isVisible() and not downloads
button = next(b for b in w.model_prompt.findChildren(QPushButton) if b.text() == '下载所选模型')
expected = w.preparation_selection()
button.click()
assert downloads == [(expected, {'only': None})]
assert w.model_manager.preparation_selection() == expected
assert w.settings_workspace.navigation.currentItem().text() == '模型管理'
assert w.session is None
w.leave_settings()
w.translate.setChecked(False)
start()
assert checks[-1][1][-2:] == ('--only', 'asr')
checks[-1][0](['识别模型：fixture'])
next(b for b in w.model_prompt.findChildren(QPushButton) if b.text() == '下载所选模型').click()
assert downloads[-1][1] == {'only': 'asr'}
# A changed selection invalidates the old result and causes a fresh local check.
w.leave_settings()
start()
old = checks[-1][0]
from linguaflow.model_options import model_catalog
manager = w.model_manager
backend = manager.backend.currentData()
selector = w.asr if backend == 'wlk-whisper' else manager.qwen_model
selector.setCurrentText(next(value for _, value in model_catalog(backend) if value != selector.currentText()))
old([])
assert w.model_action == 'start' and w.session is None
w.start = lambda **kwargs: started.append(kwargs)
checks[-1][0]([])
assert started == [{'models_checked': True}] and w.model_action is None
# Leaving the recording cancels a pending start; a late check must not begin audio.
start()
w.reset_recording_view()
checks[-1][0]([])
assert len(started) == 1
w.asset_check_generation += 1
w.on_model_assets_checked(w.asset_check_generation-1, ['stale'])
assert not w.model_prompt.isVisible()
w.current_item = None
w.session_dirty = False
w.close()
"""
    result = subprocess.run([sys.executable, '-c', finish_ui_code(code)], capture_output=True, text=True, errors='backslashreplace', timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',

                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert_ui_process(result)


def test_window_frame_restores_margins_and_keeps_backdrop_lifecycle(tmp_path):
    from test_beta_features import run_ui
    run_ui(r'''
from PySide6.QtTest import QTest
from linguaflow.ui_theme import WINDOW_SHADOW_MARGIN, WINDOW_RADIUS
from linguaflow.ui_backdrop import WallpaperBackdrop
w.show()
settle_geometry(w)
root = w.centralWidget()
assert isinstance(root, WallpaperBackdrop)
if w.custom_frame:
    assert w.contentsMargins().left() == WINDOW_SHADOW_MARGIN
    assert root.corner_radius == WINDOW_RADIUS
    image = w.grab().toImage()
    scale = w.devicePixelRatioF()
    assert image.pixelColor(0, 0).alpha() == 0
    assert 0 < image.pixelColor(round(12*scale), round(w.height()/2*scale)).alpha() < 100
    w.showMaximized()
    QTest.qWait(100)
    assert w.isMaximized() and w.contentsMargins().left() == 0
    assert root.corner_radius == 0
    w.showNormal()
    QTest.qWait(100)
    assert w.contentsMargins().left() == WINDOW_SHADOW_MARGIN
    assert root.corner_radius == WINDOW_RADIUS
assert w.centralWidget() is root
w.close()
''', tmp_path)
