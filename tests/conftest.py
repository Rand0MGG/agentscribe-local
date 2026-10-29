"""Dedicated integration jobs must execute every selected check."""
import os

import pytest


@pytest.fixture(autouse=True)
def backend_events_in_legacy_qt_tests(monkeypatch):
    """Legacy UI comparisons pump the same backend dispatcher as the Electron host.

    The production backend has no Qt import; this bridge belongs only to tests
    that still exercise the retired UI as a behavioral reference.
    """
    import sys

    from linguaflow.events import Dispatcher
    dispatcher = Dispatcher.instance()
    dispatcher.stopped = False
    if 'PySide6.QtCore' in sys.modules:
        from PySide6.QtCore import QCoreApplication
        original = QCoreApplication.processEvents
        def process(*args, **kwargs):
            result = original(*args, **kwargs)
            dispatcher.process()
            return result
        monkeypatch.setattr(QCoreApplication, 'processEvents', staticmethod(process))
    yield


@pytest.fixture(autouse=True)
def qt_logs_to_stderr(monkeypatch):
    """Qt on Windows otherwise sends warnings to the debugger rather than captured pipes."""
    monkeypatch.setenv('QT_FORCE_STDERR_LOGGING', '1')


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get('AGENTSCRIBE_REQUIRE_INTEGRATIONS') != '1':
        return
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    skipped = reporter.stats.get('skipped', []) if reporter else []
    if skipped:
        reporter.write_sep('=', f'Required integration checks skipped {len(skipped)} tests')
        if exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
