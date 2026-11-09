"""Platform regressions use fake devices and never open native audio."""
import importlib.util
import platform
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.p2
def test_windows_web_session_guard_does_not_load_macos_frameworks(monkeypatch):
    import ctypes

    from linguaflow.process_platform import window_session_available
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(ctypes, 'CDLL', lambda *args: pytest.fail('Windows must not load Quartz'))
    assert window_session_available()


@pytest.mark.p2
@pytest.mark.parametrize('session', [None, 12345])
def test_quartz_probe_does_not_register_an_application_and_releases_session(monkeypatch, session):
    import ctypes

    from linguaflow.process_platform import window_session_available
    released = []
    class Function:
        def __init__(self, fn):
            self.fn = fn
        def __call__(self, *args):
            return self.fn(*args)
    graphics = SimpleNamespace(CGSessionCopyCurrentDictionary=Function(lambda: session))
    foundation = SimpleNamespace(CFRelease=Function(released.append))
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(ctypes, 'CDLL', lambda path: graphics if 'CoreGraphics' in path else foundation)
    assert window_session_available() is bool(session)
    assert released == ([session] if session else [])


@pytest.mark.p1
@pytest.mark.parametrize('target, suffix, index', [
    ('macos-arm64', '', None), ('windows-x64', '+cu128', 'cu128'),
])
def test_runtime_install_plan_is_platform_specific(monkeypatch, tmp_path, target, suffix, index):
    from linguaflow import runtime_install
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'install_runtime.py'
    spec = importlib.util.spec_from_file_location('install_runtime', path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(runtime_install, 'check_installation', lambda: target)
    monkeypatch.setattr(runtime_install, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(runtime_install, 'cache_root', lambda: tmp_path / 'cache')
    monkeypatch.setattr(runtime_install, 'prepare_sources', lambda requirements, _: requirements)
    monkeypatch.setattr(sys, 'argv', [str(path)])
    calls = []
    def run(command, **kw):
        calls.append(command)
        if 'venv' in command:
            from linguaflow.runtime_paths import environment_python
            python = environment_python(command[-1])
            python.parent.mkdir(parents=True)
            python.write_bytes(b'fixture interpreter')
    monkeypatch.setattr(runtime_install, 'run_command', run)
    installer.main()
    torch = calls[1]
    assert f'torch==2.11.0{suffix}' in torch and f'torchaudio==2.11.0{suffix}' in torch
    if index:
        assert torch[-2:] == ['--index-url', 'https://download.pytorch.org/whl/' + index]
    else:
        assert '--index-url' not in torch


@pytest.mark.p1
def test_mac_intel_or_rosetta_rejected_before_environment_creation(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'install_runtime.py'
    spec = importlib.util.spec_from_file_location('install_runtime', path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(sys, 'argv', [str(path)])
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('must not create an environment'))
    with pytest.raises(ValueError, match='Apple Silicon'):
        installer.main()
