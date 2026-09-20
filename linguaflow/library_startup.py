"""Library discovery and legacy migration policy, with UI interactions injected."""
from .library import Library


class LibrarySelectionCancelled(Exception):
    pass


def open_library(store, install_root, *, explicit_root=None, legacy_root=None,
                 choose_directory, migration_failed, factory=Library):
    saved_root = store.value('library_directory')
    root = explicit_root or saved_root or install_root / '录音'
    selected = False
    while True:
        try:
            library = factory(root)
            break
        except (OSError, ValueError) as exc:
            if explicit_root:
                raise
            root = choose_directory(root, exc)
            if not root:
                raise LibrarySelectionCancelled()
            selected = True
    if selected:
        store.setValue('library_directory', str(root))
    if not explicit_root and not saved_root and legacy_root is not None:
        try:
            library.import_legacy(legacy_root)
        except (OSError, ValueError, KeyError) as exc:
            migration_failed(legacy_root, exc)
    return library
