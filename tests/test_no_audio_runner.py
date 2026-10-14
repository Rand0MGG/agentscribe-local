"""No-audio regression isolation must preserve caller paths and failure evidence."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import test_no_audio as runner


@pytest.mark.parametrize('system', ['nt', 'posix'])
@pytest.mark.parametrize('arguments', [[], ['--basetemp', 'explicit'], ['--basetemp=explicit']])
def test_temporary_paths_are_host_specific_and_explicit_paths_are_preserved(monkeypatch, tmp_path,
                                                                          system, arguments):
    monkeypatch.setattr(runner, '__file__', str(tmp_path / 'scripts' / 'test_no_audio.py'))
    monkeypatch.setattr(runner, 'os', SimpleNamespace(name=system, environ=dict(os.environ), pathsep=os.pathsep))
    monkeypatch.setattr(runner, 'sys', SimpleNamespace(executable=sys.executable, argv=['runner', *arguments]))
    owned = []

    def run(command, *, cwd, env):
        assert cwd == tmp_path
        guard = Path(env['AGENTSCRIBE_AUDIO_GUARD_LOG']).parent
        assert (guard / 'sitecustomize.py').read_text(encoding='utf8') == runner.GUARD
        assert str(guard) == env['PYTHONPATH'].split(os.pathsep)[0]
        owned.append(guard)
        supplied = arguments or ['-q']
        if system == 'nt' and not arguments:
            base = Path(command[-1])
            assert command[3:-2] == supplied and command[-2] == '--basetemp'
            assert base.is_dir() and base.parent == tmp_path / '.work'
            (base / 'fixture').write_text('owned regression data')
            owned.append(base)
        else:
            assert command[3:] == supplied
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main() == 7
    assert all(not path.exists() for path in owned)


def test_audio_guard_rejects_successful_suite_with_blocked_import(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, '__file__', str(tmp_path / 'scripts' / 'test_no_audio.py'))
    monkeypatch.setattr(runner, 'sys', SimpleNamespace(executable=sys.executable, argv=['runner']))

    def run(command, *, cwd, env):
        Path(env['AGENTSCRIBE_AUDIO_GUARD_LOG']).write_text('ScreenCaptureKit\n', encoding='utf8')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main() == 1
