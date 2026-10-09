"""App replacement, interrupted base copies and environment compatibility."""
import json
import shutil
import sys
from pathlib import Path

import pytest

from linguaflow import hardware, runtime_paths
from linguaflow.runtime_base import prepare_base, python_abi


def portable(tmp_path):
    root = tmp_path / '程序包' / 'python'
    executable = root / ('python.exe' if sys.platform == 'win32' else 'bin/python3')
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'portable interpreter fixture')
    (root / 'Lib').mkdir()
    (root / 'Lib/os.py').write_bytes(b'standard library fixture')
    desktop = root / 'Lib/site-packages/PySide6'
    desktop.mkdir(parents=True)
    (desktop / 'QtCore.bin').write_bytes(b'desktop is not copied into the inference base')
    return root, executable


def test_independent_base_survives_app_replacement(tmp_path):
    source, executable = portable(tmp_path)
    python, identity = prepare_base(source, tmp_path / '用户数据/runtime/base-python', executable)
    assert len(identity) == 64
    assert python.read_bytes() == executable.read_bytes()
    assert not (tmp_path / '用户数据/runtime/base-python' / identity / 'Lib/site-packages').exists()
    shutil.rmtree(source.parent)
    assert python.read_bytes() == b'portable interpreter fixture'
    assert (tmp_path / '用户数据/runtime/base-python' / identity / 'Lib/os.py').is_file()


def test_corrupt_base_is_repaired_in_a_new_slot_without_deleting_old_data(tmp_path):
    source, executable = portable(tmp_path)
    directory = tmp_path / 'runtime/base-python'
    python, old_slot = prepare_base(source, directory, executable)
    python.write_bytes(b'corrupt')
    replacement, new_slot = prepare_base(source, directory, executable, preferred_slot=old_slot)
    assert new_slot != old_slot and replacement.read_bytes() == executable.read_bytes()
    reused, slot = prepare_base(source, directory, executable, preferred_slot=new_slot)
    assert reused == replacement and slot == new_slot
    assert python.read_bytes() == b'corrupt'


def test_interrupted_copy_does_not_publish_and_can_resume(tmp_path, monkeypatch):
    source, executable = portable(tmp_path)
    directory = tmp_path / 'runtime/base-python'
    original = shutil.copy2
    calls = []
    def fail(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise OSError('disk full')
        return original(src, dst)
    monkeypatch.setattr(shutil, 'copy2', fail)
    with pytest.raises(OSError, match='disk full'):
        prepare_base(source, directory, executable)
    assert not list(directory.rglob('base.json'))
    monkeypatch.setattr(shutil, 'copy2', original)
    python, _ = prepare_base(source, directory, executable)
    assert python.is_file() and len(list(directory.rglob('base.json'))) == 1


def test_app_rollback_selects_prior_compatible_environment(tmp_path, monkeypatch):
    resources, runtime = tmp_path / 'app', tmp_path / 'runtime'
    resources.mkdir()
    (resources / 'requirements-runtime.txt').write_text('library==1')
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: resources)
    monkeypatch.setattr(runtime_paths, 'runtime_root', lambda: runtime)
    base = runtime / 'python/wlk'
    values = []
    for slot, requirement, previous in [('a' * 32, 'library==1', None), ('b' * 32, 'library==2', 'a' * 32)]:
        executable = runtime_paths.environment_python(base / slot)
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b'interpreter')
        value = {'slot': slot, 'previous': previous, 'requirements': requirement,
                 'platform': hardware.platform_target(), 'torch_version': hardware.TORCH_VERSION,
                 'python_abi': python_abi(), 'base_slot': None}
        (base / slot / 'environment.json').write_text(json.dumps(value))
        values.append(value)
    pointer = base / 'active.json'
    pointer.write_text(json.dumps(values[-1]))
    before = pointer.read_bytes()
    assert runtime_paths.runtime_python() == runtime_paths.environment_python(base / ('a' * 32))
    assert pointer.read_bytes() == before
    (resources / 'requirements-runtime.txt').write_text('library==2')
    assert runtime_paths.runtime_python() == runtime_paths.environment_python(base / ('b' * 32))
    values[-1]['python_abi'] = {'version': [2, 7]}
    pointer.write_text(json.dumps(values[-1]))
    with pytest.raises(RuntimeError, match='不匹配'):
        runtime_paths.runtime_python()


def test_previous_chain_cannot_escape_runtime(tmp_path, monkeypatch):
    resources = tmp_path / 'app'
    resources.mkdir()
    (resources / 'requirements-runtime.txt').write_text('library==2')
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: resources)
    base = tmp_path / 'runtime/python/wlk'
    base.mkdir(parents=True)
    (base / 'active.json').write_text(json.dumps({'slot': 'a' * 32, 'requirements': 'library==1',
                                                'previous': '../../other'}))
    with pytest.raises(RuntimeError, match='记录损坏'):
        runtime_paths.active_directory(base, Path('unused'), python=True)


def test_corrupt_previous_record_reports_repair_instead_of_crashing(tmp_path, monkeypatch):
    resources = tmp_path / 'app'
    resources.mkdir()
    (resources / 'requirements-runtime.txt').write_text('library==2')
    monkeypatch.setattr(runtime_paths, 'resource_root', lambda: resources)
    base = tmp_path / 'runtime/python/wlk'
    previous = base / ('b' * 32)
    previous.mkdir(parents=True)
    (previous / 'environment.json').write_text('[]')
    (base / 'active.json').write_text(json.dumps({'slot': 'a' * 32, 'requirements': 'library==1',
                                                'previous': 'b' * 32}))
    with pytest.raises(RuntimeError, match='记录损坏.*修复'):
        runtime_paths.active_directory(base, Path('unused'), python=True)
