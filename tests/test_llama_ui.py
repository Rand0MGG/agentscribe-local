import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_engine_model_selection_roundtrip_and_platform_guard(tmp_path, system):
    code = r'''
import os,sys
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
import linguaflow.app as module
from linguaflow.translation_models import HY_MODEL
from linguaflow.llama_assets import HY_GGUF
sys.platform = os.environ['FIXTURE_PLATFORM']
app = QApplication([])
folder = Path(os.environ['AGENTSCRIBE_LIBRARY'])
prefs = QSettings(str(folder/'prefs.ini'), QSettings.Format.IniFormat)
def window(): return module.Window(discover=False, prefs=prefs)
w = window()
manager = w.model_manager
assert manager.translation_engine.currentData() == 'pytorch'
w.translation.setCurrentText(HY_MODEL)
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('llama'))
manager.llama_model.setCurrentText(str(folder/'new-model-f16.gguf'))
assert manager.translation_before.isEnabled()
device = 'metal' if sys.platform == 'darwin' else 'cuda'
manager.translation_device.setCurrentIndex(manager.translation_device.findData(device))
if sys.platform == 'win32':
    assert manager.translation_device.findData('vulkan') >= 0
    assert manager.translation_device.findData('metal') == -1
w.translate.setChecked(True)
settings = w.settings_binding.session_settings(('fixture', False), {})
assert settings.translation_engine == 'llama' and settings.translation_device == device
assert settings.llama_model.endswith('new-model-f16.gguf')
commands = []
manager.prepare = lambda action: action()
manager.run_preparation = lambda command: commands.append(command)
manager.prepare_translation(HY_MODEL)
assert commands[0][1] == 'scripts/install_llama.py' and commands[0][-1] == settings.llama_model
w.close()
w = window()
manager = w.model_manager
assert manager.translation_engine.currentData() == 'llama'
assert manager.translation_device.currentData() == device
assert manager.llama_model.currentText() == settings.llama_model
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('pytorch'))
assert 'PyTorch' in manager.status.text()
assert w.translation.currentText() == HY_MODEL
assert manager.translation_device.findData('vulkan') == -1
assert manager.translation_device.findData('metal') == -1
w.translation.setCurrentText('facebook/nllb-200-distilled-600M')
assert not manager.translation_before.isEnabled()
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('llama'))
assert manager.llama_model.currentText() == settings.llama_model
assert manager.translation_before.isEnabled()
manager.llama_model.setCurrentText('models/custom-f16.gguf')
assert Path(w.settings_binding.session_settings(('fixture', False), {}).llama_model).is_absolute()
w.device.addItem('fixture', ('fixture', False))
import linguaflow.llama_assets as assets
def missing(settings): raise ValueError('fixture missing assets')
assets.resolve_assets = missing
warnings = []
QMessageBox.warning = lambda *args: warnings.append(args[-1])
w.start()
assert w.session is None and 'fixture missing' in warnings[0]
if sys.platform == 'darwin':
    manager.hy_metal_button.click()
    assert manager.translation_engine.currentData() == 'llama'
    assert manager.llama_model.currentText() == HY_GGUF
    assert manager.translation_device.currentData() == 'metal'
assert 'soundcard' not in sys.modules and 'PySide6.QtMultimedia' not in sys.modules
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path), 'FIXTURE_PLATFORM': system})
    assert result.returncode == 0, result.stderr
