from dataclasses import asdict, replace

import pytest

from linguaflow.core import Caption, Settings
from linguaflow.library import Library


def test_reopen_keeps_revisions_and_exports_only_final(tmp_path):
    library = Library(tmp_path)
    folder = library.folder("课程")
    item = library.create(folder["id"], asdict(Settings("fixture")))
    draft = Caption(1, 0, 2, "draft", "en", final=False)
    final = Caption(2, 2, 4, "hello", "en", "你好")
    library.save(item, [draft, final], "incomplete")
    reopened = Library(tmp_path)
    data, captions = reopened.load(reopened.index["sessions"][0])
    assert captions == [draft, final]
    assert data["settings"]["device_id"] == "fixture"
    output = (library.directory(item["id"]) / "定稿.srt").read_text(encoding="utf-8-sig")
    assert "draft" not in output and "你好" in output
    library.save(item, [replace(final, source="corrected", revision=2)], "complete")
    _, updated = Library(tmp_path).load(item)
    assert len(updated) == 1 and updated[0].source == "corrected"


def test_failed_atomic_save_keeps_original(tmp_path, monkeypatch):
    library = Library(tmp_path)
    item = library.create("inbox", {})
    caption = Caption(1, 0, 1, "saved", "en")
    library.save(item, [caption])
    original = type(tmp_path).replace

    def fail(path, target):
        if path.name == "session.json.tmp":
            raise OSError("disk unavailable")
        return original(path, target)

    monkeypatch.setattr(type(tmp_path), "replace", fail)
    with pytest.raises(OSError):
        library.save(item, [replace(caption, source="new")])
    assert library.load(item)[1][0].source == "saved"


def test_session_path_cannot_escape_library(tmp_path):
    with pytest.raises(ValueError):
        Library(tmp_path).directory("../other")


def test_readable_folders_external_rename_and_move(tmp_path):
    library = Library(tmp_path)
    folder = library.folder("课堂")
    child = library.folder("第一周", parent=folder["id"])
    item = library.create(child["id"], {}, name="线性代数")
    library.save(item, [Caption(1, 0, 1, "hello", "en", "你好")], "complete")
    original = tmp_path / "课堂" / "第一周" / "线性代数"
    assert library.directory(item["id"]) == original
    assert (original / "定稿.txt").exists()
    original.rename(original.with_name("矩阵入门"))
    library.refresh()
    assert library.index["sessions"][0]["name"] == "矩阵入门"
    library.move(library.index["sessions"][0], "inbox")
    assert library.directory(item["id"]) == tmp_path / "我的录音" / "矩阵入门"
    assert library.load(item)[1][0].translation == "你好"
    assert not (tmp_path / "library.json").exists()


@pytest.mark.parametrize("name", ["", "..", ".hidden", "CON", "con.txt", "a/b", "a\\b", "a:", "test."])
def test_invalid_names_are_rejected_without_creating_files(tmp_path, name):
    library = Library(tmp_path)
    before = list((tmp_path / "我的录音").iterdir())
    with pytest.raises(ValueError):
        library.create("inbox", {}, name=name)
    assert list((tmp_path / "我的录音").iterdir()) == before


def test_duplicates_and_restore_do_not_overwrite(tmp_path):
    library = Library(tmp_path)
    first = library.create("inbox", {}, name="录音")
    second = library.create("inbox", {}, name="录音")
    assert second["name"] == "录音 (2)"
    with pytest.raises(FileExistsError):
        library.rename(second, "录音")
    library.save(first, [Caption(1, 0, 1, "original", "en")])
    token = library.trash(first)
    replacement = library.create("inbox", {}, name="录音")
    restored = library.restore_deleted(token)
    assert restored.name == "录音 (3)"
    assert library.load(first)[1][0].source == "original"
    assert library.load(replacement)[1] == []
    assert library.deleted() == []


def test_folder_delete_restore_and_self_move(tmp_path):
    library = Library(tmp_path)
    folder = library.index["folders"][0]
    child = library.folder("子文件夹", parent=folder["id"])
    item = library.create(child["id"], {}, name="保留")
    with pytest.raises(ValueError):
        library.move(folder, child["id"])
    token = library.trash(folder)
    assert not library.index["sessions"]
    restarted = Library(tmp_path)
    restarted.restore_deleted(token)
    assert restarted.directory(item["id"]).is_dir()
    assert len(restarted.index["sessions"]) == 1


def test_legacy_migration_is_repeatable_and_keeps_originals(tmp_path):
    import json
    from uuid import uuid4

    source = tmp_path / "legacy"
    source.mkdir()
    identifier = uuid4().hex
    directory = source / identifier
    directory.mkdir()
    original = {"settings": {}, "captions": [asdict(Caption(1, 0, 1, "retained", "en"))]}
    (directory / "session.json").write_text(json.dumps(original), encoding="utf-8")
    (directory / "录音.wav").write_bytes(b"fixture")
    (source / "library.json").write_text(json.dumps({"folders": [{"id": "inbox", "name": "我的录音"}],
        "sessions": [{"id": identifier, "name": "旧录音: 01", "folder": "inbox",
                      "created": "2026-09-14", "state": "complete"}]}), encoding="utf-8")
    library = Library(tmp_path / "new")
    assert library.import_legacy(source) == 1
    assert library.import_legacy(source) == 0
    assert (directory / "session.json").exists()
    assert library.directory(identifier).name == "旧录音- 01"
    assert library.load(library.index["sessions"][0])[1][0].source == "retained"


def test_begin_never_overwrites_existing_recording(tmp_path):
    library = Library(tmp_path)
    item = library.create("inbox", {}, name="已有录音")
    (library.directory(item["id"]) / "录音.wav").write_bytes(b"important")
    with pytest.raises(ValueError):
        library.begin(item, {})
    assert (library.directory(item["id"]) / "录音.wav").read_bytes() == b"important"


def test_permanent_delete_is_confined_to_trash(tmp_path):
    library = Library(tmp_path)
    retained = library.create("inbox", {}, name="保留")
    removed = library.create("inbox", {}, name="删除")
    token = library.trash(removed)
    with pytest.raises(ValueError):
        library.purge_deleted("../我的录音")
    library.purge_deleted(token)
    assert library.directory(retained["id"]).is_dir()
    assert not library.deleted()
