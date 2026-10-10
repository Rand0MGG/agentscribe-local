"""Required internal assets follow the existing cancellable ASR preparation."""
import os
import subprocess
import sys


def test_recognition_prepares_internal_segmentation_and_propagates_failure(tmp_path):
    program = '''
from pathlib import Path
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton
from linguaflow.management import ModelManager
import linguaflow.model_cache as cache

app = QApplication([])
manager = ModelManager()
asr, translation = QComboBox(), QComboBox()
asr.setEditable(True); translation.setEditable(True)
manager.choose_translation = QPushButton('fixture', manager)
manager.translation_form.addRow(manager.choose_translation)
manager.finish_setup(asr=asr, translation=translation)
manager.prepare = lambda action, **kwargs: action()
commands = []
manager.run_preparation = lambda command: commands.append(command) or 'ready'
manager.prepare_whisper('tiny')
import json
assert len(commands) == 1 and 'linguaflow.recommended_prepare' in commands[0]
selection = json.loads(commands[0][commands[0].index('--selection')+1])
assert selection['backend'] == 'wlk-whisper' and selection['asr_model'] == 'tiny'
assert commands[0][-2:] == ['--only', 'asr']
commands.clear()
manager.prepare_qwen('.')
selection = json.loads(commands[0][commands[0].index('--selection')+1])
assert selection['backend'] == 'qwen3-streaming' and selection['asr_model'] == '.'
assert not hasattr(manager, 'semantic_device') and not hasattr(manager, 'semantic_lookahead')
def fail(command):
    raise RuntimeError('required model missing')
manager.run_preparation = fail
try:
    manager.prepare_qwen('.')
except RuntimeError as exc:
    assert str(exc) == 'required model missing'
else:
    raise AssertionError('preparation must not report success without required assets')
'''
    child = subprocess.run([sys.executable, '-c', program], text=True, encoding='utf-8',
                           capture_output=True, timeout=30,
                           env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert child.returncode == 0, child.stdout + child.stderr
