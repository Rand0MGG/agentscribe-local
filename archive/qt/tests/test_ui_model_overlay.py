"""Interaction regressions without audio enumeration, playback or inference."""
import pytest
from ui_support import run_ui


@pytest.mark.p2
def test_model_editor_keeps_inspection_readonly_and_download_selection_explicit(tmp_path):
    run_ui(r'''
from linguaflow.llama_assets import HY_GGUF
from linguaflow.model_options import translation_devices
workspace, manager = w.settings_workspace, w.model_manager
w.open_settings('模型管理')
before = manager.preparation_selection()
entry = dict(name='Whisper base', path='/fixture/base.pt', kind='asr', engine='wlk-whisper', size=100)
dialog = workspace.open_model_settings('asr', entry=entry)
assert dialog.model_value() == entry['path'] and dialog.engine.currentData() == entry['engine']
assert not dialog.kind.isEnabled() and manager.preparation_selection() == before
assert not hasattr(dialog, 'manager')
manager.set_inventory_busy(True)
assert not dialog.download.isEnabled()
manager.set_inventory_busy(False)
assert dialog.download.isEnabled()
assert not dialog.advanced.isVisibleTo(dialog)
dialog.advanced_toggle.setChecked(True)
assert dialog.advanced.isVisibleTo(dialog)
dialog.reject()
downloads = []
manager.prepare_selected = lambda selection, **kwargs: downloads.append((selection, kwargs))
dialog = workspace.open_model_settings('translation')
dialog.engine.setCurrentIndex(dialog.engine.findData('llama'))
assert dialog.model_value() == HY_GGUF and '4-bit' in dialog.model.currentText()
dialog.model.setCurrentIndex(1)
dialog.request_download()
assert downloads[0][0]['translation_model'].startswith('hf://tencent/')
assert 'Q6_K' in downloads[0][0]['translation_model']
assert downloads[0][1] == {'only':'translation'}
assert manager.preparation_selection() == before
dialog = workspace.open_model_settings('asr')
dialog.engine.setCurrentIndex(dialog.engine.findData('qwen3-streaming'))
dialog.model.setEditText('mlx-community/Qwen3-ASR-1.7B-4bit')
dialog.request_download()
assert dialog.error.isVisibleTo(dialog) and len(downloads) == 1
dialog.engine.setCurrentIndex(dialog.engine.findData('wlk-whisper'))
dialog.model.setCurrentIndex(dialog.model.findData('base'))
dialog.parameters['endpoint_seconds'].setValue(1.5)
dialog.apply()
assert manager.preparation_selection()['asr_model'] == 'base'
assert manager.endpoint_seconds.value() == 1.5
dialog = workspace.open_model_settings('translation')
dialog.engine.setCurrentIndex(dialog.engine.findData('llama'))
device = 'metal' if 'metal' in translation_devices('llama') else 'vulkan'
invalid_device = 'vulkan' if device == 'metal' else 'metal'
assert dialog.device.findData(device) >= 0
dialog.device.setCurrentIndex(dialog.device.findData(device))
dialog.apply()
assert manager.preparation_selection()['translation_device'] == device
before_invalid = manager.preparation_selection()
try:
    manager.apply_model_settings(dict(kind='translation', selection=before_invalid, device=invalid_device, parameters={}))
except ValueError:
    pass
else:
    raise AssertionError('incompatible device must be rejected')
assert manager.preparation_selection() == before_invalid
manager.translation_engine.setCurrentIndex(manager.translation_engine.findData('llama'))
manager.llama_model.setCurrentText(HY_GGUF)
workspace.model_browser.receive({'models':[dict(name='HY 4-bit', path='/fixture/hy.gguf',
    id='/fixture/hy.gguf', kind='translation', engine='llama', size=100, deletable=True, selection=HY_GGUF)]})
assert workspace.model_browser.role_choices['translation'].itemText(0) == 'HY 4-bit'
w.current_item = None
w.session_dirty = False
w.close()
''', tmp_path)


@pytest.mark.p2
def test_catalog_downloads_models_readonly_and_bundle_selects_only_explicitly(tmp_path):
    run_ui(r'''
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QComboBox, QSpinBox, QDoubleSpinBox, QPushButton
import linguaflow.model_dialog as module
from linguaflow.llama_assets import HY_GGUF
from linguaflow.model_options import MLX_MODEL, MLX_8BIT_MODEL, QWEN_MODELS
workspace, manager = w.settings_workspace, w.model_manager
before = manager.preparation_selection()
downloads = []
manager.prepare_selected = lambda selection, **kwargs: downloads.append((selection, kwargs))
with patch.object(module, 'sys', SimpleNamespace(platform='win32')):
    dialog = workspace.open_model_catalog()
    assert not dialog.findChildren(QComboBox) and not dialog.findChildren(QSpinBox)
    assert not dialog.findChildren(QDoubleSpinBox)
    assert len(dialog.download_buttons) == 3  # Two usable models and their bundle.
    assert not hasattr(dialog, 'manager')
    manager.set_inventory_busy(True)
    assert all(not button.isEnabled() for button in dialog.download_buttons)
    manager.set_inventory_busy(False)
    assert all(button.isEnabled() for button in dialog.download_buttons)
    dialog.set_preparing(True)
    assert all(not button.isEnabled() for button in dialog.download_buttons)
    dialog.set_preparing(False)
    assert all(button.isEnabled() for button in dialog.download_buttons)
    dialog.request_bundle()
assert downloads[-1][0]['asr_model'] == QWEN_MODELS[1]
assert downloads[-1][0]['translation_model'] == HY_GGUF
assert downloads[-1][0]['translation_engine'] == 'llama'
assert downloads[-1][0]['translation_device'] == before['translation_device']
assert downloads[-1][1] == {'only': ''}
selected_bundle = manager.preparation_selection()
assert selected_bundle == downloads[-1][0]
dialog = workspace.open_model_catalog()
dialog.request_download('asr', 'qwen3-streaming', QWEN_MODELS[0])
assert manager.preparation_selection() == selected_bundle
with patch.object(module, 'sys', SimpleNamespace(platform='darwin')):
    dialog = workspace.open_model_catalog()
    dialog.bundle_selected.disconnect(workspace.select_model_bundle)  # Inspect Mac payload on Windows.
    assert len(dialog.download_buttons) == 4  # Three Mac models and their bundle.
    dialog.original['translation_device'] = 'metal'
    dialog.request_bundle()
    assert downloads[-1][0]['asr_model'] == MLX_MODEL
    assert downloads[-1][0]['backend'] == 'qwen3-mlx'
    dialog = workspace.open_model_catalog()
    dialog.request_download('asr', 'qwen3-mlx', MLX_8BIT_MODEL)
    assert downloads[-1][0]['asr_model'] == MLX_8BIT_MODEL
assert manager.preparation_selection() == selected_bundle
w.close()
''', tmp_path)
