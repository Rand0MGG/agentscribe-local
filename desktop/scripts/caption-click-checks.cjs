const assert = require('node:assert/strict');

// P2: a short physical click must survive delayed renderer event delivery.
// Keep the real browser input, React handler, IPC and playback adapter in use.
module.exports = async function clickWhileBusy(target) {
  const trace = await target.evaluateHandle(node => {
    const events = [];
    const record = event => {
      if (!node.contains(event.target)) return;
      const range = document.createRange(); range.selectNodeContents(node);
      const rectangles = [...range.getClientRects()].map(rect => ({ x: rect.x, y: rect.y, width: rect.width, height: rect.height }));
      events.push({ type: event.type, input: event.timeStamp, handled: performance.now(), button: event.button, detail: event.detail,
        x: event.clientX, y: event.clientY, selection: getSelection()?.toString(), font: getComputedStyle(node).font,
        rectangles, hit: rectangles.some(rect => event.clientX >= rect.x && event.clientX <= rect.x + rect.width && event.clientY >= rect.y && event.clientY <= rect.y + rect.height) });
    };
    const stall = event => {
      if (node.contains(event.target)) queueMicrotask(() => {
        const until = performance.now() + 500;
        while (performance.now() < until) { /* Simulate a busy renderer after React's mousedown. */ }
      });
    };
    document.addEventListener('mousedown', record, true);
    document.addEventListener('click', record, true);
    document.addEventListener('mousedown', stall);
    return { events, cleanup() {
      document.removeEventListener('mousedown', record, true);
      document.removeEventListener('click', record, true);
      document.removeEventListener('mousedown', stall);
    } };
  });
  try {
    await target.click({ position: { x: 15, y: 10 } });
    const events = await trace.evaluate(state => state.events);
    console.log('CAPTION_CLICK ' + JSON.stringify(events));
    assert.deepEqual(events.map(event => event.type), ['mousedown', 'click']);
    assert(events[1].input - events[0].input <= 400, JSON.stringify(events));
    assert(events[1].handled - events[0].handled >= 500, JSON.stringify(events));
  } finally {
    await trace.evaluate(state => state.cleanup());
    await trace.dispose();
  }
};
