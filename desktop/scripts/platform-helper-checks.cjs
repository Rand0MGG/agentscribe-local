// Exercise real child exit and cancellation without devices or application data.
const assert = require('node:assert/strict');
const { once } = require('node:events');
const { PlatformHelpers } = require('../electron/platform-helpers.cjs');

async function main() {
  const helpers = new PlatformHelpers();
  assert.equal((await helpers.run(process.execPath, ['-e', 'process.stdout.write("ready")'])).stdout, 'ready');
  const start = () => helpers.run(process.execPath, ['-e', 'setInterval(() => {}, 1000)']);
  const cancelled = start();
  const rejected = assert.rejects(cancelled, error => error.killed);
  await once(cancelled.child, 'spawn');
  helpers.cancel();
  await rejected;
  const pending = [start(), start()];
  const failures = pending.map(job => assert.rejects(job, error => error.killed));
  await Promise.all(pending.map(job => once(job.child, 'spawn')));
  await helpers.close();
  await Promise.all(failures);
  assert.equal(helpers.jobs.size, 0);
  assert(pending.every(job => job.child.exitCode !== null || job.child.signalCode !== null));
  await assert.rejects(start(), /closing/);
  console.log('Platform helpers: real completion, cancellation, reuse and shutdown passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
