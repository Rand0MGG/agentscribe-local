"""Generate platform/channel appcasts from verified, already-published assets.

Reads the existing full Pages snapshot first. Validates immutable release
metadata, payload manifests, SHA256 and native Ed25519 signatures. No keys are
created here and no Release asset is replaced. Installation tests are an
explicit release acceptance input; a published flag alone is insufficient.
"""

import argparse
import base64
import hashlib
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linguaflow.update_config import bundle_version, update_identity
from linguaflow.updates import version_key

ROOT = Path(__file__).resolve().parents[1]

SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ET.register_namespace("sparkle", SPARKLE)
REPOSITORY = "https://github.com/Rand0MGG/agentscribe-local"


def feed_entry(release, manifest, artifact, signature, configuration, *, allow_unverified=False):
    """Return a sealed item, failing closed for drafts/dirty/unaccepted builds."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    version, target = manifest["version"], manifest["target"]
    identity = update_identity(configuration, target, version)
    if manifest.get("updater") != identity or manifest.get("source_modified") is not False:
        raise ValueError("安装包更新身份无效，或产物来自未提交源码。")
    if (
        release.get("draft") is not False
        or not release.get("published_at")
        or release.get("tag_name") != "v" + version
        or release.get("source_commit") != manifest.get("source_commit")
        or release.get("html_url") != REPOSITORY + "/releases/tag/v" + version
        or release.get("prerelease") != (identity["channel"] == "beta")
    ):
        raise ValueError("只允许发布固定标签和来源提交一致的已发布 Release。")
    if release.get("accepted_targets", {}).get(target) is not True and not allow_unverified:
        raise ValueError("此平台尚未通过安装与旧包升级验收。")
    suffix, field = ("dmg", "dmg") if target == "macos-arm64" else ("exe", "installer")
    name = f"AgentScribe-{version}-{target}.{suffix}"
    if artifact.name != name:
        raise ValueError("安装包名称与版本或目标平台不一致。")
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if manifest.get(field + "_sha256") != digest or manifest.get(field + "_bytes") != artifact.stat().st_size:
        raise ValueError("安装包与构建清单不一致。")
    url = REPOSITORY + "/releases/download/v" + version + "/" + quote(name)
    candidates = [asset for asset in release.get("assets", []) if asset.get("name") == name]
    if len(candidates) != 1 or candidates[0].get("browser_download_url") != url:
        raise ValueError("安装包尚未发布到对应 Release。")
    asset = candidates[0]
    if asset.get("size") != artifact.stat().st_size or asset.get("digest") != "sha256:" + digest:
        raise ValueError("GitHub 资产大小或摘要与验收安装包不一致。")
    try:
        signed = base64.b64decode(signature.strip(), validate=True)
        public = base64.b64decode(identity["public_key"], validate=True)
        # The official Sparkle and WinSparkle EdDSA tools sign the exact bytes.
        Ed25519PublicKey.from_public_bytes(public).verify(signed, artifact.read_bytes())
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("更新签名验证失败，保留原订阅。") from exc
    return dict(
        version=version,
        target=target,
        channel=identity["channel"],
        url=url,
        bytes=artifact.stat().st_size,
        sha256=digest,
        signature=signature.strip(),
        published=release["published_at"],
        notes=release.get("body", ""),
        minimum=manifest.get("minimum_macos", "15.0") if target == "macos-arm64" else "10.0",
    )


def render(entry):
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "AgentScribe " + entry["target"]
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = "AgentScribe " + entry["version"]
    ET.SubElement(item, "description").text = entry["notes"]  # XML escaped, never executed.
    ET.SubElement(item, f"{{{SPARKLE}}}minimumSystemVersion").text = entry["minimum"]
    attrs = {
        "url": entry["url"],
        "length": str(entry["bytes"]),
        "type": "application/octet-stream",
        f"{{{SPARKLE}}}version": bundle_version(entry["version"]),
        f"{{{SPARKLE}}}shortVersionString": entry["version"],
        f"{{{SPARKLE}}}edSignature": entry["signature"],
    }
    if entry["target"] == "windows-x64":
        attrs[f"{{{SPARKLE}}}os"] = "windows"
        attrs[f"{{{SPARKLE}}}installerArguments"] = (
            "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /AGENTSCRIBEUPDATE=1"
        )
    else:
        attrs[f"{{{SPARKLE}}}os"] = "macos"
    ET.SubElement(item, "enclosure", attrs)
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def merge_snapshot(previous, output, entry):
    """Preserve every other feed and reject older/conflicting publications."""
    index_path = previous / "updates/index.json"
    if not index_path.is_file():
        raise ValueError("缺少完整原订阅快照；不能用空目录覆盖线上入口。首次发布须显式使用 --initialize。")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    key = entry["target"] + "/" + entry["channel"]
    old = index.get(key)
    if old:
        if version_key(entry["version"]) < version_key(old["version"]):
            raise ValueError("拒绝将更新订阅回退到旧版本。")
        if version_key(entry["version"]) == version_key(old["version"]) and old != entry:
            raise ValueError("同一版本不可替换为另一产物或改写发布身份。")
    shutil.copytree(previous, output, dirs_exist_ok=True)
    index[key] = entry
    destination = output / "updates" / entry["target"] / (entry["channel"] + ".xml")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(render(entry))
    # Existing beta clients keep their immutable beta.xml URL. Offer the stable
    # release there too, while retaining any newer beta in the same platform.
    candidates = [index[key] for channel in ('stable', 'beta')
                  if (key := entry['target'] + '/' + channel) in index]
    candidates.sort(key=lambda value: version_key(value['version']), reverse=True)
    beta = ET.fromstring(render(candidates[0]))
    for candidate in candidates[1:]:
        beta.find('channel').append(ET.fromstring(render(candidate)).find('channel/item'))
    (destination.parent / 'beta.xml').write_bytes(ET.tostring(beta, encoding='utf-8', xml_declaration=True))
    (output / "updates/index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--initialize", action="store_true", help="仅用于经确认的首次空站点")
    args = parser.parse_args()
    if args.previous.resolve() == args.output.resolve():
        parser.error("输出与原快照必须分别存放。")
    if args.initialize:
        if args.previous.exists() and any(args.previous.iterdir()):
            parser.error("首次初始化要求原目录为空。")
        (args.previous / "updates").mkdir(parents=True, exist_ok=True)
        (args.previous / "updates/index.json").write_text("{}\n", encoding="utf-8")
    config = json.loads((ROOT / "packaging/updates.json").read_text(encoding="utf-8"))
    entry = feed_entry(
        json.loads(args.release.read_text(encoding="utf-8")),
        json.loads(args.manifest.read_text(encoding="utf-8")),
        args.artifact,
        args.signature.read_text(encoding="utf-8"),
        config,
    )
    merge_snapshot(args.previous, args.output, entry)


if __name__ == "__main__":
    main()
