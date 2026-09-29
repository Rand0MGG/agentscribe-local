import ctypes
import os
import subprocess
import sys
import zipfile
from types import SimpleNamespace

import pytest

from linguaflow import llama_assets, process_platform
from linguaflow.runtime_paths import llama_server
from scripts.install_llama import unpack


@pytest.mark.parametrize('system,machine,device,count', [
    ('darwin', 'arm64', 'metal', 1), ('darwin', 'arm64', 'cpu', 1),
    ('win32', 'AMD64', 'cpu', 1), ('win32', 'AMD64', 'cuda', 3), ('win32', 'AMD64', 'vulkan', 2),
])
def test_pinned_install_plan_and_binary_location(monkeypatch, system, machine, device, count):
    monkeypatch.setattr(sys, 'platform', system)
    monkeypatch.setattr(llama_assets.platform, 'machine', lambda: machine)
    archives = llama_assets.runtime_archives(device)
    assert len(archives) == count and all(len(sha) == 64 for _, sha in archives)
    path = llama_server(device)
    if system == 'win32':
        assert path.name == 'llama-server.exe' and path.parent.name == 'windows-x64-'+device
        assert all(name.endswith('.zip') for name, _ in archives)
    else:
        assert path.name == 'llama-server' and archives[0][0].endswith('.tar.gz')


def test_unsupported_platform_is_rejected(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(llama_assets.platform, 'machine', lambda: 'x86_64')
    with pytest.raises(ValueError, match='支持'):
        llama_assets.runtime_archives('metal')


def test_installer_accepts_flat_and_nested_zip_and_rejects_escape(tmp_path):
    for prefix in ('', 'release/'):
        archive = tmp_path/('nested.zip' if prefix else 'flat.zip')
        with zipfile.ZipFile(archive, 'w') as out:
            out.writestr(prefix+'llama-server.exe', b'fixture')
            out.writestr(prefix+'ggml.dll', b'fixture-dll')
        folder = unpack(archive, tmp_path/archive.stem)
        assert (folder/'llama-server.exe').read_bytes() == b'fixture'
    bad = tmp_path/'bad.zip'
    with zipfile.ZipFile(bad, 'w') as out:
        out.writestr('../escape', b'fixture')
    with pytest.raises(ValueError, match='无效路径'):
        unpack(bad, tmp_path/'bad')
    assert not (tmp_path/'escape').exists()


def test_windows_spawn_and_cleanup_target_only_owned_tree(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    assert process_platform.spawn_options() == {'creationflags': 0x08000000}
    seen = []
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: seen.append((command, kwargs)))
    process_platform.stop_tree(SimpleNamespace(pid=12345), force=True)
    assert seen[0][0] == ['taskkill', '/PID', '12345', '/T', '/F']
    assert seen[0][1]['timeout'] == 5


@pytest.mark.parametrize('state,expected', [('connected',False), ('broken',True), ('data',False)])
def test_windows_parent_pipe_detection_does_not_use_select(monkeypatch, state, expected):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(get_osfhandle=lambda fd: 123))
    monkeypatch.setattr(process_platform.select, 'select', lambda *_: pytest.fail('Windows pipe is not a socket'))
    class Peek:
        def __call__(self, handle, buffer, size, read, available, remaining):
            available._obj.value = 1 if state == 'data' else 0
            return state != 'broken'
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **kw: SimpleNamespace(PeekNamedPipe=Peek()), raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 109, raising=False)
    monkeypatch.setattr(os, 'read', lambda *args: b'x')
    assert process_platform.parent_disconnected(0) is expected
