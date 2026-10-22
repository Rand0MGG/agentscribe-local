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


@pytest.mark.p0
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


@pytest.mark.p0
def test_retry_completed_copy_before_preference_commit(tmp_path):
    source, item, _ = populated(tmp_path / 'old')
    copied, _ = migrate_library(source, tmp_path / 'new')
    retried, verified = migrate_library(source, copied.root)
    assert retried.load(item)[1][0].source == 'original'
    assert verified


@pytest.mark.p0
@pytest.mark.parametrize('change', ['missing', 'invalid', 'changed'])
def test_retry_checks_generated_folder_identity_before_committing(tmp_path, change):
    source = Library(tmp_path / 'old')
    folder = source.root / '手工文件夹'
    folder.mkdir()
    source.refresh()
    identifier = next(row['id'] for row in source.index['folders'] if row['name'] == folder.name)
    item = source.create(identifier, {}, '课堂')
    original = source.directory(item['id']) / '录音.wav'
    original.write_bytes(b'fixture PCM')
    copied, _ = migrate_library(source, tmp_path / 'new')
    marker = copied.directory(identifier) / Library.folder_file
    assert not (folder / Library.folder_file).exists()
    if change == 'missing':
        marker.unlink()
    else:
        marker.write_text('{"id":"invalid"}' if change == 'invalid' else '{"id":"' + 'a' * 32 + '"}',
                          encoding='utf-8')
    with pytest.raises(ValueError, match='索引不完整'):
        migrate_library(source, copied.root)
    assert original.read_bytes() == b'fixture PCM'
    assert (copied.root / folder.name / '课堂' / '录音.wav').read_bytes() == b'fixture PCM'
    assert (copied.root / '.agentscribe-migration.json').is_file()


@pytest.mark.p0
@pytest.mark.parametrize('addition', ['file', 'directory', 'recording'])
def test_retry_rejects_source_entries_added_after_copy(tmp_path, addition):
    source, item, _ = populated(tmp_path / 'old')
    copied, _ = migrate_library(source, tmp_path / 'new')
    if addition == 'recording':
        new = source.create('inbox', {}, '新增录音')
        path = source.directory(new['id'])
    else:
        path = source.root / '新增资料'
        path.write_text('new material') if addition == 'file' else path.mkdir()
    with pytest.raises(ValueError, match='原目录内容已变化'):
        migrate_library(source, copied.root)
    assert path.exists() and source.load(item)[1][0].source == 'original'
    assert copied.load(item)[1][0].source == 'original'


@pytest.mark.p0
def test_addition_during_copy_prevents_publication(tmp_path):
    source, item, _ = populated(tmp_path / 'old')
    target = tmp_path / 'new'
    def progress(_):
        (source.root / '新增资料.txt').write_text('keep new material')
    with pytest.raises(OSError, match='原目录内容在迁移时发生变化'):
        migrate_library(source, target, progress=progress)
    assert not list(target.iterdir())
    assert source.load(item)[1][0].source == 'original'
    assert (source.root / '新增资料.txt').is_file()


@pytest.mark.p0
def test_legacy_journal_cannot_prove_complete_directory_copy(tmp_path):
    import json
    source, _, _ = populated(tmp_path / 'old')
    copied, _ = migrate_library(source, tmp_path / 'new')
    journal = copied.root / '.agentscribe-migration.json'
    record = json.loads(journal.read_text())
    record.pop('directories')
    journal.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='迁移记录不完整'):
        migrate_library(source, copied.root)


@pytest.mark.p0
def test_cancel_halfway_leaves_originals_and_empty_destination(tmp_path):
    source, item, _ = populated(tmp_path / 'old')
    cancelled = [False]
    def progress(_):
        cancelled[0] = True
    with pytest.raises(MigrationCancelled):
        migrate_library(source, tmp_path / 'new', cancelled=lambda: cancelled[0], progress=progress)
    assert source.load(item)[1][0].source == 'original'
    assert not list((tmp_path / 'new').iterdir())


@pytest.mark.p0
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


@pytest.mark.p0
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


@pytest.mark.p0
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


@pytest.mark.p0
def test_destination_changes_during_copy_never_overwritten(tmp_path):
    source, _, _ = populated(tmp_path / 'old')
    target = tmp_path / 'new'
    def progress(_):
        (target / 'concurrent.txt').write_text('external writer')
    with pytest.raises(FileExistsError):
        migrate_library(source, target, progress=progress)
    assert (target / 'concurrent.txt').read_text() == 'external writer'
    assert len(list(target.iterdir())) == 1


@pytest.mark.p0
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
