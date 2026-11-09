import os

import pytest
from ui_support import run_ui_process


@pytest.mark.p1
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
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('pytorch'))
assert manager.translation_engine.currentData() == 'pytorch'
w.translation.setCurrentText(HY_MODEL)
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('llama'))
manager.llama_model.setCurrentText(str(folder/'new-model-f16.gguf'))
device = 'metal' if sys.platform == 'darwin' else 'cuda'
manager.translation_device.setCurrentIndex(manager.translation_device.findData(device))
if sys.platform == 'win32':
    assert manager.translation_device.findData('vulkan') >= 0
    assert manager.translation_device.findData('metal') == -1
w.translate.setChecked(True)
settings = w.settings_binding.session_settings(('fixture', False))
assert settings.translation_engine == 'llama' and settings.translation_device == device
assert settings.translation_initial_before == 1 and settings.translation_before == 5
assert settings.llama_model.endswith('new-model-f16.gguf')
commands = []
manager.prepare = lambda action, **kwargs: action()
manager.run_preparation = lambda command: commands.append(command)
manager.prepare_translation(HY_MODEL)
import json
assert 'linguaflow.recommended_prepare' in commands[0]
selection = json.loads(commands[0][commands[0].index('--selection')+1])
assert selection['translation_model'] == settings.llama_model and selection['translation_device'] == device
assert commands[0][-2:] == ['--only', 'translation']
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
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('llama'))
assert manager.llama_model.currentText() == settings.llama_model
manager.llama_model.setCurrentText('models/custom-f16.gguf')
assert Path(w.settings_binding.session_settings(('fixture', False)).llama_model).is_absolute()
reference = 'hf://tencent/Hy-MT2-1.8B-GGUF/Hy-MT2-1.8B-Q8_0.gguf'
import linguaflow.llama_assets as assets
manager.llama_model.setCurrentText(reference)
settings = w.settings_binding.session_settings(('fixture', False))
assert settings.llama_model == reference
assert assets.weights_path(settings.llama_model).name == 'Hy-MT2-1.8B-Q8_0.gguf'
w.device.addItem('fixture', ('fixture', False))
import linguaflow.llama_assets as assets
def missing(settings): raise ValueError('fixture missing assets')
assets.resolve_assets = missing
from linguaflow.inference_startup import start_problem
# Asset validation now runs in Session after capture starts; exercise the same
# validator here without launching native capture in this UI settings test.
problem = start_problem(w.settings_binding.session_settings(('fixture',False)))
assert w.session is None and 'fixture missing' in problem[1]
if sys.platform == 'darwin':
    w.use_mac_profile()
    assert manager.translation_engine.currentData() == 'llama'
    assert manager.llama_model.currentText() == HY_GGUF
    assert manager.translation_device.currentData() == 'metal'
assert 'soundcard' not in sys.modules and 'PySide6.QtMultimedia' not in sys.modules
w.close()
'''
    run_ui_process(code, timeout=20,
                   env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGENTSCRIBE_LIBRARY': str(tmp_path), 'FIXTURE_PLATFORM': system})


@pytest.mark.p1
@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_background_validation_uses_only_active_translation_model(tmp_path, system):
    code = r"""
import os, sys
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
from linguaflow.app import Window
import linguaflow.llama_assets as assets
sys.platform = os.environ['FIXTURE_PLATFORM']
app = QApplication([])
prefs = QSettings(str(Path(os.environ['AGENTSCRIBE_LIBRARY'])/'prefs.ini'), QSettings.Format.IniFormat)
w = Window(discover=False, prefs=prefs)
w.device.addItem('fixture', ('fixture', False))
manager = w.model_manager
manager.backend.setCurrentIndex(manager.backend.findData('wlk-whisper'))
w.asr.setCurrentText('tiny')
w.translation.setCurrentText('')
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('llama'))
w.translate.setChecked(True)
checks, warnings, next_steps = [], [], []
assets.resolve_assets = lambda settings: checks.append(settings.translation_engine)
w.show_warning = lambda title, message: warnings.append(message)
# Validate the frozen UI settings at the background validation boundary.
from linguaflow.inference_startup import start_problem
def validate():
    problem=start_problem(w.settings_binding.session_settings(('fixture',False)))
    if problem:
        warnings.append(problem[1])
    else:
        next_steps.append('load models')
validate()
assert checks == ['llama'] and not warnings and len(next_steps) == 1
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('pytorch'))
validate()
assert len(warnings) == 1 and len(next_steps) == 1
# Disabling translation permits an empty translation model on either engine.
for engine in ('pytorch', 'llama'):
    manager.translation_engine.setCurrentIndex(manager.translation_engine.findData(engine))
    w.translate.setChecked(False)
    validate()
assert len(warnings) == 1 and len(next_steps) == 3 and checks == ['llama']
# ASR validation still applies with llama.cpp translation selected.
w.translate.setChecked(True)
w.asr.setCurrentText('')
validate()
assert len(warnings) == 2 and len(next_steps) == 3
w.close()
"""
    run_ui_process(code, timeout=20,
                   env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGENTSCRIBE_LIBRARY': str(tmp_path), 'FIXTURE_PLATFORM': system})
