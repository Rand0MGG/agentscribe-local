"""Dedicated integration jobs must execute every selected check."""
import os

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """Validate before -m filtering: missing priorities must not disappear."""
    priorities = {'p0', 'p1', 'p2', 'p3'}
    invalid = []
    for item in items:
        levels = [mark.name for mark in item.iter_markers() if mark.name in priorities]
        own = [mark.name for mark in item.own_markers if mark.name in priorities]
        if len(levels) != 1 or len(own) != 1:
            invalid.append(f'{item.nodeid}: {levels or "missing"}')
    if invalid:
        raise pytest.UsageError('Each test needs exactly one function-level P0-P3 marker:\n'
                                + '\n'.join(invalid))
    # Stable within each level; the default still runs every collected test.
    items.sort(key=lambda item: next(int(mark.name[1]) for mark in item.own_markers
                                     if mark.name in priorities))


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get('AGENTSCRIBE_REQUIRE_INTEGRATIONS') != '1':
        return
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    skipped = reporter.stats.get('skipped', []) if reporter else []
    if skipped:
        reporter.write_sep('=', f'Required integration checks skipped {len(skipped)} tests')
        if exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
