"""Relocation must preserve all data until copy, preference and cleanup succeed."""

import pytest

from linguaflow.core import Caption
from linguaflow.library import Library
from linguaflow.library_migration import MigrationCancelled, finish_migration, migrate_library


def populated(root):
    library = Library(root)
    item = library.create('inbox', {}, '课堂')
    library.save(item, [Caption(1, 0, 4, 'original', 'en', '译文')], 'complete')
    folder = library.directory(item['id'])
    (folder / '录音.wav').write_bytes(b'fixture PCM bytes' * 1000)
    (folder / '资料').mkdir()
    (folder / '资料/课程.pdf').write_bytes(b'course fixture')
    deleted = library.create('inbox', {}, '最近删除的录音')
    token = library.trash(deleted)
    return library, item, token


def test_copy_verification_commit_cleanup_and_trash_materials(tmp_path):
    source, item, token = populated(tmp_path / 'old')
    original = source.directory(item['id']) / '录音.wav'
    progress = []
    copied, verified = migrate_library(source, tmp_path / '新 保存位置', progress=progress.append)
    assert original.is_file()  # No preference commit yet.
    assert copied.load(item)[1][0].translation == '译文'
    assert (copied.directory(item['id']) / '资料/课程.pdf').read_bytes() == b'course fixture'
    assert copied.deleted()[0]['token'] == token
    assert progress[-1] == 100
    assert not finish_migration(source.root, copied.root, verified)
    assert not original.exists()
    assert (copied.directory(item['id']) / '录音.wav').is_file()
    copied.restore_deleted(token)


def test_retry_completed_copy_before_preference_commit(tmp_path):
    source, item, _ = populated(tmp_path / 'old')
    copied, _ = migrate_library(source, tmp_path / 'new')
    retried, verified = migrate_library(source, copied.root)
    assert retried.load(item)[1][0].source == 'original'
    assert verified


def test_cancel_halfway_leaves_originals_and_empty_destination(tmp_path):
    source, item, _ = populated(tmp_path / 'old')
    cancelled = [False]
    def progress(_):
        cancelled[0] = True
    with pytest.raises(MigrationCancelled):
        migrate_library(source, tmp_path / 'new', cancelled=lambda: cancelled[0], progress=progress)
    assert source.load(item)[1][0].source == 'original'
    assert not list((tmp_path / 'new').iterdir())


def test_collision_never_overwrites_and_nested_location_rejected(tmp_path):
    source, _, _ = populated(tmp_path / 'old')
    destination = tmp_path / 'new'
    destination.mkdir()
    existing = destination / '我的录音'
    existing.write_text('keep me')
    with pytest.raises(ValueError, match='已有文件'):
        migrate_library(source, destination)
    assert existing.read_text() == 'keep me'
    with pytest.raises(ValueError, match='子目录'):
        migrate_library(source, source.root / 'nested')


@pytest.mark.parametrize('changed_side', ['source', 'destination'])
def test_cleanup_retains_original_when_either_verified_copy_changes(tmp_path, changed_side):
    source, item, _ = populated(tmp_path / 'old')
    copied, verified = migrate_library(source, tmp_path / 'new')
    original = source.directory(item['id']) / '录音.wav'
    path = original if changed_side == 'source' else copied.directory(item['id']) / '录音.wav'
    path.write_bytes(b'changed after verification')
    retained = finish_migration(source.root, copied.root, verified)
    assert str(original.relative_to(source.root)) in retained
    assert original.exists()


def test_external_links_rejected_and_implicit_folder_identity_preserved(tmp_path):
    source, _, _ = populated(tmp_path / 'old')
    extra = source.root / '手动建的文件夹'
    extra.mkdir()
    source.refresh()
    identifier = next(folder['id'] for folder in source.index['folders'] if folder['name'] == extra.name)
    copied, _ = migrate_library(source, tmp_path / 'new')
    assert copied.directory(identifier).name == extra.name
    outside = tmp_path / 'outside'
    outside.write_text('external')
    link = source.root / 'link'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('symlinks unavailable on this Windows account')
    with pytest.raises(ValueError, match='快捷映射'):
        migrate_library(source, tmp_path / 'new2')
    assert outside.read_text() == 'external'


def test_destination_changes_during_copy_never_overwritten(tmp_path):
    source, _, _ = populated(tmp_path / 'old')
    target = tmp_path / 'new'
    def progress(_):
        (target / 'concurrent.txt').write_text('external writer')
    with pytest.raises(FileExistsError):
        migrate_library(source, target, progress=progress)
    assert (target / 'concurrent.txt').read_text() == 'external writer'
    assert len(list(target.iterdir())) == 1


def test_volume_without_hardlinks_uses_exclusive_verified_copy(tmp_path, monkeypatch):
    import errno
    import os
    source, item, _ = populated(tmp_path/'old')
    def unsupported(*args):
        raise OSError(errno.ENOTSUP, 'fixture exFAT volume')
    monkeypatch.setattr(os, 'link', unsupported)
    copied, verified = migrate_library(source, tmp_path/'external')
    assert copied.load(item)[1][0].source == 'original'
    assert not finish_migration(source.root, copied.root, verified)
    assert (copied.directory(item['id'])/'录音.wav').is_file()
