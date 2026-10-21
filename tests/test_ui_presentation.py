"""User-visible regressions in an isolated Qt process, with no audio discovery."""
import os

from ui_support import run_ui_process


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
    run_ui_process(code, timeout=20,
                   env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
