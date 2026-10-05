"""Required internal assets follow the existing cancellable ASR preparation."""
import os
import subprocess
import sys


def test_recognition_prepares_internal_segmentation_and_propagates_failure(tmp_path):
    program = '''
from pathlib import Path
from PySide6.QtWidgets import QApplication
from linguaflow.management import ModelManager
import linguaflow.model_cache as cache

app = QApplication([])
manager = ModelManager()
manager.prepare = lambda action: action()
commands = []
manager.run_preparation = lambda command: commands.append(command) or 'ready'
manager.prepare_whisper('tiny')
assert len(commands) == 2
assert commands[0][-3:] == ['linguaflow.wlk_prepare', 'whisper', 'tiny']
assert commands[1][-1] == 'linguaflow.semantic_model'
commands.clear()
cache.resolve_qwen_cached = lambda model: Path(model)
manager.prepare_qwen('.')
assert len(commands) == 1 and commands[0][-1] == 'linguaflow.semantic_model'
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
