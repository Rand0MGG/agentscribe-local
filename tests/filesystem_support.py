"""Real filesystem fixtures with explicit Windows privilege boundaries."""
import sys

import pytest


def directory_symlink(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if sys.platform == 'win32' and exc.winerror == 1314:
            pytest.skip('Real directory symlink requires Windows Developer Mode or symlink privilege')
        raise
