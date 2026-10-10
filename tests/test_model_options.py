"""Both desktop platforms use the same choices without changing saved selections."""
import os
import subprocess
import sys

import pytest

from linguaflow.model_options import download_catalog, model_catalog, recommended_selection


@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_download_catalog_and_recommendation_share_identifiers(system):
    selection = recommended_selection(system)
    entries = download_catalog(system)
    assert ('asr', selection['backend'], selection['asr_model']) in [row[2:] for row in entries]
    assert ('translation', selection['translation_engine'], selection['translation_model']) in [row[2:] for row in entries]
    for _title, _description, _kind, engine, model in entries:
        assert model in dict(model_catalog(engine)).values()
    assert selection['translation_engine'] == 'llama'
    if system == 'win32':
        assert all(row[3] != 'qwen3-mlx' for row in entries)


@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_desktop_backend_device_and_model_choices_roundtrip(tmp_path, system):
    code = '''
import os, sys
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import STYLE, Window
from linguaflow.model_options import MLX_MODEL, recommended_selection
sys.platform = os.environ['FIXTURE_PLATFORM']
app = QApplication([])
app.setStyleSheet(STYLE)
prefs = QSettings(str(Path(os.environ['AGENTSCRIBE_LIBRARY']) / 'prefs.ini'), QSettings.Format.IniFormat)
def window(): return Window(discover=False, prefs=prefs)
def values(combo): return tuple(combo.itemData(i) for i in range(combo.count()))
w = window()
m = w.model_manager
mac = sys.platform == 'darwin'
# The missing-model prompt downloads the effective first-use choice. Only Mac
# has a first-use preset; explicit choices must never be replaced by it.
initial = m.preparation_selection()
expected = recommended_selection() if mac else initial
assert w.preparation_selection() == expected
downloads = []
m.prepare_selected = lambda selection, **kwargs: downloads.append((selection.copy(), kwargs))
w.prepare_recommended_models(only='asr')
assert downloads == [(expected, {'only': 'asr'})]
assert m.preparation_selection() == expected
assert values(m.backend) == (('wlk-whisper', 'qwen3-streaming', 'qwen3-mlx') if mac else
                             ('wlk-whisper', 'qwen3-streaming'))
assert values(w.compute) == (('cpu', 'mlx') if mac else ('cpu', 'cuda'))
models = tuple(m.qwen_model.itemText(i) for i in range(m.qwen_model.count()))
assert (MLX_MODEL in models) == mac
m.backend.setCurrentIndex(m.backend.findData('qwen3-streaming'))
if mac:
    m.qwen_model.setCurrentText('Qwen/Qwen3-ASR-1.7B')
    m.backend.setCurrentIndex(m.backend.findData('qwen3-mlx'))
    assert w.compute.currentData() == 'mlx' and not w.compute.isEnabled()
    assert m.qwen_model.currentText() == MLX_MODEL
    local = str(Path(os.environ['AGENTSCRIBE_LIBRARY']) / '本地模型')
    m.qwen_model.setCurrentText(local)
    w.sync_asr_device()
    assert m.qwen_model.currentText() == local
    m.backend.setCurrentIndex(m.backend.findData('qwen3-streaming'))
    assert w.compute.currentData() == 'cpu' and w.compute.isEnabled()
    assert m.qwen_model.currentText() == local
    m.qwen_model.setCurrentText(MLX_MODEL)
    w.sync_asr_device()
    assert m.qwen_model.currentText() == 'Qwen/Qwen3-ASR-0.6B'
else:
    w.compute.setCurrentIndex(w.compute.findData('cuda'))
    w.sync_asr_device()
    assert w.compute.currentData() == 'cuda' and w.compute.isEnabled()
m.translation_engine.setCurrentIndex(m.translation_engine.findData('llama'))
assert values(m.translation_device) == (('cpu', 'metal') if mac else ('cpu', 'cuda', 'vulkan'))
chosen = 'metal' if mac else 'cuda'
m.translation_device.setCurrentIndex(m.translation_device.findData(chosen))
m.update_translation_engine()
assert m.translation_device.currentData() == chosen
explicit = m.preparation_selection()
w.prepare_recommended_models()
assert downloads[-1] == (explicit, {'only': None})
assert m.preparation_selection() == explicit
m.translation_engine.setCurrentIndex(m.translation_engine.findData('pytorch'))
assert values(m.translation_device) == (('cpu',) if mac else ('cpu', 'cuda'))
assert m.translation_device.currentData() == ('cpu' if mac else 'cuda')
w.save()
saved = w.settings_binding.session_settings(('fixture', False))
w.close()
reopened = window()
assert reopened.settings_binding.session_settings(('fixture', False)) == saved
assert reopened.knowledge_client.process is None and reopened.session is None
assert not {'soundcard', 'sounddevice', 'pyaudio', 'PySide6.QtMultimedia'} & sys.modules.keys()
reopened.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=25,
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'FIXTURE_PLATFORM': system,
             'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
