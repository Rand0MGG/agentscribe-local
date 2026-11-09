"""Bounded Qt waits for isolated UI tests; never access native audio."""
import os
import subprocess
import sys
import time
from pathlib import Path
from subprocess import CompletedProcess

from PySide6.QtWidgets import QApplication

from scripts.probe_package import close_window as close_window


def finish_ui_code(code):
    """Keep Qt alive until every real application window accepts its close."""
    return code + '''
from PySide6.QtWidgets import QApplication as _QtApp
from linguaflow.app import Window as _TestWindow
from scripts.probe_package import close_window as _close_window
if _QtApp.instance() is not None:
    for _widget in _QtApp.instance().topLevelWidgets():
        if isinstance(_widget, _TestWindow):
            _close_window(_widget, _QtApp.instance())
'''


def assert_ui_process(result: CompletedProcess[str]):
    """Reject failed children and Qt drawing errors; allow unrelated platform hints."""
    output = result.stdout + result.stderr
    assert result.returncode == 0, f'Qt child exited {result.returncode}:\n{output}'
    assert not any(marker in output for marker in ('QPainter::', 'QWidgetEffectSourcePrivate::pixmap:',
                                                  'Error calling Python override',
                                                  'QProcess: Destroyed while process',
                                                  'QThread: Destroyed while thread')), (
        'Qt drawing or cleanup failure:\n' + output)


def wait_until(predicate, *, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        QApplication.instance().processEvents()
        if predicate():
            return
        assert time.monotonic() < deadline, 'Qt condition did not complete before the deadline'
        time.sleep(.01)


def settle_geometry(*widgets):
    """Wait for posted layout/resize events before comparing complete geometry.

    Stability is measured independently before and after an action; a changed
    final layout still fails the caller's equality assertion.
    """
    previous, unchanged_since = None, time.monotonic()

    def settled():
        nonlocal previous, unchanged_since
        current = tuple((widget.geometry(), widget.sizeHint()) for widget in widgets)
        if current != previous:
            previous, unchanged_since = current, time.monotonic()
        return time.monotonic() - unchanged_since >= .08

    wait_until(settled, timeout=2)


def run_ui(code, tmp_path):
    prefix = '''
import os, time
from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from linguaflow.events import Owner as QObject, Signal
from PySide6.QtWidgets import QApplication
import linguaflow.app as module
app=QApplication([])
path=Path(os.environ['AGENTSCRIBE_LIBRARY'])/'prefs.ini'
def window():
    return module.Window(discover=False,prefs=QSettings(str(path),QSettings.Format.IniFormat))
from ui_support import close_window, settle_geometry, wait_until as wait
w=window()
'''
    run_ui_process(prefix + code, tmp_path)


def run_ui_process(code, tmp_path=None, *, timeout=35, env=None):
    """Run a Qt journey with bounded shutdown and one shared diagnostic policy."""
    bootstrap = f'import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n'
    environment = {**os.environ, 'QT_QPA_PLATFORM': os.environ.get('AGENTSCRIBE_UI_PLATFORM', 'offscreen'),
                   **(env or {}), 'PYTHONIOENCODING': 'utf-8'}
    if tmp_path is not None:
        environment['AGENTSCRIBE_LIBRARY'] = str(tmp_path)
    try:
        result = subprocess.run([sys.executable, '-c', bootstrap + finish_ui_code(code)],
                                capture_output=True, text=True, encoding='utf-8', errors='backslashreplace',
                                timeout=timeout, env=environment)
    except subprocess.TimeoutExpired as exc:
        output = b'\n'.join(value if isinstance(value, bytes) else (value or '').encode('utf-8')
                            for value in (exc.stdout, exc.stderr))
        raise AssertionError(f'Qt child timed out after {timeout} seconds:\n'
                             + output.decode('utf-8', errors='replace')) from exc
    assert_ui_process(result)
