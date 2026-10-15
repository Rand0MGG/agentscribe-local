"""Seal an audited Windows payload into an Inno Setup/WinSparkle installer.

The desktop payload must already contain a portable Python and its locked
native dependencies. This assembler does not copy a developer venv or fetch
unpinned wheels. Run on Windows x64 with Inno Setup 7 on PATH.
"""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linguaflow import __version__
from linguaflow.update_config import update_identity
from scripts.packaging_common import obtain
from scripts.probe_package import run_probe
from scripts.probe_packaged_launcher import probe

ROOT = Path(__file__).resolve().parents[1]


def prepare_compiler(downloads):
    """Prepare the pinned long-path-aware compiler in portable project-local mode."""
    item = json.loads((ROOT / 'packaging/windows/inno.json').read_text(encoding='utf-8'))
    installer = obtain(item, downloads, download=True)
    destination = ROOT / '.work/packaging' / ('inno-' + item['version'])
    subprocess.run([str(installer.resolve()), '/PORTABLE=1', '/CURRENTUSER', '/VERYSILENT',
                    '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(destination)],
                   check=True, timeout=180)
    compiler = destination / 'ISCC.exe'
    if not compiler.is_file():
        raise RuntimeError('Inno Setup portable compiler was not prepared: ' + str(compiler))
    return compiler


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_payload(payload):
    """Reject mismatched/unsealed payloads before creating any installer."""
    payload = payload.resolve()
    manifest = json.loads((payload / "build-manifest.json").read_text(encoding="utf-8"))
    commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    if (
        manifest.get("target") != "windows-x64"
        or manifest.get("version") != __version__
        or manifest.get("source_commit") != commit
        or manifest.get("source_modified") is not False
    ):
        raise ValueError("Windows 桌面产物必须与当前固定提交、版本和平台完全对应。")
    files = manifest.get("payload_files", {})
    required = {
        "AgentScribe.exe",
        "AgentScribeRecovery.dll",
        "python/python.exe",
        "requirements-runtime.txt",
        "desktop.lock",
        "THIRD_PARTY_NOTICES.md",
        "linguaflow/__init__.py",
    }
    if not required <= files.keys() or not any(path.startswith("Licenses/") for path in files):
        raise ValueError("缺少完整桌面运行组件、锁文件或许可清单。")
    actual = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
    if actual != set(files) | {"build-manifest.json"}:
        raise ValueError("Windows 产物包含未列入构建清单的文件。")
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("产物清单包含无效路径。")
        if digest(payload / relative) != expected:
            raise ValueError("Windows 产物文件校验失败：" + name)
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in payload.rglob("*")):
        raise ValueError("桌面产物不能包含外部目录映射。")
    dirty = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT),
            "status",
            "--porcelain",
            "--",
            "linguaflow",
            "packaging",
            "scripts",
            "pyproject.toml",
        ],
        text=True,
    )
    if dirty.strip():
        raise ValueError("必须从已提交的固定源码构建发行安装器。")
    return manifest


def build(payload, compiler, downloads, *, fetch=False):
    manifest = validate_payload(payload)
    configuration = json.loads((ROOT / "packaging/updates.json").read_text(encoding="utf-8"))
    identity = update_identity(configuration, "windows-x64", __version__)
    item = configuration["targets"]["windows-x64"]
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / item["filename"]
    if fetch and not archive.is_file():
        part = archive.with_suffix(".zip.part")
        with urllib.request.urlopen(item["url"], timeout=90) as response, part.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(part) != item["sha256"]:
            raise ValueError("WinSparkle 官方组件校验失败。")
        part.replace(archive)
    if not archive.is_file() or digest(archive) != item["sha256"]:
        raise ValueError("缺少已校验的 WinSparkle，请使用 --fetch。")
    work = ROOT / ".work/packaging"
    dist = work / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="windows-installer-", dir=work) as directory:
        stage = Path(directory)
        sealed = stage / "payload"
        shutil.copytree(payload, sealed)
        with zipfile.ZipFile(archive) as source:
            for name, destination in [
                ("WinSparkle-0.9.4/x64/Release/WinSparkle.dll", sealed / "WinSparkle.dll"),
                ("WinSparkle-0.9.4/COPYING", sealed / "Licenses/WinSparkle.txt"),
            ]:
                # Exact member names keep archive paths out of the filesystem.
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read(name))
        (sealed / "update-config.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
        manifest["updater"] = identity
        manifest["payload_files"] = {
            p.relative_to(sealed).as_posix(): digest(p)
            for p in sealed.rglob("*")
            if p.is_file() and p.name != "build-manifest.json"
        }
        (sealed / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Probe the actual final payload, including the updater and its identity.
        probe(sealed)
        run_probe(sealed)
        subprocess.run(
            [
                str(compiler),
                "/DPayload=" + str(sealed),
                "/DVersion=" + __version__,
                "/DOutput=" + str(stage),
                str(ROOT / "packaging/windows/installer.iss"),
            ],
            check=True,
        )
        name = f"AgentScribe-{__version__}-windows-x64.exe"
        installer = stage / name
        # Authenticode signing belongs to the protected release environment.
        # No private signing material is obtained by this build script.
        installer.replace(dist / name)
    installer = dist / name
    manifest.update(
        installer_sha256=digest(installer),
        installer_bytes=installer.stat().st_size,
        signature="unsigned",
        models_included=False,
    )
    installer.with_suffix(".build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    installer.with_suffix(".exe.sha256").write_text(f"{digest(installer)}  {name}\n", encoding="utf-8")
    print(installer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--iscc", type=Path, default=Path("ISCC.exe"))
    parser.add_argument("--downloads", type=Path, default=ROOT / ".work/packaging/downloads")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("必须在 Windows x64 构建此安装器。")
    build(args.payload, args.iscc, args.downloads, fetch=args.fetch)


if __name__ == "__main__":
    main()
