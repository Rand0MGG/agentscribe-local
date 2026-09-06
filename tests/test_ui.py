import os
import subprocess
import sys


def test_fatal_error_survives_late_status_and_finish():
    # QWidget needs QApplication, whereas the engine suite uses QCoreApplication.
    code = """
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
app = QApplication([])
w = Window(discover=False)
w.session = SimpleNamespace(deleteLater=lambda: None)
w.on_failure('GPU 运行库缺失: cublas64_12.dll')
w.on_status('音频队列已满')
assert 'cublas64_12.dll' in w.status.text()
w.on_finished()
assert 'cublas64_12.dll' in w.status.text()
assert w.start_button.isEnabled()
assert 'cublas64_12.dll' in w.empty.text()
w.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
