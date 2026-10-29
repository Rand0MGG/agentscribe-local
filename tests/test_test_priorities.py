"""Priority policy must reject omissions even when -m would hide them."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.p1
@pytest.mark.parametrize('marks,valid', [
    ('@pytest.mark.p0', True),
    ('@pytest.mark.p2\n@pytest.mark.parametrize("value", [1, 2])', True),
    ('', False),
    ('@pytest.mark.p0\n@pytest.mark.p1', False),
    ('@pytest.mark.p1\n@pytest.mark.p1', False),
    ('pytestmark = pytest.mark.p1', False),
    ('@pytest.mark.p4', False),
])
def test_collection_enforces_one_explicit_priority_before_filtering(tmp_path, marks, valid):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / 'conftest.py').write_bytes((root / 'tests/conftest.py').read_bytes())
    (tmp_path / 'pytest.ini').write_text('[pytest]\naddopts = --strict-markers\nmarkers =\n'
                                       '    p0\n    p1\n    p2\n    p3\n', encoding='utf-8')
    argument = 'value' if 'parametrize' in marks else ''
    (tmp_path / 'test_sample.py').write_text(f'import pytest\n{marks}\ndef test_sample({argument}): pass\n',
                                           encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--collect-only', '-m', 'p0 or p2'],
                            cwd=tmp_path, text=True, capture_output=True, timeout=15,
                            env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'})
    assert (result.returncode == 0) == valid, result.stdout + result.stderr
    if not valid:
        assert 'exactly one function-level' in result.stderr or 'not found in `markers`' in result.stdout


@pytest.mark.p1
def test_default_collection_runs_safety_before_features_without_dropping_levels(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / 'conftest.py').write_bytes((root / 'tests/conftest.py').read_bytes())
    (tmp_path / 'pytest.ini').write_text('[pytest]\nmarkers =\n    p0\n    p1\n    p2\n    p3\n')
    (tmp_path / 'test_order.py').write_text('import pytest\n' + '\n'.join(
        f'@pytest.mark.p{level}\ndef test_p{level}(): pass' for level in (3, 1, 2, 0)))
    result = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q'], cwd=tmp_path,
                            env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [line for line in result.stdout.splitlines() if '::test_' in line] == [
        f'test_order.py::test_p{level}' for level in range(4)]
