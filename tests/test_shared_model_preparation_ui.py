"""Platform simulation verifies shared entry points; no native audio or real downloads."""
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_empty_inventory_prepares_selected_models_and_shared_progress(tmp_path, system):
    code = r'''
import json, os, sys
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QPushButton
import linguaflow.app as module
sys.platform = os.environ['FIXTURE_PLATFORM']
module.Window.start_background_check = lambda *args, **kwargs: None
app = QApplication([])
folder = Path(os.environ['AGENTSCRIBE_LIBRARY'])
w = module.Window(discover=False, library_root=folder/'recordings', prefs=QSettings(str(folder/'prefs.ini'), QSettings.Format.IniFormat))
manager, workspace = w.model_manager, w.settings_workspace
assert workspace.model_browser.current() is None
commands = []
manager.prepare = lambda action, **kwargs: action()
manager.run_preparation = lambda command: commands.append(command)
button = next(b for b in workspace.findChildren(QPushButton) if b.text() == '准备识别与翻译模型')
# A cached custom selection is never replaced by preparation defaults.
manager.backend.setCurrentIndex(manager.backend.findData('qwen3-streaming'))
manager.qwen_model.setCurrentText(str(folder/'custom-qwen'))
expected = manager.preparation_selection()
button.click()
assert len(commands) == 1 and 'linguaflow.recommended_prepare' in commands[0]
assert json.loads(commands[0][commands[0].index('--selection')+1]) == expected
assert manager.preparation_selection() == expected
w.prepare_models.click()
assert len(commands) == 2
# The same progress renderer remains synchronized even while browsing other pages.
w.open_settings('使用指南')
for total, expected_max, expected_value in [(100, 1000, 500), (None, 0, None), (-1, 0, None), (100, 1000, 500)]:
    manager.show_download(dict(completed=50, total=total))
    assert manager.progress_bar.maximum() == w.preparation_progress.maximum() == expected_max
    if expected_value is not None:
        assert manager.progress_bar.value() == w.preparation_progress.value() == expected_value
assert 'soundcard' not in sys.modules and 'PySide6.QtMultimedia' not in sys.modules
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM':'offscreen', 'AGENTSCRIBE_LIBRARY':str(tmp_path),
                                 'FIXTURE_PLATFORM':system})
    assert result.returncode == 0, result.stderr


def test_prepare_preserves_partial_legacy_model_preferences(tmp_path):
    code = r'''
import os, json
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import linguaflow.app as module
module.Window.start_background_check = lambda *args, **kwargs: None
app = QApplication([])
folder = Path(os.environ['AGENTSCRIBE_LIBRARY'])
prefs = QSettings(str(folder/'prefs.ini'), QSettings.Format.IniFormat)
# Old preferences may contain a translation choice without an explicit ASR backend.
prefs.setValue('translation_engine', 'llama')
prefs.setValue('llama_model', str(folder/'custom.gguf'))
w = module.Window(discover=False, library_root=folder/'recordings', prefs=prefs)
expected = w.model_manager.preparation_selection()
commands = []
w.model_manager.prepare = lambda action, **kwargs: action()
w.model_manager.run_preparation = lambda command: commands.append(command)
w.prepare_recommended_models()
actual = json.loads(commands[0][commands[0].index('--selection')+1])
assert actual == expected and actual['translation_model'].endswith('custom.gguf')
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM':'offscreen', 'AGENTSCRIBE_LIBRARY':str(tmp_path)})
    assert result.returncode == 0, result.stderr
