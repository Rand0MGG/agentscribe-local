// Probe-only observation of the real request/event path; never changes replies.
const fs = require('node:fs');
const path = require('node:path');

async function install(app, root) {
  await app.evaluate((_electron, root) => {
    const { Service } = process.getBuiltinModule('module').createRequire(root + '/desktop/package.json')('./electron/service.cjs');
    const request = Service.prototype.request;
    const trace = globalThis.playbackProbe = { requests: [], events: [] };
    Service.prototype.request = function(method, params) {
      if (trace.service !== this) {
        trace.service = this;
        this.on('event', value => {
          if (['playback', 'notice'].includes(value.event)) trace.events.push({ ...value, at: Date.now() });
          if (value.event === 'state') trace.events.push({ event: 'state', at: Date.now(), data: {
            generation: value.data.generation, state: value.data.state, has_audio: value.data.has_audio,
          } });
        });
        this.on('fault', message => trace.events.push({ event: 'fault', message }));
      }
      const result = request.call(this, method, params);
      if (method.startsWith('playback.') || method === 'recording.open') {
        const row = { method, params, at: Date.now() };
        trace.requests.push(row);
        result.then(() => { row.result = 'ok'; row.finished = Date.now(); }, error => { row.error = error.message; row.finished = Date.now(); });
      }
      return result;
    };
  }, root);
}

async function capture(app, page, fixture, output, stage) {
  const backend = await app.evaluate(() => {
    const trace = globalThis.playbackProbe;
    return trace ? { requests: trace.requests.slice(-20), events: trace.events.slice(-30),
      stderr: trace.service?.stderr, pending: trace.service?.pending.size, closed: trace.service?.closed } : {};
  }).catch(error => ({ error: error.message }));
  const dom = await page.evaluate(() => ({
    active: document.querySelector('.caption-region')?.dataset.active,
    selection: getSelection()?.toString(), visibility: document.visibilityState,
    labels: [...document.querySelectorAll('.playback-group button')].map(node => ({ label: node.getAttribute('aria-label'), disabled: node.disabled })),
  })).catch(error => ({ error: error.message }));
  const mediaPath = path.join(fixture, 'media.jsonl');
  const report = { stage, backend, dom, media: fs.existsSync(mediaPath) ? fs.readFileSync(mediaPath, 'utf8') : '' };
  fs.writeFileSync(path.join(output, 'playback-diagnosis.json'), JSON.stringify(report, null, 2));
  console.log('PLAYBACK_DIAGNOSIS ' + JSON.stringify(report));
}

module.exports = { install, capture };
