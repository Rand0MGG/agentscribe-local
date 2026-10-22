"""Real Sparkle callbacks: background HTTP failure, manual retry and cancellation."""
import json
import os
import plistlib
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = r'''
#import <Cocoa/Cocoa.h>
int ASUpdaterStart(void (*callback)(const char *));
int ASUpdaterCheck(int manual, uint64_t requestID);
void ASUpdaterChoose(int action);
void ASUpdaterStop(void);
static uint64_t finished;
static void receive(const char *data) {
    puts(data); fflush(stdout);
    NSDictionary *event = [NSJSONSerialization JSONObjectWithData:
        [[NSString stringWithUTF8String:data] dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];
    if ([event[@"stage"] isEqualToString:@"cycle-finished"]) finished = [event[@"request"] unsignedLongLongValue];
}
int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        if (!ASUpdaterStart(receive)) return 2;
        for (uint64_t request = 1; request <= 3; request++) {
            if (!ASUpdaterCheck(request != 1, request)) return 3;
            if (request == 3) dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC/10),
                dispatch_get_main_queue(), ^{ ASUpdaterChoose(0); });
            NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:25];
            while (finished != request && deadline.timeIntervalSinceNow > 0)
                [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.02]];
            if (finished != request) return 4;
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.25]];
        }
        ASUpdaterStop();
    }
    return 0;
}
'''


@pytest.mark.p2
@pytest.mark.skipif(sys.platform != 'darwin', reason='Native Sparkle callback integration')
def test_native_background_404_does_not_block_manual_retry_or_cancel(tmp_path):
    from scripts.packaging_common import extract, obtain
    configuration = json.loads((ROOT / 'packaging/updates.json').read_text())
    item = configuration['targets']['macos-arm64']
    downloads = ROOT / '.work/packaging/downloads'
    if not (downloads / item['filename']).is_file():
        if os.environ.get('AGENTSCRIBE_REQUIRE_NATIVE_UPDATE_TEST'):
            pytest.fail('Pinned Sparkle archive is required for native update verification')
        pytest.skip('Pinned Sparkle build dependency is not cached')
    framework_source = tmp_path / 'sparkle'
    extract(obtain(item, downloads), framework_source)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            import time
            requests.append(self.path)
            if len(requests) == 3:
                time.sleep(.5)
            body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Probe</title></channel></rss>'
            self.send_response(404 if len(requests) == 1 else 200)
            self.send_header('Content-Type', 'application/rss+xml')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    app = tmp_path / 'CycleProbe.app'
    contents = app / 'Contents'
    frameworks, macos = contents / 'Frameworks', contents / 'MacOS'
    frameworks.mkdir(parents=True)
    macos.mkdir()
    shutil.copytree(framework_source / 'Sparkle.framework', frameworks / 'Sparkle.framework', symlinks=True)
    info = dict(CFBundleExecutable='CycleProbe', CFBundleIdentifier='io.github.rand0mgg.agentscribe.cycle-probe',
                CFBundlePackageType='APPL', CFBundleVersion='0.9.2', CFBundleShortVersionString='0.9.2',
                SUPublicEDKey=item['public_key'], SUFeedURL=f'http://127.0.0.1:{server.server_port}/feed.xml',
                SUEnableAutomaticChecks=False, SUAutomaticallyUpdate=False,
                NSAppTransportSecurity={'NSAllowsArbitraryLoads': True})
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    host = tmp_path / 'host.m'
    host.write_text(HOST)
    try:
        subprocess.run(['clang', '-fobjc-arc', '-fblocks', '-Wno-unused-parameter',
                        '-F', str(framework_source), '-framework', 'Cocoa', '-framework', 'Sparkle',
                        '-Wl,-rpath,@executable_path/../Frameworks', str(ROOT / 'packaging/macos/updater.m'),
                        str(host), '-o', str(macos / 'CycleProbe')], check=True, capture_output=True)
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True, capture_output=True)
        result = subprocess.run([str(macos / 'CycleProbe')], capture_output=True, text=True, timeout=90)
        (tmp_path / 'native.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        assert any(e['stage'] == 'error' and e['request'] == 1 for e in events), events
        assert any(e['stage'] == 'latest' and e['request'] == 2 for e in events), events
        assert {e['request'] for e in events if e['stage'] == 'cycle-finished'} == {1, 2, 3}, events
        assert not any(e['stage'] in ('available', 'ready', 'installing') for e in events), events
    finally:
        server.shutdown()
        server.server_close()
