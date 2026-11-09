"""Contract drift and malformed requests must fail before business side effects."""
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from linguaflow.desktop_protocol import CONTRACT, validate_params
from linguaflow.desktop_service import DesktopService


@pytest.mark.p1
def test_contract_matches_backend_signatures():
    for name, spec in CONTRACT.items():
        if 'handler' not in spec:
            continue
        args = {key: value for key, value in inspect.signature(getattr(DesktopService, spec['handler'])).parameters.items() if key != 'self'}
        fields = spec.get('backendParams', spec['params'])
        assert args.keys() == fields.keys(), name
        for key, parameter in args.items():
            assert fields[key].get('optional', False) == (parameter.default is not inspect.Parameter.empty), (name, key)


@pytest.mark.p0
@pytest.mark.parametrize('method,params', [
    ('recording.start', {'path': '/outside'}), ('recording.open', {}),
    ('audio.select', {'identifier': 'x', 'loopback': 1}),
    ('playback.seek', {'milliseconds': float('nan')}),
    ('settings.set', {'values': []}), ('captions.page', {'start': True}),
    ('recording.export', {'path': None}),
])
def test_backend_contract_rejects_invalid_requests(method, params):
    with pytest.raises(ValueError):
        validate_params(method, params)


@pytest.mark.p1
def test_contract_preserves_optional_fields_and_explicit_nulls():
    validate_params('captions.page', {})
    validate_params('captions.page', {'locate': None, 'start': 0})
    validate_params('item.rename', {'identifier': None, 'name': '未开始的录音'})
    validate_params('frontend.ready', {'owner_pid': 123})
    validate_params('recording.export', {'path': '/tmp/result.txt', 'recovery': True})


@pytest.mark.p0
def test_renderer_contract_blocks_internal_routes_and_extra_paths():
    root = Path(__file__).resolve().parents[1]
    program = r'''
const assert = require('node:assert/strict');
const { validateRequest } = require('./desktop/electron/protocol.cjs');
for (const name of ['app.close', 'frontend.prepare', 'frontend.cancel', 'playback.event', 'path.recording', '__proto__'])
  assert.throws(() => validateRequest(name, {}));
for (const [name, params] of [['library.migrate',{path:'/outside'}],['frontend.ready',{owner_pid:1}],['recording.export',{path:'/outside'}],['audio.select',{identifier:'x',loopback:1}],['playback.seek',{milliseconds:Infinity}]])
  assert.throws(() => validateRequest(name, params));
validateRequest('library.migrate', {});
validateRequest('recording.export', {format:'srt'});
validateRequest('audio.select', {identifier:'fixture',loopback:false});
'''
    subprocess.run(['node', '-e', program], cwd=root, check=True, capture_output=True)
    subprocess.run(['node', 'desktop/scripts/protocol-types.cjs', '--check'], cwd=root, check=True, capture_output=True)
    assert json.loads((root/'linguaflow/desktop_contract.json').read_text()) == CONTRACT
