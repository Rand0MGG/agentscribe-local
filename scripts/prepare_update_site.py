"""Fetch published installer/signature and preserve the whole previous Pages site."""

import argparse
import io
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linguaflow.update_config import update_identity
from linguaflow.updates import version_key
from scripts.publish_update_feed import feed_entry, merge_snapshot

ROOT = Path(__file__).resolve().parents[1]

REPO = "Rand0MGG/agentscribe-local"


def unpack_snapshot(data, root):
    """The previous site is data, never code; reject mappings and unsafe paths."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 32 * 1024**2:
            raise ValueError("旧订阅快照超出容量。")
        for item in archive.infolist():
            relative = Path(item.filename)
            if relative.is_absolute() or ".." in relative.parts or "\\" in item.filename:
                raise ValueError("旧订阅快照含无效路径。")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("旧订阅快照含外部目录映射。")
            destination = root / relative
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target)


def prepare(tag, target, work, *, initialize=False):
    version = tag.removeprefix("v")
    version_key(version)
    if tag != "v" + version or target not in ("windows-x64", "macos-arm64"):
        raise ValueError("发行标签或平台无效。")
    work.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / "packaging/updates.json").read_text(encoding="utf-8"))
    update_identity(config, target, version)  # Refuse missing trust before network.
    release = json.loads(
        subprocess.check_output(["gh", "api", f"repos/{REPO}/releases/tags/{tag}"], text=True)
    )
    if release.get("draft") or not release.get("published_at"):
        raise ValueError("必须先发布已验收的 Release，再发布对应订阅。")
    release["source_commit"] = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", tag + "^{commit}"], text=True
    ).strip()
    # Workflow dispatch has an explicit platform acceptance input. No build or
    # API result is interpreted as human installation acceptance.
    release["accepted_targets"] = {target: True}
    suffix = "dmg" if target == "macos-arm64" else "exe"
    stem = f"AgentScribe-{version}-{target}"
    names = [stem + "." + suffix, stem + ".build.json", stem + "." + suffix + ".ed25519"]
    for name in names:
        subprocess.run(
            ["gh", "release", "download", tag, "--repo", REPO, "--pattern", name, "--dir", str(work)],
            check=True,
        )
    previous, output = work / "previous", work / "site"
    previous.mkdir()
    url = config["feed_base"].rsplit("/", 1)[0] + "/snapshot.zip"
    try:
        request = urllib.request.Request(url + '?fresh=' + str(time.time_ns()), headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=30) as response:
            snapshot = response.read(32 * 1024**2 + 1)
        if len(snapshot) > 32 * 1024**2:
            raise ValueError("旧订阅快照超出容量。")
        if initialize:
            raise ValueError("线上已有站点，不能使用首次初始化。")
        unpack_snapshot(snapshot, previous)
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or not initialize:
            raise
        # An existing site without a snapshot is never silently replaced.
        site_url = config["feed_base"].rsplit("/", 1)[0] + "/"
        try:
            urllib.request.urlopen(site_url, timeout=30).close()
        except urllib.error.HTTPError as site_error:
            if site_error.code != 404:
                raise
        else:
            raise ValueError("站点已存在但缺少快照，需先导入整站，不能覆盖。")
        (previous / "updates").mkdir()
        (previous / "updates/index.json").write_text("{}\n", encoding="utf-8")
    entry = feed_entry(
        release,
        json.loads((work / (stem + ".build.json")).read_text(encoding="utf-8")),
        work / (stem + "." + suffix),
        (work / (stem + "." + suffix + ".ed25519")).read_text(encoding="utf-8"),
        config,
    )
    merge_snapshot(previous, output, entry)
    # The self-contained archive excludes itself; next dispatch restores all
    # existing feeds and site files. Global workflow concurrency serializes it.
    (output / "snapshot.zip").unlink(missing_ok=True)
    with zipfile.ZipFile(output / "snapshot.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path.name != "snapshot.zip":
                archive.write(path, path.relative_to(output).as_posix())
    (work / "release.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target", required=True, choices=["macos-arm64", "windows-x64"])
    parser.add_argument("--work", type=Path, default=ROOT / ".work/update-site")
    parser.add_argument("--accepted", action="store_true", help="此平台安装与旧包升级已验收")
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    if not args.accepted:
        parser.error("未确认平台安装/升级验收，不发布订阅。")
    prepare(args.tag, args.target, args.work, initialize=args.initialize)


if __name__ == "__main__":
    main()
