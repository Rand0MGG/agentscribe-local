"""No-audio regression isolation must preserve caller paths and failure evidence."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import test_no_audio as runner


@pytest.mark.p2
@pytest.mark.parametrize('arguments', [[], ['--basetemp', 'explicit'], ['--basetemp=explicit']])
def test_default_and_explicit_paths_are_preserved_without_host_shortening(monkeypatch, tmp_path,
                                                                        arguments):
    monkeypatch.setattr(runner, '__file__', str(tmp_path / 'scripts' / 'test_no_audio.py'))
    monkeypatch.setattr(runner, 'sys', SimpleNamespace(executable=sys.executable, argv=['runner', *arguments]))
    owned = []

    def run(command, *, cwd, env):
        assert cwd == tmp_path
        guard = Path(env['AGENTSCRIBE_AUDIO_GUARD_LOG']).parent
        assert (guard / 'sitecustomize.py').read_text(encoding='utf8') == runner.GUARD
        assert str(guard) == env['PYTHONPATH'].split(os.pathsep)[0]
        owned.append(guard)
        supplied = arguments or ['-q']
        assert command[3:] == supplied
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main() == 7
    assert all(not path.exists() for path in owned)


@pytest.mark.p0
def test_audio_guard_rejects_successful_suite_with_blocked_import(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, '__file__', str(tmp_path / 'scripts' / 'test_no_audio.py'))
    monkeypatch.setattr(runner, 'sys', SimpleNamespace(executable=sys.executable, argv=['runner']))

    def run(command, *, cwd, env):
        Path(env['AGENTSCRIBE_AUDIO_GUARD_LOG']).write_text('ScreenCaptureKit\n', encoding='utf8')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main() == 1
