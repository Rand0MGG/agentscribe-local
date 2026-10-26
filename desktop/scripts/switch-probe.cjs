// Actual native Electron -> Qt -> Electron handoff, with isolated data and no audio.
const { _electron: electron, chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const { mkdtempSync, mkdirSync, existsSync, readFileSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(action, seconds = 35) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) { const value = await action(); if (value) return value; await pause(100); }
  throw new Error('Native frontend handoff did not complete before deadline');
}
async function main() {
  const root = path.resolve(__dirname, '../..'), evidence = path.join(root, 'output/playwright/switch');
  mkdirSync(evidence, { recursive: true });
  const fixture = mkdtempSync(path.join(evidence, 'probe-'));
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  const python = process.env.AGENTSCRIBE_DESKTOP_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  execFileSync(python, ['-c', `
import sys
from pathlib import Path
from dataclasses import asdict
from scripts.test_no_audio import GUARD
from linguaflow.library import Library
from linguaflow.core import Caption, Settings
root=Path(sys.argv[1])
(root/'sitecustomize.py').write_text(GUARD, encoding='utf-8')
library=Library(root/'library')
folder=library.folder('切换对照')
item=library.create(folder['id'],asdict(Settings('preview')),'同一段录音 · 两个界面')
library.save(item,[Caption(1,0,4,'The same recording.','en','同一段录音。')],'complete')
`, fixture], { cwd: root, encoding: 'utf8' });
  // Harness-only observer: operates the real Qt Window and adds CDP to the next
  // Electron child. Neither path adds a production test API or fake backend.
  writeFileSync(path.join(fixture, 'sitecustomize.py'), readFileSync(path.join(fixture, 'sitecustomize.py'), 'utf8') + `
if __import__('os').environ.get('AGENTSCRIBE_SWITCH_PROBE'):
    import os, json
    from pathlib import Path
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    import subprocess
    _popen = subprocess.Popen
    class _ProbePopen(_popen):
        def __init__(self, args, *positional, **keyword):
            if isinstance(args, (list, tuple)) and len(args) > 1 and Path(args[1]).name == 'desktop' and Path(args[0]).name.lower() in ('electron', 'electron.exe'):
                args = [*args, '--remote-debugging-port=' + os.environ['AGENTSCRIBE_SWITCH_PORT']]
            super().__init__(args, *positional, **keyword)
    subprocess.Popen = _ProbePopen
    _exec = QApplication.exec
    def _probe_exec():
        from linguaflow.app import Window
        folder = Path(os.environ['AGENTSCRIBE_SWITCH_PROBE'])
        windows = [w for w in QApplication.topLevelWidgets() if isinstance(w, Window)]
        if not windows:
            return _exec()
        window = windows[0]
        def observe():
            if window.library_reader.busy:
                return
            (folder/'qt-ready.json').write_text(json.dumps(dict(pid=os.getpid(), context=os.environ.get('AGENTSCRIBE_FRONTEND_CONTEXT'),
                recording=window.current_item, no_audio=window.no_audio, visible=window.isVisible(),
                title=window.workspace_title.text(), captions=len(window.captions))),encoding='utf-8')
            command=folder/'qt-command'
            if command.exists():
                value=command.read_text();command.unlink()
                if value == 'switch':
                    window.open_settings('运行环境')
                    assert window.frontend_button.isVisible()
                    window.frontend_button.click()
                else:
                    window.close()
        timer=QTimer();timer.timeout.connect(observe);timer.start(100)
        return _exec()
    QApplication.exec=staticmethod(_probe_exec)
`);
  let first, second;
  try {
    first = await electron.launch({ executablePath: require('electron'), args: [path.join(root, 'desktop'), '--no-audio'], env: {
      ...process.env, AGENTSCRIBE_DESKTOP_PROFILE: path.join(fixture, 'profile'), AGENTSCRIBE_SWITCH_PROBE: fixture, AGENTSCRIBE_SWITCH_PORT: String(port),
      AGENTSCRIBE_DESKTOP_LIBRARY: path.join(fixture, 'library'), AGENTSCRIBE_DESKTOP_PREFERENCES: path.join(fixture, 'prefs.ini'),
      AGENTSCRIBE_LOG_DIR: path.join(fixture, 'logs'), AGENTSCRIBE_AUDIO_GUARD_LOG: path.join(fixture, 'blocked.log'),
      PYTHONPATH: [fixture, root, process.env.PYTHONPATH || ''].join(path.delimiter),
    }, timeout: 30000 });
    const page = await first.firstWindow();
    await page.getByRole('button', { name: '同一段录音 · 两个界面', exact: true }).click();
    await page.getByText('The same recording.', { exact: true }).waitFor();
    const before = await page.evaluate(() => window.agentScribe.request('bootstrap'));
    assert.equal(await page.getByRole('button', { name: '切换到 Qt 界面', exact: true }).count(), 0);
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await page.getByRole('button', { name: '运行环境', exact: true }).click();
    // An unsaved editor blocks handoff while the current UI remains available.
    await page.evaluate(() => window.agentScribe.request('window.edited', { owner: 'knowledge', dirty: true }));
    await page.getByRole('button', { name: '切换到 Qt 界面', exact: true }).click();
    await page.getByText(/请先保存或取消名称、术语及笔记编辑，再切换界面/).waitFor();
    await page.evaluate(() => window.agentScribe.request('window.edited', { owner: 'knowledge', dirty: false }));
    const closed = first.waitForEvent('close');
    await page.getByRole('button', { name: '切换到 Qt 界面', exact: true }).click();
    await closed;
    first = null;
    const qt = await until(() => existsSync(path.join(fixture, 'qt-ready.json')) && JSON.parse(readFileSync(path.join(fixture, 'qt-ready.json'), 'utf8')));
    assert(qt.visible && qt.no_audio && qt.captions === 1);
    assert.equal(qt.recording.id, before.state.item.id);
    assert.equal(qt.title, before.state.item.name);
    writeFileSync(path.join(fixture, 'qt-command'), 'switch');
    second = await until(async () => chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 500 }).catch(() => null));
    const reopened = await until(() => second.contexts()[0]?.pages().find(p => p.url().includes('index.html')));
    await reopened.getByText('The same recording.', { exact: true }).waitFor();
    const after = await reopened.evaluate(() => window.agentScribe.request('bootstrap'));
    assert(after.no_audio);
    assert.equal(after.state.item.id, before.state.item.id);
    assert.equal(after.root, before.root);
    assert.deepEqual(after.captions.rows, before.captions.rows);
    await reopened.screenshot({ path: path.join(evidence, 'roundtrip.png') });
    const closedAgain = reopened.waitForEvent('close');
    await reopened.evaluate(() => window.agentScribe.request('window.close')).catch(error => {
      if (!error.message.includes('Target page, context or browser has been closed')) throw error;
    });
    await closedAgain;
    await second.close(); second = null;
    assert(!existsSync(path.join(fixture, 'blocked.log')));
    writeFileSync(path.join(evidence, 'result.json'), JSON.stringify({ fixture, passed: true, recording: before.state.item.id, qt, audioAttempts: 0 }, null, 2));
    console.log('Native Electron -> Qt -> Electron roundtrip passed; same recording/captions/library, no audio.');
  } catch (error) { console.error(error); throw error; } finally {
    writeFileSync(path.join(fixture, 'qt-command'), 'close');
    if (first) {
      const page = await first.firstWindow().catch(() => null);
      if (page) await page.evaluate(() => window.agentScribe.request('window.edited', { owner: 'knowledge', dirty: false })).catch(() => {});
      await first.close();
    }
    if (second) await second.close();
    if (existsSync(path.join(fixture, 'blocked.log'))) throw new Error(readFileSync(path.join(fixture, 'blocked.log'), 'utf8'));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
