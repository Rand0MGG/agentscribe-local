// Noninteractive helpers own no user windows. A closed parent/output is cancellation.
function ownHelper(app, { timeout = 110000 } = {}) {
  const owner = Number(process.env.AGENTSCRIBE_HELPER_OWNER_PID || process.ppid);
  if (process.platform === 'darwin') app.setActivationPolicy('accessory');
  let exiting = false;
  const stop = code => { if (!exiting) { exiting = true; app.exit(code); } };
  const broken = error => ['EPIPE', 'ERR_STREAM_DESTROYED'].includes(error.code);
  for (const stream of [process.stdout, process.stderr]) {
    stream.on('error', error => stop(broken(error) ? 0 : 1));
  }
  const watcher = setInterval(() => {
    try { process.kill(owner, 0); } catch (error) { if (error.code === 'ESRCH') stop(0); }
  }, 100);
  const deadline = setTimeout(() => stop(2), timeout);
  function write(stream, text) {
    return new Promise(resolve => {
      if (exiting) { resolve(); return; }
      stream.write(text, error => { if (error) stop(broken(error) ? 0 : 1); resolve(); });
    });
  }
  async function finish(value) {
    await write(process.stdout, JSON.stringify(value));
    stop(0);
  }
  async function fail(error) {
    await write(process.stderr, String(error?.message || error));
    stop(1);
  }
  // A helper failure must be returned to its owner, never open Electron's modal dialog.
  process.on('uncaughtException', fail);
  process.on('unhandledRejection', fail);
  app.on('quit', () => { clearInterval(watcher); clearTimeout(deadline); });
  return { finish, fail };
}
module.exports = { ownHelper };
