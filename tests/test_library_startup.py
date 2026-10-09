from pathlib import Path
from types import SimpleNamespace

import pytest

from linguaflow.library_startup import LibrarySelectionCancelled, open_library


def test_default_install_location_retry_and_migration_are_ui_independent(tmp_path):
    saved, attempts, migrations = {}, [], []
    store = SimpleNamespace(value=lambda key: saved.get(key), setValue=saved.__setitem__)
    target = tmp_path / 'chosen'
    legacy = tmp_path / 'legacy'

    def factory(path):
        attempts.append(path)
        if path != target:
            raise PermissionError('read only')
        return SimpleNamespace(import_legacy=migrations.append)

    def choose(path, error):
        assert path == tmp_path / '录音' and isinstance(error, PermissionError)
        return target

    open_library(store, tmp_path, default_root=tmp_path / '录音', legacy_root=legacy, choose_directory=choose,
                 migration_failed=lambda *args: pytest.fail('unexpected migration error'), factory=factory)
    assert attempts == [tmp_path / '录音', target]
    assert saved == {'library_directory': str(target)} and migrations == [legacy]


def test_explicit_root_never_prompts_or_imports_other_libraries(tmp_path):
    store = SimpleNamespace(value=lambda _: None)

    def no_prompt(*args):
        pytest.fail('explicit root must not prompt or import')

    lib = SimpleNamespace(import_legacy=no_prompt)
    assert open_library(store, tmp_path, explicit_root=tmp_path / 'explicit', legacy_root=tmp_path,
                        choose_directory=no_prompt, migration_failed=no_prompt, factory=lambda _: lib) is lib

    def fail(_):
        raise PermissionError('read only')

    with pytest.raises(PermissionError):
        open_library(store, tmp_path, explicit_root=tmp_path, choose_directory=no_prompt,
                     migration_failed=no_prompt, factory=fail)
    with pytest.raises(LibrarySelectionCancelled):
        open_library(store, tmp_path, choose_directory=lambda *args: '',
                     migration_failed=no_prompt, factory=fail)


def test_saved_or_explicit_library_does_not_probe_unreadable_old_folder(tmp_path, monkeypatch):
    old = tmp_path / '录音'
    old.mkdir()
    monkeypatch.setattr(Path, 'iterdir', lambda _: (_ for _ in ()).throw(PermissionError('unreadable')))
    def no_prompt(*args):
        pytest.fail('explicit/saved library must not be affected by old folder permissions')
    for explicit in (True, False):
        chosen = tmp_path / 'my recordings'
        store = SimpleNamespace(value=lambda _: None if explicit else str(chosen))
        paths = []
        open_library(store, tmp_path, explicit_root=chosen if explicit else None,
                     choose_directory=no_prompt, migration_failed=no_prompt,
                     factory=lambda path: paths.append(Path(path)) or SimpleNamespace())
        assert paths == [chosen]


def test_unreadable_old_folder_prompts_instead_of_opening_empty_library(tmp_path, monkeypatch):
    old = tmp_path / '录音'
    old.mkdir()
    monkeypatch.setattr(Path, 'iterdir', lambda _: (_ for _ in ()).throw(PermissionError('unreadable')))
    saved, attempts = {}, []
    chosen = tmp_path / 'selected'
    store = SimpleNamespace(value=lambda _: None, setValue=saved.__setitem__)
    def factory(path):
        attempts.append(path)
        if path == old:
            raise PermissionError('unreadable')
        return SimpleNamespace()
    open_library(store, tmp_path, choose_directory=lambda path, error: chosen,
                 migration_failed=lambda *args: pytest.fail('unexpected migration'), factory=factory)
    assert attempts == [old, chosen]
    assert saved['library_directory'] == str(chosen)
