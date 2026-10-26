"""Real WinSparkle/Inno old-client upgrade on a fresh disposable Windows runner.

Only the test adapter's feed transport changes for local fault cases. Production
application files, trust keys, shutdown gates and sealed installers stay intact.
Never run on a user's computer; normal relaunch may discover runner devices.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.probe_macos_update import digest, preserved_files

ROOT = Path(__file__).resolve().parents[1]
SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
HARNESS = r"""
import json,sys
from pathlib import Path
from PySide6.QtCore import QSettings,QTimer
from PySide6.QtWidgets import QApplication
from linguaflow import native_updates
from linguaflow.app import Window
from linguaflow.recording_state import RecordingState
from linguaflow.update_recovery import startup
startup()
work=Path(WORK);case=CASE;feed=FEED
if feed:
    original=native_updates.WinSparkleAdapter
    class LocalFeed(original):
        def __init__(self,root,config,*args):
            super().__init__(root,{**config,'feed_url':feed},*args)
    native_updates.WinSparkleAdapter=LocalFeed
app=QApplication([])
Window.check_model_assets=lambda self:None
prefs=QSettings('LinguaFlow','LocalCaptions')
prefs.setValue('library_directory',str(work/'recordings'))
prefs.setValue('appearance','dark');prefs.setValue('update_probe_sentinel','preserve this preference')
w=Window(discover=False,prefs=prefs,library_root=work/'recordings');w.show()
u=w.native_updater;started=False;released=False
if case in ('happy','rollback'):
    w.set_recording_state(RecordingState.LISTENING);w.save_error='fixture pending save'
def event(e):
    global started,released
    with (work/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(e,ensure_ascii=False)+'\n')
    stage=e.get('stage')
    if stage=='native' and not started:
        started=True;QTimer.singleShot(0,u.adapter.install)
    elif stage=='waiting' and not released:
        assert case in ('happy','rollback'),e
        released=True
        assert u.pending and not u.installing and u.shutdown_job is None
        (work/'recording-gate').write_text('held')
        def finish():
            w.set_recording_state(RecordingState.IDLE);w.try_install_update()
            assert u.shutdown_job is None and not u.installing
            (work/'save-gate').write_text('held');w.save_error='';w.try_install_update()
        QTimer.singleShot(300,finish)
    elif stage=='error':
        assert case in ('tampered','interrupted','cancel'),e
        QTimer.singleShot(100,w.close)
u.event.connect(event)
def cancel():
    if case=='cancel' and (work/'download-started').exists():
        u.cancel();w.close();cancel_timer.stop()
cancel_timer=QTimer();cancel_timer.timeout.connect(cancel);cancel_timer.start(50)
QTimer.singleShot(200,w.check_software_updates)
QTimer.singleShot(300000,app.quit)
sys.exit(app.exec())
"""


def run_case(case, work, old_installer, candidate, manifest, signature, live):
    import psutil
    from PySide6.QtCore import QSettings

    from linguaflow.core import Caption
    from linguaflow.library import Library
    from linguaflow.runtime_paths import user_data_root
    from linguaflow.update_recovery import NativeRecovery, inventory

    work.mkdir()
    installed = work / "AgentScribe"
    subprocess.run(
        [str(old_installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/DIR={installed}"],
        check=True,
        timeout=300,
    )
    executable = installed / "AgentScribe.exe"
    old_manifest = json.loads((installed / "build-manifest.json").read_text(encoding="utf-8"))
    old_version = old_manifest["version"]
    trust = json.loads((installed / "update-config.json").read_text(encoding="utf-8"))
    assert trust["public_key"] == manifest["updater"]["public_key"]
    # Keep the controller's DLL outside the installed tree: Windows locks loaded DLLs.
    control = work / "control-recovery.dll"
    shutil.copy2(installed / "AgentScribeRecovery.dll", control)
    native = NativeRecovery(control)
    library = Library(work / "recordings")
    folder = library.ensure_default_folder()
    item = library.create(folder["id"], {}, name="升级保留的课堂录音")
    library.save(item, [Caption(1, 0.0, 1.0, "preserved transcript", "en", final=True)], state="complete")
    import wave

    with wave.open(str(library.directory(item["id"]) / "audio.wav"), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0" * 32000)
    library.trash(library.create(folder["id"], {}, name="最近删除也应保留"))
    external = work / "external"
    external.mkdir()
    (external / "用户资料.txt").write_text("Never delete unrelated user files", encoding="utf-8")
    data = user_data_root()
    model, runtime = data / "models" / case / "existing.bin", data / "runtime" / case / "existing.bin"
    for marker in (model, runtime):
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"preserved user-owned fixture")
    expected = preserved_files(work / "recordings"), preserved_files(external), digest(model), digest(runtime)
    server = None
    if not live:

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path.split("?", 1)[0].endswith(".xml"):
                    rss = ET.Element("rss", {"version": "2.0", "xmlns:sparkle": SPARKLE})
                    entry = ET.SubElement(ET.SubElement(rss, "channel"), "item")
                    ET.SubElement(
                        entry,
                        "enclosure",
                        {
                            "url": f"http://127.0.0.1:{server.server_port}/update.exe",
                            "length": str(candidate.stat().st_size),
                            "type": "application/octet-stream",
                            "sparkle:version": manifest["version"],
                            "sparkle:shortVersionString": manifest["version"],
                            "sparkle:edSignature": signature,
                            "sparkle:os": "windows",
                            "sparkle:installerArguments": "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /AGENTSCRIBEUPDATE=1",
                        },
                    )
                    body = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Content-Type", "application/rss+xml")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                (work / "download-started").touch()
                self.send_response(200)
                self.send_header("Content-Length", str(candidate.stat().st_size))
                self.end_headers()
                try:
                    with candidate.open("rb") as source:
                        first = True
                        while chunk := source.read(1024 * 1024):
                            if first and case == "tampered":
                                chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
                            first = False
                            self.wfile.write(chunk)
                            self.wfile.flush()
                            if case == "interrupted":
                                self.close_connection = True
                                return
                            if case == "cancel":
                                time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
    before = inventory(installed)
    feed = f"http://127.0.0.1:{server.server_port}/feed.xml" if server else None
    harness = HARNESS.replace("WORK", repr(str(work))).replace("CASE", repr(case)).replace("FEED", repr(feed))
    state, child, passed = None, None, False
    try:
        with (work / "old-app.log").open("wb") as log:
            child = subprocess.Popen(
                [str(executable), "--python", "-c", harness],
                cwd=work,
                stdout=log,
                stderr=log,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            deadline, killed = time.monotonic() + 300, False
            while time.monotonic() < deadline:
                for path in (data / "updates").glob("*/state.json"):
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if Path(value["installed"]) != installed:
                        continue
                    state = value
                    startup = path.parent / "startup.json"
                    if case == "rollback" and startup.exists() and not killed:
                        record = json.loads(startup.read_text(encoding="utf-8"))
                        assert not (path.parent / "healthy.json").exists(), "Missed startup failure boundary"
                        assert native.stop(record["pid"], record["stamp"])
                        killed = True
                if (
                    case in ("happy", "rollback")
                    and state
                    and state["status"] == ("healthy" if case == "happy" else "restored")
                ):
                    break
                if child.poll() is not None:
                    if child.returncode:
                        raise RuntimeError((work / "old-app.log").read_text(errors="replace"))
                    if case not in ("happy", "rollback"):
                        break
                time.sleep(0.01 if case == "rollback" else 0.1)
            else:
                raise TimeoutError("Native Windows update did not reach its expected terminal state")
            events = [
                json.loads(line) for line in (work / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            if case in ("happy", "rollback"):
                assert (work / "recording-gate").exists() and (work / "save-gate").exists()
                assert state["previous_version"] == old_version
                installed_manifest = json.loads(
                    (installed / "build-manifest.json").read_text(encoding="utf-8")
                )
                assert installed_manifest["version"] == (
                    manifest["version"] if case == "happy" else old_version
                )
                if case == "happy":
                    assert preserved_files(installed / "linguaflow") == {
                        p.removeprefix("linguaflow/"): sha
                        for p, sha in manifest["source_files"].items()
                        if p.startswith("linguaflow/")
                    }
                else:
                    until = time.monotonic() + 30
                    while time.monotonic() < until:
                        if not (data / "updates/notice.json").exists() and any(
                            os.path.normcase(p.info["exe"] or "") == os.path.normcase(str(executable))
                            for p in psutil.process_iter(["exe"])
                        ):
                            break
                        time.sleep(0.1)
                    else:
                        raise TimeoutError("Restored old client did not relaunch and consume recovery notice")
                (work / "recovery-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
            else:
                assert any(e["stage"] == ("cancelled" if case == "cancel" else "error") for e in events), (
                    events
                )
                assert inventory(installed) == before
                assert not state or state["status"] == "cancelled"
            assert expected == (
                preserved_files(work / "recordings"),
                preserved_files(external),
                digest(model),
                digest(runtime),
            )
            prefs = QSettings("LinguaFlow", "LocalCaptions")
            prefs.sync()
            assert (
                prefs.value("appearance") == "dark"
                and prefs.value("update_probe_sentinel") == "preserve this preference"
            )
            passed = True
            return dict(
                case=case,
                old_version=old_version,
                old_commit=old_manifest["source_commit"],
                candidate_commit=manifest["source_commit"],
                expected_version=manifest["version"],
                status=state["status"] if state else "retained",
                preserved=True,
                live=live,
                fault_after_startup=killed,
                events=events,
            )
    finally:
        for process in psutil.process_iter(["exe", "pid"]):
            if os.path.normcase(process.info["exe"] or "") == os.path.normcase(str(executable)):
                stamp = native.stamp(process.pid)
                if stamp:
                    assert native.stop(process.pid, stamp)
        if child:
            child.wait(timeout=15)
        if server:
            server.shutdown()
            server.server_close()
        if passed:
            copies = [installed]
            if state:
                copies += [Path(state["backup"]), Path(state["failed"])]
            for copy in copies:
                if copy.exists():
                    assert copy.parent == work and not copy.is_symlink()
                    shutil.rmtree(copy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("old-installer", "candidate", "manifest", "signature", "work"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("Run only on a disposable Windows GitHub runner")
    import psutil
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from linguaflow.runtime_paths import user_data_root

    if any(Path(p.info["exe"] or "").name.lower() == "agentscribe.exe" for p in psutil.process_iter(["exe"])):
        parser.error("An unrelated AgentScribe process already exists")
    if user_data_root().exists() and any(user_data_root().iterdir()):
        parser.error("Existing user data found; require a fresh runner")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assert manifest["target"] == "windows-x64" and manifest["source_modified"] is False
    assert (
        digest(args.candidate) == manifest["installer_sha256"]
        and args.candidate.stat().st_size == manifest["installer_bytes"]
    )
    config = json.loads((ROOT / "packaging/updates.json").read_text(encoding="utf-8"))
    signature = args.signature.read_text().strip()
    Ed25519PublicKey.from_public_bytes(
        base64.b64decode(config["targets"]["windows-x64"]["public_key"])
    ).verify(base64.b64decode(signature), args.candidate.read_bytes())
    args.work = args.work.resolve()
    args.work.mkdir(parents=True, exist_ok=False)
    results = []
    for case in ("happy",) if args.live else ("tampered", "interrupted", "cancel", "happy", "rollback"):
        results.append(
            run_case(
                case,
                args.work / case,
                args.old_installer.resolve(),
                args.candidate.resolve(),
                manifest,
                signature,
                args.live,
            )
        )
        (args.work / "result.json").write_text(
            json.dumps(
                dict(candidate_sha256=manifest["installer_sha256"], cases=results),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(case, results[-1]["status"], flush=True)


if __name__ == "__main__":
    main()
