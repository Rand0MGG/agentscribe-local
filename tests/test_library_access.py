import pytest

from linguaflow.library import Library
from linguaflow.library_access import acquire_recording_lock, check_library_access


def test_active_recording_protects_its_parent_folder_and_releases_cleanly(tmp_path):
    library = Library(tmp_path)
    folder = library.index['folders'][0]
    recording = library.create(folder['id'], {}, name='active')
    lock = acquire_recording_lock(library.directory(recording['id']))
    try:
        with pytest.raises(ValueError, match='另一个窗口'):
            check_library_access(library, folder)
        with pytest.raises(ValueError, match='另一个窗口'):
            acquire_recording_lock(library.directory(recording['id']))
    finally:
        lock.unlock()
    check_library_access(library, folder)
    assert not list(library.recording_locks(folder))
