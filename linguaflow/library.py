"""Ordinary directories are the source of truth; JSON only accompanies recordings."""

import json
import re
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from .core import Caption, export_srt


class Library:
    folder_file = ".folder.json"
    trash_name = ".最近删除"

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        probe = self.root / (".write-check-" + uuid4().hex)
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        self.index, self.paths, self.warnings = {}, {}, []
        self.refresh()
        if (self.root / "library.json").is_file():
            self.import_legacy(self.root)
        if not self.index["folders"]:
            identifier = None if any(d["id"] == "inbox" for d in self.deleted()) else "inbox"
            self.folder("我的录音", identifier=identifier)

    @staticmethod
    def _read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    @staticmethod
    def _write(path, value):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def validate_name(name):
        name = name.strip()
        if not name or name in {".", ".."}:
            raise ValueError("请输入名称。")
        if len(name) > 64:
            raise ValueError("名称最多 64 个字符。")
        if name.startswith(".") or name.endswith(".") or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
            raise ValueError('名称不能包含 < > : " / \\ | ? *，也不能以点开头或结尾。')
        if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", name.split(".")[0], re.I):
            raise ValueError("这个名称被系统保留，请换一个名称。")
        return name

    def _safe(self, path):
        path = Path(path)
        resolved = path.resolve()
        if resolved == self.root or self.root not in resolved.parents:
            raise ValueError("操作必须位于录音目录内。")
        cursor = path
        while cursor != self.root:
            if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
                raise ValueError("不通过快捷映射操作录音文件。")
            cursor = cursor.parent
        return resolved

    def refresh(self):
        folders, sessions, paths, warnings = [], [], {}, []

        def scan(directory, parent=None):
            try:
                children = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
            except OSError as exc:
                warnings.append(f"无法读取 {directory.name}：{exc}")
                return
            for child in children:
                if child.name.startswith(".") or not child.is_dir():
                    continue
                try:
                    self._safe(child)
                    metadata = child / "session.json"
                    if metadata.is_file():
                        self._safe(metadata)
                        data = self._read(metadata)
                        if "session" not in data:
                            continue  # v1 files are migrated separately.
                        item = dict(data["session"])
                        identifier = item["id"]
                        if parent is None:
                            warnings.append(f"请把 {child.name} 放入一个文件夹。")
                            continue
                        item.update(name=child.name, folder=parent)
                        target = sessions
                    else:
                        marker = child / self.folder_file
                        self._safe(marker)
                        identifier = self._read(marker)["id"] if marker.exists() else uuid5(NAMESPACE_URL, str(child)).hex
                        item = {"id": identifier, "name": child.name, "parent": parent}
                        target = folders
                    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}|inbox", identifier):
                        raise ValueError("无效的文件标识")
                    if identifier in paths:
                        warnings.append(f"{child.name} 的标识重复，未载入副本；原文件不受影响。")
                        continue
                    paths[identifier] = child
                    target.append(item)
                    if target is folders:
                        scan(child, identifier)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    warnings.append(f"未载入 {child.name}：{exc}")

        scan(self.root)
        self.index = {"folders": folders, "sessions": sorted(sessions, key=lambda x: x.get("created", ""), reverse=True)}
        self.paths, self.warnings = paths, warnings

    def directory(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}|inbox", identifier):
            raise ValueError("无效的录音标识")
        path = self.paths.get(identifier)
        if path is None or not path.is_dir():
            self.refresh()
            path = self.paths.get(identifier)
        if path is None:
            raise FileNotFoundError("文件已被移动或删除，请刷新文件列表。")
        return self._safe(path)

    def folder_label(self, identifier):
        return str(self.directory(identifier).relative_to(self.root))

    def _destination(self, parent, name, unique=False, source=None):
        name = self.validate_name(name)
        candidate = parent / name
        entries = {p.name.casefold(): p for p in parent.iterdir()}
        number = 2
        while candidate.name.casefold() in entries and entries[candidate.name.casefold()] != source:
            if not unique:
                raise FileExistsError("此处已有同名文件或文件夹，请使用其他名称。")
            candidate = parent / f"{name} ({number})"
            number += 1
        self._safe(candidate)
        return candidate

    def folder(self, name, parent=None, identifier=None):
        base = self.directory(parent) if parent else self.root
        path = self._destination(base, name, unique=True)
        path.mkdir()
        identifier = identifier or uuid4().hex
        self._write(path / self.folder_file, {"id": identifier})
        self.refresh()
        return next(f for f in self.index["folders"] if f["id"] == identifier)

    def create(self, folder_id, settings, name=None):
        base = self.directory(folder_id)
        name = datetime.now().strftime("录音 %m月%d日 %H时%M分") if name is None else name
        directory = self._destination(base, name, unique=True)
        directory.mkdir()
        item = {"id": uuid4().hex, "folder": folder_id, "name": directory.name,
                "created": datetime.now().isoformat(), "state": "draft"}
        self._write(directory / "session.json", {"version": 2, "session": item, "settings": settings, "captions": []})
        self.refresh()
        return next(i for i in self.index["sessions"] if i["id"] == item["id"])

    def begin(self, item, settings):
        path = self.directory(item["id"])
        data = self._read(path / "session.json")
        if data["session"]["state"] != "draft" or (path / "录音.wav").exists():
            raise ValueError("已有录音不能被覆盖，请新建录音。")
        data["settings"] = settings
        data["session"]["state"] = "recording"
        self._write(path / "session.json", data)
        item["state"] = "recording"

    def save(self, item, captions, state=None):
        directory = self.directory(item["id"])
        data = self._read(directory / "session.json")
        data["captions"] = [asdict(c) for c in sorted(captions, key=lambda c: (c.start, c.id))]
        data["session"].update(state=state or data["session"]["state"], name=directory.name)
        self._write(directory / "session.json", data)
        final = [Caption(**c) for c in data["captions"] if c["final"] and c["source"]]
        for filename, text in [("定稿.srt", export_srt(final)),
                               ("定稿.txt", "\n\n".join("\n".join(filter(None, [c.source, c.translation]))
                                                      for c in final))]:
            path = directory / filename
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(text, encoding="utf-8-sig")
            temporary.replace(path)
        item["state"] = data["session"]["state"]

    def load(self, item):
        data = self._read(self.directory(item["id"]) / "session.json")
        return data, [Caption(**c) for c in data["captions"]]

    def rename(self, item, name):
        source = self.directory(item["id"])
        destination = self._destination(source.parent, name, source=source)
        if source != destination:
            source.rename(destination)
        item["name"] = destination.name
        self.refresh()

    def move(self, item, folder_id):
        source = self.directory(item["id"])
        base = self.directory(folder_id)
        if source == base or source in base.parents:
            raise ValueError("不能把文件夹移动到自身或它的子文件夹。")
        if source.parent != base:
            destination = self._destination(base, source.name, unique=True)
            source.rename(destination)
            item["name"] = destination.name
        item["folder" if "folder" in item else "parent"] = folder_id
        self.refresh()

    def trash(self, item):
        source = self.directory(item["id"])
        trash = self._safe(self.root / self.trash_name)
        trash.mkdir(exist_ok=True)
        token = uuid4().hex
        box = self._safe(trash / token)
        box.mkdir()
        self._write(box / "restore.json", {"original": str(source.relative_to(self.root)),
                    "name": source.name, "deleted": datetime.now().isoformat(), "id": item["id"]})
        source.rename(self._safe(box / source.name))
        self.refresh()
        return token

    def deleted(self):
        result = []
        trash = self.root / self.trash_name
        if not trash.exists():
            return result
        self._safe(trash)
        for box in trash.iterdir():
            try:
                self._safe(box)
                data = self._read(box / "restore.json")
                data["token"] = box.name
                if self._safe(box / data["name"]).is_dir():
                    result.append(data)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(result, key=lambda x: x["deleted"], reverse=True)

    def restore_deleted(self, token):
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("无效的恢复标识")
        box = self._safe(self.root / self.trash_name / token)
        data = self._read(box / "restore.json")
        self.validate_name(data["name"])
        source = self._safe(box / data["name"])
        original = self._safe(self.root / data["original"])
        if self.root / self.trash_name in original.parents:
            raise ValueError("无效的恢复位置")
        original.parent.mkdir(parents=True, exist_ok=True)
        destination = self._destination(original.parent, original.name, unique=True)
        source.rename(destination)
        self.refresh()
        return destination

    def purge_deleted(self, token):
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("无效的删除标识")
        trash = self._safe(self.root / self.trash_name)
        box = self._safe(trash / token)
        if box.parent != trash:
            raise ValueError("只能清理最近删除内的条目")
        # The absolute target is checked before recursive removal.
        shutil.rmtree(box)

    def import_legacy(self, source):
        """Copy v1 once and retain originals, including after a partial migration."""
        source = Path(source).resolve()
        marker = self.root / ".legacy-imported.json"
        done = self._read(marker) if marker.exists() else []
        if str(source) in done or not (source / "library.json").exists():
            return 0
        old = self._read(source / "library.json")
        mapping, copied = {}, 0
        for folder in old["folders"]:
            existing = next((f for f in self.index["folders"] if f["id"] == folder["id"]), None)
            mapping[folder["id"]] = existing or self.folder(folder["name"], identifier=folder["id"])
        for item in old["sessions"]:
            if item["id"] in self.paths:
                continue
            if not re.fullmatch(r"[0-9a-f]{32}", item["id"]):
                raise ValueError("旧录音标识无效")
            origin = source / item["id"]
            if origin.resolve().parent != source or origin.is_symlink():
                raise ValueError("旧录音目录包含外部映射")
            if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in origin.rglob("*")):
                raise ValueError("旧录音目录包含外部映射")
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', item["name"]).strip('. ')[:64] or "导入录音"
            destination = self._destination(self.directory(mapping[item["folder"]]["id"]), name, unique=True)
            temporary = self._safe(destination.parent / (".import-" + item["id"]))
            shutil.copytree(origin, temporary, dirs_exist_ok=True)
            data = self._read(temporary / "session.json")
            data.update(version=2, session={**item, "name": destination.name})
            self._write(temporary / "session.json", data)
            temporary.rename(destination)
            self.refresh()
            copied += 1
        self._write(marker, done + [str(source)])
        return copied
