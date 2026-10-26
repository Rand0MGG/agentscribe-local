// Own only the short-lived, device-free platform/material helpers.
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
class PlatformHelpers {
  constructor() { this.jobs = new Map(); this.closed = false; }
  run(executable, args, options) {
    if (this.closed) return Promise.reject(new Error('Platform helpers are closing'));
    const result = promisify(execFile)(executable, args, options);
    const child = result.child;
    const exited = new Promise(resolve => child.once('close', resolve));
    this.jobs.set(child, exited);
    exited.then(() => this.jobs.delete(child));
    return result;
  }
  cancel() {
    for (const child of this.jobs.keys()) {
      if (child.exitCode === null && child.signalCode === null) child.kill();
    }
  }
  async close() {
    this.closed = true;
    this.cancel();
    await Promise.all([...this.jobs.values()]);
  }
}
module.exports = { PlatformHelpers };
