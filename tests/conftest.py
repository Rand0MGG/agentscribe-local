"""Dedicated integration jobs must execute every selected check."""
import os

import pytest


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
