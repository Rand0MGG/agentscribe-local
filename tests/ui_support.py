"""Bounded Qt waits for isolated UI tests; never access native audio."""
import time
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
