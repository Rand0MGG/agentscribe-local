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


@pytest.mark.p0
def test_real_guard_blocks_imports_in_children_and_grandchildren(tmp_path):
    import subprocess
    guard = tmp_path/'guard'
    guard.mkdir()
    (guard/'sitecustomize.py').write_text(runner.GUARD, encoding='utf-8')
    log = tmp_path/'blocked.log'
    env = {**os.environ, 'PYTHONPATH': str(guard), 'AGENTSCRIBE_AUDIO_GUARD_LOG': str(log)}
    # A sentinel rejects imports before any real loader even if GUARD regresses.
    probe = '''
import importlib, sys, types
class Sentinel:
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in {'soundcard','sounddevice','pyaudio','ScreenCaptureKit','PySide6'}:
   raise AssertionError('audio guard missing')
installed = any(type(f).__name__ == 'NoNativeAudio' for f in sys.meta_path)
sys.meta_path.insert(1 if installed else 0, Sentinel())
qt = types.ModuleType('PySide6'); qt.__path__ = []; sys.modules['PySide6'] = qt
for name in ('soundcard','sounddevice','pyaudio','ScreenCaptureKit','PySide6.QtMultimedia'):
 try: importlib.import_module(name)
 except RuntimeError as exc: assert 'Audio hardware access blocked' in str(exc)
 else: raise AssertionError('import unexpectedly accepted')
'''
    source = probe + '\nimport subprocess\nsubprocess.run([sys.executable,"-c",' + repr(probe) + '],check=True,timeout=10)\n'
    result = subprocess.run([sys.executable, '-c', source], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = ['soundcard', 'sounddevice', 'pyaudio', 'ScreenCaptureKit', 'PySide6.QtMultimedia']
    assert log.read_text().splitlines() == expected * 2
