"""User-visible regressions in an isolated Qt process, with no audio discovery."""
import os
import subprocess
import sys


def test_hover_darkens_existing_colour_and_application_shortcuts_are_removed(tmp_path):
    from test_beta_features import run_ui
    run_ui(r'''
from PySide6.QtCore import QPoint
from PySide6.QtGui import QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget, QPushButton
assert not w.findChildren(QShortcut)
probe = QWidget()
probe.resize(240,100)
probe.setObjectName('hoverProbe')
probe.setStyleSheet('QWidget#hoverProbe { background: #d08ab4; }')
button = QPushButton('', probe)
button.setObjectName('quiet')
button.setGeometry(20,20,160,50)
probe.show()
app.processEvents()
QTest.mouseMove(probe, QPoint(225,85))
app.processEvents()
before = probe.grab().toImage().pixelColor(35,35)
QTest.mouseMove(button, QPoint(15,15))
app.processEvents()
after = probe.grab().toImage().pixelColor(35,35)
assert all(0 < a < b for a,b in zip(after.getRgb()[:3],before.getRgb()[:3]))
assert after.red()-after.green() > 40 and after.blue()-after.green() > 25, (before.getRgb(),after.getRgb())
assert button.graphicsEffect() is None
probe.close()
w.close()
''', tmp_path)


def test_caption_reveal_is_bounded_and_preserves_complete_text_and_layout():
    code = r'''
from dataclasses import replace
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from linguaflow.app import CaptionCard
from linguaflow.core import Caption
app = QApplication([])
app.setProperty('reduceMotion', False)
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
QTest.qWait(45)
assert 0 < label._visible_units < label._boundaries[-1], (label._visible_units, label._boundaries[-1], label.reveal.isActive(), label.isVisible())
label.grab()  # Exercise shaping and painting during the reveal.
assert label.size() == size and label.sizeHint() == hint
deadline = label._started + label._duration
card.update_caption(replace(caption, source=text+'更多文字', ready=True))
assert label._started + label._duration == deadline
QTest.qWait(350)
assert not label.reveal.isActive() and label.text() == text+'更多文字'
card.update_caption(replace(caption, source='修订后的原文', final=True))
assert not label.reveal.isActive() and label.text() == '修订后的原文'
assert card.meta.text() == '00:00 · 已定稿'
card.update_caption(replace(caption, source='修订后的原文继续扩展'))
assert label.reveal.isActive()
app.setProperty('reduceMotion', True)
QTest.qWait(25)
assert not label.reveal.isActive()
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
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Painter not active' not in result.stderr and 'one painter at a time' not in result.stderr


def test_save_feedback_model_inspection_and_recording_tree(tmp_path):
    code = r'''
import os
from dataclasses import replace
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from linguaflow.app import CaptionCard, Window
from linguaflow.core import Caption
from linguaflow.recording_save import SaveSnapshot
from linguaflow.recording_state import RecordingState
from linguaflow.workspace_widgets import RecordingDialog
app = QApplication([])
Window.check_model_assets = lambda self: None
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
w.settings_workspace.model_browser.start_check = lambda *args: None
w.reduce_motion.setChecked(True)
w.show()
assert w.new_recording(name='fixture')
w.on_caption(Caption(1, 0, 1, 'new source', 'en', 'old translation',
                     final=False, ready=True, translation_source='old source', translation_phase='initial'))
w.set_recording_state(RecordingState.LISTENING)
app.processEvents()
assert not hasattr(w, 'prepare_models')
assert w.pipeline.isHidden()
assert w.control_island.parentWidget() is w.scroll.viewport()
assert w.meter.isVisibleTo(w) and w.transport.currentWidget() is w.live_transport
w.on_stage('翻译', '加载中')
assert '翻译：加载中' in w.pipeline.text()
token = (w.save_generation, w.current_item['id'])
snapshot = SaveSnapshot(token, w.caption_version, w.current_item.copy(), (), 'draft')
w.on_saved(snapshot, 'draft', 'disk full')
w.on_status('识别正在处理')
w.update_activity()
assert '保存失败' in w.status.text() and w.status.toolTip() == 'disk full'
assert w.session_dirty and w.status.property('saveError')
w.on_saved(replace(snapshot, revision=snapshot.revision-1), 'draft', '')
assert w.save_error and w.session_dirty
w.on_saved(replace(snapshot, token=(0, 'different')), 'draft', '')
assert w.save_error
w.on_saved(snapshot, 'draft', '')
assert not w.save_error and not w.session_dirty and not w.status.property('saveError')
assert '正在聆听' in w.status.text()
card = w.cards[1]
assert card.target.text() == 'old translation' and card.pending.isVisibleTo(w)
card.update_caption(replace(w.captions[1], translation_source='new source'))
assert card.pending.isHidden()
w.set_recording_state(RecordingState.IDLE)
assert w.pipeline.isHidden() and not w.meter.isHidden()
workspace, manager = w.settings_workspace, w.model_manager
w.open_settings('模型管理')
browser = workspace.model_browser
browser.receive({'models': []})
dialog = workspace.open_model_settings('asr')
assert not dialog.engine.isVisibleTo(dialog)
dialog.advanced_toggle.setChecked(True)
assert dialog.engine.isVisibleTo(dialog)
dialog.reject()
dialog = workspace.open_model_settings('translation')
dialog.engine.setCurrentIndex(dialog.engine.findData('llama'))
assert '4-bit' in dialog.model.itemText(0)
dialog.engine.setCurrentIndex(dialog.engine.findData('pytorch'))
assert dialog.model.count() >= 3
dialog.reject()
before = manager.preparation_selection()
entry = dict(id='/fixture', path='/fixture/Qwen', name='Fixture Qwen', kind='asr',
             engine='qwen3-streaming', size=100, deletable=True)
browser.receive({'models': [entry]})
browser.open_selected()
dialog = QApplication.activeModalWidget()
assert dialog is not None and manager.preparation_selection() == before
dialog.accept()
browser.choose_role('asr', 1)
assert manager.qwen_model.currentText() == entry['path']
w.leave_settings()
w.refresh_library()
row = w.library_rows[w.folder_id]
row.setExpanded(True)
app.processEvents()
rect = w.library_tree.visualItemRect(row)
QTest.mouseClick(w.library_tree.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.x()+17, rect.center().y()))
assert not row.isExpanded()
QTest.mouseClick(w.library_tree.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.x()+17, rect.center().y()))
assert row.isExpanded()
w.session_dirty = False
w.current_item = None
w.close()
# The empty-library creation form is still usable and cancellation writes nothing.
from types import SimpleNamespace
library = SimpleNamespace(index={'folders': []}, validate_name=lambda name: None)
dialog = RecordingDialog(library, None, None)
assert next(b for b in dialog.findChildren(QPushButton) if b.text() == '创建录音').isEnabled()
dialog.validate(library)
assert dialog.result() == dialog.DialogCode.Accepted and not library.index['folders']
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Painter not active' not in result.stderr and 'one painter at a time' not in result.stderr


def test_frosted_material_is_subdued_opaque_and_shared(tmp_path):
    code = r'''
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication
from linguaflow import ui_backdrop
from linguaflow.ui_theme import theme_colors
app = QApplication([])
source = QPixmap(80, 80)
source.fill(QColor('#ff0000'))
for mode in ['light', 'dark']:
    c = theme_colors(mode)
    neutral = ui_backdrop.frosted_wallpaper(QPixmap(), QSize(160, 160), mode).toImage()
    image = ui_backdrop.frosted_wallpaper(source, QSize(160, 160), mode).toImage()
    pixel = image.pixelColor(80, 80)
    base = QColor(c['glass'])
    assert pixel.alpha() == 255 and neutral.pixelColor(80, 80).alpha() == 255
    # A saturated wallpaper must contribute a tint, never become the reading surface.
    assert abs(pixel.green()-base.green()) < 50 and pixel.red() > pixel.green()
    colours = {neutral.pixelColor(x, y).rgb() for x in range(32) for y in range(32)}
    assert 1 < len(colours) < 10  # Sub-level static grain, not coarse decorative noise.
    again = ui_backdrop.frosted_wallpaper(QPixmap(), QSize(160, 160), mode).toImage()
    assert neutral == again
    def luminance(value):
        channels = [value.redF(), value.greenF(), value.blueF()]
        channels = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
        return sum(v*w for v,w in zip(channels, [.2126, .7152, .0722]))
    a, b = sorted([luminance(QColor(c['draft'])), luminance(QColor(c['surface']))])
    assert (b+.05)/(a+.05) >= 4.5
with patch.object(ui_backdrop, 'sys', SimpleNamespace(platform='darwin')):
    with patch.object(ui_backdrop, 'mac_wallpaper_path', return_value='/fixture/wallpaper.jpg'):
        assert ui_backdrop.desktop_wallpaper_path() == '/fixture/wallpaper.jpg'
with patch.object(ui_backdrop, 'sys', SimpleNamespace(platform='linux')):
    assert ui_backdrop.desktop_wallpaper_path() == ''
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Painter not active' not in result.stderr and 'one painter at a time' not in result.stderr



def test_recording_actions_prompt_for_models_without_automatic_downloads(tmp_path):
    code = r"""
import os
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
# Another explicit start must prompt again, even after dismissing the previous one.
start = w.start
w.start_button.click()
assert w.session is None and w.model_action == 'start'
checks[-1][0](['识别模型：fixture'])
assert w.model_prompt.isVisible() and not downloads
button = next(b for b in w.model_prompt.findChildren(QPushButton) if b.text() == '下载所选模型')
expected = w.model_manager.preparation_selection()
button.click()
assert downloads == [(expected, {'only': None})]
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
w.asr.setCurrentText('medium')
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
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Painter not active' not in result.stderr and 'one painter at a time' not in result.stderr


def test_floating_controls_choices_and_hover_preserve_geometry(tmp_path):
    code = r"""
import os
from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from linguaflow.app import Window
from linguaflow.core import Caption
from linguaflow.recording_state import RecordingState
app = QApplication([])
Window.start_background_check = lambda *args, **kwargs: None
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
w.reduce_motion.setChecked(True)
w.show()
w.device.addItem('Fixture microphone with a long descriptive name', ('fixture', False))
for i in range(20):
    w.on_caption(Caption(i, i*10, i*10+5, 'Caption content stays visible beside the floating controls. '*4, 'en', '字幕可以从小岛下方经过。'*5))
w.set_recording_state(RecordingState.LISTENING)
QTest.qWait(40)
assert w.control_island.parentWidget() is w.scroll.viewport()
assert w.control_island.width() < w.scroll.viewport().width()
assert w.meter.isVisibleTo(w) and w.transport.currentWidget() is w.live_transport
for size in [(1280, 840), (900, 650)]:
    w.resize(*size)
    QTest.qWait(30)
    before = (w.control_island.geometry(), w.scroll.geometry(), w.cards[1].geometry())
    w.appearance.setCurrentIndex(1)
    QTest.qWait(30)
    assert before == (w.control_island.geometry(), w.scroll.geometry(), w.cards[1].geometry())
    w.appearance.setCurrentIndex(0)
    QTest.qWait(30)
    assert w.scroll.viewport().rect().contains(w.control_island.geometry())
w.quick_language.click()
QTest.qWait(30)
popup = w.language_popup
assert popup.isVisible()
popup.source_choice.setCurrentIndex((w.source.currentIndex()+1) % w.source.count())
assert popup.source_choice.currentIndex() == w.source.currentIndex()
popup.target_choice.showPopup()
QTest.qWait(30)
choices = popup.target_choice.view().window()
assert choices.isVisible() and choices.screen().availableGeometry().contains(choices.geometry())
previous = popup.target_choice.currentIndex()
QTest.keyClick(popup.target_choice, Qt.Key.Key_Down)
QTest.keyClick(popup.target_choice, Qt.Key.Key_Return)
assert popup.target_choice.currentIndex() != previous
assert popup.target_choice.currentIndex() == w.target.currentIndex()
popup.target_choice.hidePopup()
popup.close()
assert not popup.isVisible()
w.set_recording_state(RecordingState.IDLE)
w.playback.setProperty('available', True)
w.update_transport()
QTest.qWait(30)
assert w.transport.currentWidget() is w.playback and w.play_button.isVisibleTo(w) and w.meter.isHidden()
button = w.start_button
app.sendEvent(button, QEvent(QEvent.Type.Enter))
assert button.graphicsEffect() is None
w.grab()
app.sendEvent(button, QEvent(QEvent.Type.Leave))
w.open_settings('常规')
for _ in range(6):
    w.settings_workspace.transition.start()
    for button in w.settings_workspace.findChildren(QPushButton):
        app.sendEvent(button, QEvent(QEvent.Type.Enter))
        assert button.graphicsEffect() is None
        w.grab()
        app.sendEvent(button, QEvent(QEvent.Type.Leave))
    QTest.qWait(20)
w.release_playback()
assert not w.transport.isHidden()
assert 'PySide6.QtMultimedia' not in __import__('sys').modules
w.current_item = None
w.session_dirty = False
w.close()
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Painter not active' not in result.stderr and 'one painter at a time' not in result.stderr
