"""Library discovery and legacy migration policy, with UI interactions injected."""
from pathlib import Path

from .library import Library
from .runtime_paths import recordings_root


class LibrarySelectionCancelled(Exception):
    pass


def open_library(store, install_root, *, explicit_root=None, legacy_root=None,
                 choose_directory, migration_failed, factory=Library, default_root=None):
    saved_root = store.value('library_directory')
    if not isinstance(saved_root, (str, Path)) or not str(saved_root).strip():
        saved_root = None
    old_default = install_root / '录音'
    # Existing source users retain their library; never silently move recordings
    # or open an empty new library in place of their old one.
    existing = None
    if not explicit_root and not saved_root:
        try:
            if old_default.is_dir() and any(old_default.iterdir()):
                existing = old_default
        except OSError:
            # An unreadable old library must enter the normal selection/error
            # flow, never be mistaken for no recordings and silently hidden.
            existing = old_default
    root = explicit_root or saved_root or existing or default_root or recordings_root()
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
    if selected or (existing and not explicit_root and not saved_root):
        store.setValue('library_directory', str(root))
    if not explicit_root and not saved_root and legacy_root is not None:
        try:
            library.import_legacy(legacy_root)
        except (OSError, ValueError, KeyError) as exc:
            migration_failed(legacy_root, exc)
    return library
