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

    open_library(store, tmp_path, legacy_root=legacy, choose_directory=choose,
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
