"""Independent model controls, export snapshots, and user-file protection."""
import pytest
from ui_support import run_ui_process

WINDOW = '''
import os
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from linguaflow.core import Caption
from linguaflow.recording_export import FORMATS
from ui_support import wait_until
import linguaflow.app as module
app = QApplication([])
folder = Path(os.environ['AGENTSCRIBE_LIBRARY'])
module.Window.start_background_check = lambda *args, **kwargs: None
w = module.Window(discover=False, no_audio=True, library_root=folder/'recordings',
                  prefs=QSettings(str(folder/'prefs.ini'), QSettings.Format.IniFormat))
'''


@pytest.mark.p2
def test_inventory_provider_selection_and_busy_controls(tmp_path):
    run_ui_process('''
from PySide6.QtWidgets import QApplication
from linguaflow.model_browser import ModelBrowser
app = QApplication([])
selection = dict(backend='qwen3-streaming', asr_model='qwen', translation_engine='llama', translation_model='hy')
browser = ModelBrowser(lambda: selection, lambda: [], ('qwen3-streaming',))
browser.receive({'models': [dict(id='fixture', path='custom.gguf', name='custom', size=100,
                               kind='translation', engine='llama', deletable=True)]})
assert browser.delete_button.isEnabled()
browser.set_session_active(True)
assert not browser.delete_button.isEnabled()
browser.set_session_active(False)
browser.set_preparing(True)
assert not browser.delete_button.isEnabled()
assigned = []
browser.assigned.connect(assigned.append)
browser.choose_role('translation', 1)
assert assigned[0]['path'] == 'custom.gguf'
assert selection['translation_model'] == 'hy'
''', tmp_path)


@pytest.mark.p2
def test_model_changes_schedule_one_check_for_final_selection(tmp_path):
    run_ui_process(WINDOW + '''
import json
app.processEvents()
checks = []
w.start_background_check = lambda *args: checks.append(args)
w.model_manager.qwen_model.setCurrentText('first')
w.model_manager.qwen_model.setCurrentText('latest')
w.model_manager.llama_model.setCurrentText('latest.gguf')
wait_until(lambda: bool(checks), timeout=2)
assert len(checks) == 1
assert json.loads(checks[0][-1]) == w.preparation_selection()
''', tmp_path)


@pytest.mark.p2
def test_background_export_freezes_caption_snapshot(tmp_path):
    run_ui_process(WINDOW + '''
path = folder/'导出.txt'
QFileDialog.getSaveFileName = lambda *args: (str(path), FORMATS['txt'][0])
original = Caption(1, 1, 2, 'Hello', 'en', '你好')
w.captions = {1: original, 2: Caption(2, 2, 3, 'DRAFT', 'en', final=False)}
w.export_action.setEnabled(True)
w.export_action.trigger()
original.source = 'changed after export'
assert w.export_saver.flush()
text = path.read_text(encoding='utf-8-sig')
assert 'Hello' in text and '你好' in text and 'DRAFT' not in text and 'changed after export' not in text
assert '已导出录音定稿' in w.status.text()
''', tmp_path)


@pytest.mark.p0
def test_added_export_suffix_cannot_overwrite_existing_document_without_consent(tmp_path):
    run_ui_process(WINDOW + '''
existing = folder/'existing.txt'
existing.write_bytes(b'original user document')
w.captions = {1: Caption(1, 1, 2, 'replacement', 'en')}
QFileDialog.getSaveFileName = lambda *args: (str(folder/'existing'), FORMATS['txt'][0])
confirmations = []
QMessageBox.question = lambda *args: confirmations.append(args) or QMessageBox.StandardButton.Cancel
w.export()
assert confirmations and not w.export_saver.busy
assert existing.read_bytes() == b'original user document'
QFileDialog.getSaveFileName = lambda *args: ('', '')
w.export()
assert not w.export_saver.busy
assert existing.read_bytes() == b'original user document'
''', tmp_path)
