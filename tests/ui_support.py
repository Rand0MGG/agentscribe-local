"""Bounded Qt waits for isolated UI tests; never access native audio."""
import time

from PySide6.QtWidgets import QApplication


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
