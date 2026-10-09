"""A clean installation must not accidentally depend on the developer's Node."""
import sys
from pathlib import Path

import pytest

from linguaflow import runtime_paths


@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_bundle_owns_node_and_npm_without_path(tmp_path, monkeypatch, system):
    monkeypatch.setattr(sys, 'platform', system)
    root, runtime = tmp_path / '只读 应用', tmp_path / '用户 数据'
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: root)
    monkeypatch.setattr(runtime_paths, 'runtime_root', lambda: runtime)
    monkeypatch.setattr(runtime_paths, 'packaged', lambda: True)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda *_: pytest.fail('bundles must not use PATH'))
    suffix = 'node.exe' if system == 'win32' else 'bin/node'
    node = root / 'node' / suffix
    node.parent.mkdir(parents=True)
    node.write_bytes(b'node')
    assert runtime_paths.node_executable() == node
    with pytest.raises(RuntimeError, match='缺少 npm'):
        runtime_paths.npm_command(node)
    relative = 'node_modules/npm/bin/npm-cli.js' if system == 'win32' else 'lib/node_modules/npm/bin/npm-cli.js'
    npm = root / 'node' / relative
    npm.parent.mkdir(parents=True)
    npm.write_text('npm')
    assert runtime_paths.npm_command(node) == [str(node), str(npm)]
    owned = runtime / 'node' / suffix
    owned.parent.mkdir(parents=True)
    owned.write_bytes(b'new node')
    assert runtime_paths.node_executable() == owned


def test_incomplete_bundle_does_not_use_system_node(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: tmp_path)
    monkeypatch.setattr(runtime_paths, 'runtime_root', lambda: tmp_path / 'runtime')
    monkeypatch.setattr(runtime_paths, 'packaged', lambda: True)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda *_: '/developer/node')
    with pytest.raises(RuntimeError, match='缺少 Node'):
        runtime_paths.node_executable()


def test_source_keeps_existing_node_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: tmp_path)
    monkeypatch.setattr(runtime_paths, 'runtime_root', lambda: tmp_path / 'runtime')
    monkeypatch.setattr(runtime_paths, 'packaged', lambda: False)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda name: '/system/' + name)
    assert runtime_paths.node_executable() == Path('/system/node')
    assert runtime_paths.npm_command(Path('/system/node')) == [
        '/system/' + ('npm.cmd' if sys.platform == 'win32' else 'npm')]
