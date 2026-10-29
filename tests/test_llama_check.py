"""The manual model probe must report outcomes after the adapter clears owners."""
import json
import os
import sys
from types import SimpleNamespace

import pytest

from scripts import check_llama


@pytest.mark.p2
@pytest.mark.parametrize('failed', [False, True])
def test_probe_keeps_exit_evidence_after_close_clears_adapter(tmp_path, monkeypatch, failed):
    output = tmp_path/'report'
    binary, weights = tmp_path/'binary', tmp_path/'weights'
    binary.write_bytes(b'fixture executable')
    weights.write_bytes(b'fixture weights')
    process, reader = SimpleNamespace(returncode=None), SimpleNamespace(is_alive=lambda: False)
    class Translator:
        def __init__(self):
            self.process, self.reader = process, reader
        def request(self, *args):
            return {}
        def translate(self, *args):
            if failed:
                raise ValueError('fixture inference failure')
            return 'fixture translation'
        def close(self):
            process.returncode = 0
            self.process = self.reader = None
    translator = Translator()
    monkeypatch.setattr('linguaflow.backends.create_translator', lambda *args: translator)
    monkeypatch.setattr('linguaflow.llama_assets.resolve_assets', lambda *args: (binary, weights))
    monkeypatch.setattr(sys, 'argv', ['check_llama', '--output', str(output)])
    monkeypatch.setattr(sys, 'meta_path', sys.meta_path.copy())
    for key in ('PYTHONPATH', 'AGENTSCRIBE_AUDIO_GUARD_LOG'):
        monkeypatch.setenv(key, os.environ.get(key, ''))
    if failed:
        with pytest.raises(RuntimeError, match='fixture inference failure'):
            check_llama.main()
    else:
        check_llama.main()
    result = json.loads((output/'summary.json').read_text())
    assert result['helper_exit_code'] == 0 and not result['log_reader_alive']
    assert not result['audio_access_attempted']
    assert result['error'] == ('fixture inference failure' if failed else None)
    assert result['translation'] == (None if failed else 'fixture translation')
    assert translator.process is None and translator.reader is None
