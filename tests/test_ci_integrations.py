"""Prove CI rejects missing integration coverage while ordinary suites can skip."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.p1
@pytest.mark.parametrize('required', [False, True])
def test_required_integration_job_rejects_skipped_tests(tmp_path, required):
    (tmp_path / 'conftest.py').write_text(Path(__file__).with_name('conftest.py').read_text(encoding='utf8'),
                                       encoding='utf8')
    (tmp_path / 'pytest.ini').write_text('[pytest]\nmarkers =\n    p2: independent feature\n', encoding='utf8')
    (tmp_path / 'test_missing.py').write_text(
        "import pytest\n@pytest.mark.p2\ndef test_component():\n    pytest.skip('optional component unavailable')\n", encoding='utf8')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--rootdir', str(tmp_path),
                             '--confcutdir', str(tmp_path), str(tmp_path)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'AGENTSCRIBE_REQUIRE_INTEGRATIONS': '1' if required else '0'})
    assert result.returncode == (1 if required else 0), result.stdout + result.stderr
    assert '1 skipped' in result.stdout
    assert ('Required integration checks skipped 1 tests' in result.stdout) is required
