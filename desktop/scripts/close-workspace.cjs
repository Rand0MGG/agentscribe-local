// Require actual clean exit, including owned helpers, rather than an IPC receipt
// from a renderer that may already have been destroyed by successful shutdown.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
module.exports = async function closeWorkspace(application, page) {
  const child = application.process();
  const root = path.resolve(__dirname, '../..');
  const python = process.env.AGENTSCRIBE_DESKTOP_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const owned = execFileSync(python, ['-c', `
import json,sys,psutil
rows=[]
for process in psutil.Process(int(sys.argv[1])).children(recursive=True):
    try: rows.append([process.pid,process.create_time()])
    except psutil.NoSuchProcess: pass
print(json.dumps(rows))
`, String(child.pid)], { encoding: 'utf8', timeout: 10000 });
  const closed = application.waitForEvent('close', { timeout: 15000 });
  const receipt = page.evaluate(() => window.agentScribe.request('window.close')).catch(error => {
    if (!error.message.includes('Target page, context or browser has been closed')) throw error;
  });
  await Promise.all([closed, receipt]);
  const deadline = Date.now() + 15000;
  while (child.exitCode === null && child.signalCode === null && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20));
  assert(page.isClosed()); assert.equal(child.exitCode, 0); assert.equal(child.signalCode, null);
  // A helper can still be releasing Qt frameworks after the UI exits. Wait for
  // the captured PID/creation-time identities before detaching the read-only DMG.
  // This never terminates processes or waits on unrelated applications.
  execFileSync(python, ['-c', `
import json,sys,time,psutil
owned=json.loads(sys.argv[1]);deadline=time.monotonic()+15
while True:
    alive=[]
    for pid,created in owned:
        try:
            process=psutil.Process(pid)
            if process.create_time()==created and process.status()!=psutil.STATUS_ZOMBIE: alive.append(pid)
        except psutil.NoSuchProcess: pass
    if not alive: break
    if time.monotonic()>deadline: raise SystemExit('Owned Electron helpers did not exit: '+str(alive))
    time.sleep(.05)
`, owned], { encoding: 'utf8', timeout: 18000 });
};
