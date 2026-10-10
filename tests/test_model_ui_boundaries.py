"""Inventory is usable without a manager's controls; export owns an immutable snapshot."""
import os
import subprocess
import sys


def test_inventory_interfaces_and_background_export(tmp_path):
    code = r'''
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from linguaflow.model_browser import ModelBrowser
from linguaflow.core import Caption
from linguaflow.recording_export import FORMATS
import linguaflow.app as module
app = QApplication([])
# A plain provider proves inventory doesn't require another widget's internals.
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
import os
folder = Path(os.environ['TEST_ROOT'])
module.Window.start_background_check = lambda *args, **kwargs: None
w = module.Window(discover=False, library_root=folder/'recordings',
                  prefs=QSettings(str(folder/'prefs.ini'), QSettings.Format.IniFormat))
# Continuous control changes yield one check using the final selection.
app.processEvents()
checks=[]
w.start_background_check=lambda *args: checks.append(args)
w.model_manager.qwen_model.setCurrentText('first')
w.model_manager.qwen_model.setCurrentText('latest')
w.model_manager.llama_model.setCurrentText('latest.gguf')
QTest.qWait(250)
assert len(checks)==1
import json
assert json.loads(checks[0][-1]) == w.preparation_selection()
for kind in ('srt', 'txt', 'md'):
    path = folder / ('导出.' + kind)
    QFileDialog.getSaveFileName = lambda *args: (str(path), FORMATS[kind][0])
    original = Caption(1, 1, 2, 'Hello', 'en', '你好')
    w.captions = {1: original, 2: Caption(2, 2, 3, 'DRAFT', 'en', final=False)}
    w.export()
    original.source = 'changed after export'
    assert w.export_saver.flush()
    text = path.read_text(encoding='utf-8-sig')
    assert 'Hello' in text and '你好' in text and 'DRAFT' not in text and 'changed after export' not in text
    assert '已导出录音定稿' in w.status.text()
# Appending a format suffix cannot silently overwrite an existing document.
existing=folder/'existing.txt'
existing.write_text('keep',encoding='utf-8')
QFileDialog.getSaveFileName=lambda *args: (str(folder/'existing'), FORMATS['txt'][0])
confirmations=[]
QMessageBox.question=lambda *args: confirmations.append(args) or QMessageBox.StandardButton.Cancel
w.export()
assert confirmations and not w.export_saver.busy
assert existing.read_text(encoding='utf-8')=='keep'
QFileDialog.getSaveFileName = lambda *args: ('', '')
w.export()
assert not w.export_saver.busy
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'TEST_ROOT': str(tmp_path), 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 0, result.stdout + result.stderr
