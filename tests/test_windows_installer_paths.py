"""Compile complete long-path payloads; never run the fixture installer."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from linguaflow.knowledge.files import file_path

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows installer compiler')
def test_real_inno_compiler_preserves_long_license_source_paths(tmp_path):
    item = json.loads((ROOT / 'packaging/windows/inno.json').read_text(encoding='utf-8'))
    compiler = ROOT / '.work/packaging' / ('inno-' + item['version']) / 'ISCC.exe'
    if not compiler.is_file():
        pytest.skip('Pinned portable Inno 7 compiler is not prepared')
    payload = tmp_path / 'installer-payload'
    notices = json.loads((ROOT / 'packaging/macos/licenses.json').read_text(encoding='utf-8'))
    longest = max(notices, key=lambda row: len(row['filename']))['filename']
    license = file_path(payload / 'Licenses/Qt-PySide' / longest)
    license.parent.mkdir(parents=True)
    license.write_text('Long license path compiler fixture.', encoding='utf-8')
    assert len(str(license)) > 260
    (payload / 'AgentScribe.exe').write_bytes(b'Non-executable compiler fixture')
    output = tmp_path / 'output'
    result = subprocess.run([str(compiler), '/DPayload=' + str(payload), '/DVersion=0.9.0',
                             '/DOutput=' + str(output), str(ROOT / 'packaging/windows/installer.iss')],
                            capture_output=True, text=True, errors='replace', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    installer = output / 'AgentScribe-0.9.0-windows-x64.exe'
    assert installer.stat().st_size > 0
    assert license.read_text(encoding='utf-8') == 'Long license path compiler fixture.'
