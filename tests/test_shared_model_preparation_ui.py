"""Platform simulation verifies shared entry points; no native audio or real downloads."""
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_settings_sections_are_direct_and_mac_catalog_preserves_gpu_selection(tmp_path, system):
    code = r'''
import os, sys
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
import linguaflow.app as module
sys.platform = os.environ['FIXTURE_PLATFORM']
module.Window.start_background_check = lambda *args, **kwargs: None
module.Window.check_model_assets = lambda *args: None
app = QApplication([])
app.setStyle('Fusion')
folder = Path(os.environ['AGENTSCRIBE_LIBRARY'])
w = module.Window(discover=False, library_root=folder/'recordings',
                  prefs=QSettings(str(folder/'prefs.ini'), QSettings.Format.IniFormat))
w.reduce_motion.setChecked(True)
w.show()
workspace, manager = w.settings_workspace, w.model_manager
assert workspace.categories == ['常规', '聆听', '模型管理', '字幕与延迟', '运行环境', '使用指南']
assert not hasattr(workspace, 'advanced_navigation')
assert not any('更多设置' in button.text() for button in workspace.findChildren(QPushButton))
general = workspace.pages.widget(workspace.mapping['常规'])
assert not any('字幕停留在底部' in label.text() for label in general.findChildren(QLabel))
assert not any(label.objectName() == 'infoBanner' for label in general.findChildren(QLabel))
for size in ((1280, 840), (900, 650)):
    w.resize(*size)
    for mode in (0, 1):
        w.appearance.setCurrentIndex(mode)
        for category in workspace.categories:
            w.open_settings(category)
            app.processEvents()
            assert workspace.navigation.currentItem().text() == category
            assert all(not workspace.navigation.item(i).isHidden() for i in range(len(workspace.categories)))
            assert workspace.pages.currentIndex() == workspace.mapping[category]
workspace.search.setText('修复')
assert workspace.navigation.currentItem().text() == '运行环境'
workspace.search.clear()
assert all(not workspace.navigation.item(i).isHidden() for i in range(len(workspace.categories)))
downloads = []
manager.prepare_selected = lambda selection, **kwargs: downloads.append((selection, kwargs))
if sys.platform == 'darwin':
    from linguaflow.model_options import MLX_MODEL, MLX_8BIT_MODEL
    from linguaflow.llama_assets import HY_GGUF
    # Exercise the actual shared signal wiring, rather than disconnecting the Mac handler.
    manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('llama'))
    manager.translation_device.setCurrentIndex(manager.translation_device.findData('metal'))
    dialog = workspace.open_model_catalog()
    dialog.request_bundle()
    expected = manager.preparation_selection()
    assert expected == downloads[-1][0] and downloads[-1][1] == {'only': ''}
    assert expected['backend'] == 'qwen3-mlx' and expected['asr_model'] == MLX_MODEL
    assert expected['translation_model'] == HY_GGUF and expected['translation_device'] == 'metal'
    assert w.compute.currentData() == 'mlx'
    dialog = workspace.open_model_catalog()
    dialog.request_download('asr', 'qwen3-mlx', MLX_8BIT_MODEL)
    assert downloads[-1][0]['asr_model'] == MLX_8BIT_MODEL and downloads[-1][1] == {'only': 'asr'}
    assert manager.preparation_selection() == expected  # Download alone does not select.
assert w.session is None and not {'soundcard', 'sounddevice', 'pyaudio', 'PySide6.QtMultimedia'} & sys.modules.keys()
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGENTSCRIBE_LIBRARY': str(tmp_path),
                                 'FIXTURE_PLATFORM': system})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Painter not active' not in result.stderr and 'one painter at a time' not in result.stderr


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
button = next(b for b in workspace.findChildren(QPushButton) if b.text() == '检查 / 补齐当前模型')
# A cached custom selection is never replaced by preparation defaults.
manager.backend.setCurrentIndex(manager.backend.findData('qwen3-streaming'))
manager.qwen_model.setCurrentText(str(folder/'custom-qwen'))
expected = manager.preparation_selection()
button.click()
assert len(commands) == 1 and 'linguaflow.recommended_prepare' in commands[0]
assert json.loads(commands[0][commands[0].index('--selection')+1]) == expected
assert manager.preparation_selection() == expected
assert not hasattr(w, 'prepare_models')
button.click()
assert len(commands) == 2
# The single download card persists across settings pages.
w.open_settings('使用指南')
for total, expected_max, expected_value in [(100, 1000, 500), (None, 0, None), (-1, 0, None), (100, 1000, 500)]:
    manager.show_download(dict(completed=50, total=total))
    assert manager.progress_bar.maximum() == expected_max
    if expected_value is not None:
        assert manager.progress_bar.value() == expected_value
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
