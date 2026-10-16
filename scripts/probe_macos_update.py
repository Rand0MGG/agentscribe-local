"""Exercise real old DMG -> sealed candidate using Sparkle on a disposable Mac runner.

Only the local-feed pass redirects the old copy's feed URL (retaining its trust
key); --live uses the unmodified old app and its real HTTPS subscription.
Candidate bytes are never changed. Relaunch uses the normal application entry.
Never run on the user's Mac: the new app may discover the runner's empty devices.
"""
import argparse
import base64
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
SPARKLE = 'http://www.andymatuschak.org/xml-namespaces/sparkle'
HARNESS = r'''
import json,sys,time
from pathlib import Path
from PySide6.QtCore import QSettings,QTimer
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.recording_state import RecordingState
from linguaflow.update_recovery import startup
startup()
work=Path(WORK)
app=QApplication([])
Window.check_model_assets=lambda self:None
prefs=QSettings('LinguaFlow','LocalCaptions')
prefs.setValue('library_directory',str(work/'recordings'))
prefs.setValue('appearance','dark')
prefs.setValue('update_probe_sentinel','preserve this preference')
w=Window(discover=False,prefs=prefs,library_root=work/'recordings');w.show()
u=w.native_updater
def event(e):
    with (work/'events.jsonl').open('a') as f:f.write(json.dumps(e,ensure_ascii=False)+'\n')
    stage=e.get('stage')
    if stage=='available':QTimer.singleShot(0,u.adapter.download)
    elif stage=='downloading' and CASE=='cancel' and e.get('progress',0)>2:
        u.cancel();QTimer.singleShot(500,w.close)
    elif stage=='ready':
        assert CASE in ('happy','rollback')
        w.set_recording_state(RecordingState.LISTENING)
        w.save_error='fixture pending save'
        u.confirm_install()
        assert u.pending and not u.installing and u.shutdown_job is None
        (work/'recording-gate').write_text('held')
        def finish_recording():
            w.set_recording_state(RecordingState.IDLE)
            w.try_install_update()
            assert u.shutdown_job is None and not u.installing
            (work/'save-gate').write_text('held')
            w.save_error=''
            w.try_install_update()
        QTimer.singleShot(300,finish_recording)
    elif stage=='error':
        assert CASE in ('tampered','interrupted','cancel'),e
        QTimer.singleShot(100,w.close)
u.event.connect(event)
QTimer.singleShot(200,w.check_software_updates)
QTimer.singleShot(240000,app.quit)
sys.exit(app.exec())
'''


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


@contextmanager
def mount(image, destination):
    destination.mkdir()
    subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(destination), str(image)],
                   check=True, capture_output=True, timeout=60)
    try:
        yield destination / 'AgentScribe.app'
    finally:
        subprocess.run(['hdiutil', 'detach', str(destination)], check=True, capture_output=True, timeout=60)


def owned_processes(executable):
    rows = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True).splitlines()
    return [int(row.split(None, 1)[0]) for row in rows
            if (row.strip().split(None, 1)[1] == str(executable)
                or row.strip().split(None, 1)[1].startswith(str(executable) + ' '))]


def stop_owned(executable, native):
    for pid in owned_processes(executable):
        stamp = native.stamp(pid)
        if stamp:
            assert native.stop(pid, stamp), 'Could not stop owned isolated app'


def preserved_files(root):
    return {str(p.relative_to(root)): digest(p) for p in root.rglob('*') if p.is_file()}


def run_case(case, work, old_app, candidate, manifest, signature, live):
    from linguaflow.core import Caption
    from linguaflow.library import Library
    from linguaflow.update_recovery import NativeRecovery, inventory
    work.mkdir()
    installed = work / 'AgentScribe.app'
    subprocess.run(['ditto', str(old_app), str(installed)], check=True)
    executable = installed / 'Contents/MacOS/AgentScribe'
    resources = installed / 'Contents/Resources'
    old_info = plistlib.loads((installed / 'Contents/Info.plist').read_bytes())
    old_version = old_info['AgentScribeVersion']
    old_manifest = json.loads((resources / 'build-manifest.json').read_text())
    assert old_manifest['source_modified'] is False and old_manifest['version'] == old_version
    native = NativeRecovery(installed / 'Contents/Frameworks/AgentScribeRecovery.dylib')
    library = Library(work / 'recordings')
    folder = library.ensure_default_folder()
    item = library.create(folder['id'], {}, name='升级保留的课堂录音')
    library.save(item, [Caption(1, 0., 1., 'preserved transcript', 'en', final=True)], state='complete')
    import wave
    with wave.open(str(library.directory(item['id']) / 'audio.wav'), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0' * 32000)
    deleted = library.create(folder['id'], {}, name='最近删除也应保留')
    library.trash(deleted)
    external = work / 'external'
    external.mkdir()
    (external / '用户资料.txt').write_text('Never delete unrelated user files')
    data_root = Path.home() / 'Library/Application Support/AgentScribe'
    model = data_root / 'models' / case / 'preserved-model.bin'
    runtime = data_root / 'runtime' / case / 'preserved-component'
    for marker, value in ((model, b'existing model marker'), (runtime, b'existing component marker')):
        marker.parent.mkdir(parents=True)
        marker.write_bytes(value)
    expected = preserved_files(work / 'recordings'), preserved_files(external), digest(model), digest(runtime)
    server = None
    if not live:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path.split('?', 1)[0] == '/feed.xml':
                    feed = ET.Element('rss', {'version': '2.0', 'xmlns:sparkle': SPARKLE})
                    channel = ET.SubElement(feed, 'channel')
                    entry = ET.SubElement(channel, 'item')
                    ET.SubElement(entry, 'sparkle:minimumSystemVersion').text = manifest['minimum_macos']
                    ET.SubElement(entry, 'enclosure', {'url': f'http://127.0.0.1:{server.server_port}/update.dmg',
                        'length': str(candidate.stat().st_size), 'type': 'application/octet-stream',
                        'sparkle:version': manifest['version'], 'sparkle:shortVersionString': manifest['version'],
                        'sparkle:edSignature': signature})
                    body = ET.tostring(feed, encoding='utf-8', xml_declaration=True)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/rss+xml')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(candidate.stat().st_size))
                self.end_headers()
                try:
                    with candidate.open('rb') as source:
                        sent = 0
                        while chunk := source.read(1024 * 1024):
                            if sent == 0 and case == 'tampered':
                                chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
                            self.wfile.write(chunk)
                            self.wfile.flush()
                            sent += len(chunk)
                            if case == 'interrupted':
                                self.close_connection = True
                                return
                            if case == 'cancel':
                                time.sleep(.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        old_info['SUFeedURL'] = f'http://127.0.0.1:{server.server_port}/feed.xml'
        (installed / 'Contents/Info.plist').write_bytes(plistlib.dumps(old_info))
        subprocess.run(['codesign', '--force', '--sign', '-', str(installed)], check=True, capture_output=True)
    installed_before = inventory(installed)
    harness = HARNESS.replace('WORK', repr(str(work))).replace('CASE', repr(case))
    child = None
    state = None
    passed = False
    try:
        with (work / 'old-app.log').open('wb') as log:
            child = subprocess.Popen([str(executable), '--python', '-c', harness], stdout=log, stderr=log,
                                     env={**os.environ, 'QT_QPA_PLATFORM': 'cocoa'})
            deadline = time.monotonic() + 300
            killed_startup = False
            while time.monotonic() < deadline:
                states = list((data_root / 'updates').glob('*/state.json'))
                for file in states:
                    value = json.loads(file.read_text())
                    if value.get('installed') == str(installed):
                        state = value
                        directory = file.parent
                        startup = directory / 'startup.json'
                        if case == 'rollback' and startup.exists() and not killed_startup:
                            record = json.loads(startup.read_text())
                            assert not (directory / 'healthy.json').exists(), 'Fault injection missed startup boundary'
                            assert native.stop(record['pid'], record['stamp'])
                            killed_startup = True
                if case == 'happy' and state and state['status'] == 'healthy':
                    break
                if case == 'rollback' and state and state['status'] == 'restored':
                    break
                if case not in ('happy', 'rollback') and child.poll() is not None:
                    break
                if child.poll() is not None and child.returncode != 0:
                    raise RuntimeError((work / 'old-app.log').read_text(errors='replace'))
                time.sleep(.01 if case == 'rollback' else .1)
            else:
                raise TimeoutError('Native update did not reach its expected terminal state')
            events = [json.loads(line) for line in (work / 'events.jsonl').read_text().splitlines()]
            if case in ('happy', 'rollback'):
                assert (work / 'recording-gate').exists() and (work / 'save-gate').exists()
                assert state['status'] == ('healthy' if case == 'happy' else 'restored')
                version = plistlib.loads((installed / 'Contents/Info.plist').read_bytes())['AgentScribeVersion']
                assert version == (manifest['version'] if case == 'happy' else old_version)
                assert state['previous_version'] == old_version
                (work / 'recovery-state.json').write_text(json.dumps(state, indent=2))
                if case == 'happy':
                    assert preserved_files(installed / 'Contents/Resources/linguaflow') == {
                        p.removeprefix('linguaflow/'): sha for p, sha in manifest['source_files'].items()
                        if p.startswith('linguaflow/')}
                    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(installed)], check=True, capture_output=True)
                else:
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        if owned_processes(executable) and not (data_root / 'updates/notice.json').exists():
                            break
                        time.sleep(.1)
                    else:
                        raise TimeoutError('Restored old application did not relaunch and consume recovery notice')
            else:
                assert any(e['stage'] == ('cancelled' if case == 'cancel' else 'error') for e in events), events
                assert not any(e['stage'] in ('ready', 'installing', 'installed') for e in events), events
                assert inventory(installed) == installed_before
            assert expected == (preserved_files(work / 'recordings'), preserved_files(external), digest(model), digest(runtime))
            from PySide6.QtCore import QSettings
            prefs = QSettings('LinguaFlow', 'LocalCaptions')
            prefs.sync()
            assert prefs.value('appearance') == 'dark'
            assert prefs.value('update_probe_sentinel') == 'preserve this preference'
            passed = True
            return dict(case=case, old_version=old_version, old_commit=old_manifest['source_commit'],
                        expected_version=manifest['version'], candidate_commit=manifest['source_commit'],
                        status=state['status'] if state else 'retained', preserved=True, live=live,
                        fault_after_startup=killed_startup, events=events)
    finally:
        stop_owned(executable, native)
        if child:
            child.wait(timeout=15)
        if server:
            server.shutdown()
            server.server_close()
        if passed:
            # Keep signed DMGs, logs, file inventories and user-data fixtures;
            # discard only redundant app copies created by this completed test.
            copies = [installed]
            if state:
                copies += [work / ('.AgentScribe-' + kind + '-' + state['token']) for kind in ('previous', 'failed')]
            for copy in copies:
                if copy.exists():
                    assert copy.parent == work and not copy.is_symlink()
                    shutil.rmtree(copy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-dmg', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--signature', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Run only on a disposable GitHub Mac runner, never on the user recording machine')
    if any('AgentScribe.app/Contents/MacOS/AgentScribe' in line for line in
           subprocess.check_output(['ps', '-axo', 'command='], text=True).splitlines()):
        parser.error('An AgentScribe process already exists; do not touch an unrelated application')
    args.work = args.work.resolve()
    args.work.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(args.manifest.read_text())
    assert not manifest['source_modified'] and manifest['target'] == 'macos-arm64'
    assert digest(args.candidate) == manifest['dmg_sha256']
    configuration = json.loads((ROOT / 'packaging/updates.json').read_text())
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    public = configuration['targets']['macos-arm64']['public_key']
    signature = args.signature.read_text().strip()
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public)).verify(base64.b64decode(signature), args.candidate.read_bytes())
    with mount(args.old_dmg, args.work / 'old-volume') as old_app:
        old_info = plistlib.loads((old_app / 'Contents/Info.plist').read_bytes())
        assert old_info['SUPublicEDKey'] == public
        results = []
        for case in (('happy',) if args.live else ('tampered', 'interrupted', 'cancel', 'happy', 'rollback')):
            result = run_case(case, args.work / case, old_app, args.candidate.resolve(), manifest, signature, args.live)
            results.append(result)
            (args.work / 'result.json').write_text(json.dumps(dict(candidate_sha256=manifest['dmg_sha256'], cases=results), ensure_ascii=False, indent=2))
            print(case, result['status'], flush=True)


if __name__ == '__main__':
    main()
