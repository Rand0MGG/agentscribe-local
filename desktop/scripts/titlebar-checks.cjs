// Exercise the real bootstrap/settings routes; keep the native overlay setter.
const assert = require('node:assert/strict');
module.exports = async function checkWindowsTitlebar(desktop, page) {
  if (process.platform !== 'win32') return;
  await desktop.evaluate(({ BrowserWindow }) => {
    const target = BrowserWindow.getAllWindows()[0];
    target.originalTitlebarSetter = target.setTitleBarOverlay;
    target.setTitleBarOverlay = function (options) {
      this.lastTitlebarOverlay = options;
      return this.originalTitlebarSetter(options);
    };
  });
  try {
    for (const [appearance, symbolColor] of [['dark', '#ededf0'], ['light', '#29292d']]) {
      await page.evaluate(value => window.agentScribe.request('settings.set', { values: { appearance: value } }), appearance);
      await page.waitForFunction(value => document.documentElement.dataset.theme === value, appearance);
      const applied = () => desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].lastTitlebarOverlay);
      assert.deepEqual(await applied(), { color: '#00000000', symbolColor, height: 36 }, `${appearance}: native buttons must blend into the material`);
      // Reproduce the constructor's cold state, then load the saved theme via
      // the actual bootstrap path. A theme-change-only fix would miss this.
      await desktop.evaluate(({ BrowserWindow }) => {
        const target = BrowserWindow.getAllWindows()[0];
        target.originalTitlebarSetter({ color: '#f7f5f5', symbolColor: '#29292d', height: 36 });
        target.lastTitlebarOverlay = null;
      });
      await page.reload();
      await page.getByRole('button', { name: '新录音', exact: true }).waitFor();
      assert.deepEqual(await applied(), { color: '#00000000', symbolColor, height: 36 }, `${appearance}: bootstrap must restore native button colors`);
      const geometry = await page.evaluate(() => ({
        overlay: navigator.windowControlsOverlay.getTitlebarAreaRect().toJSON(),
        visible: navigator.windowControlsOverlay.visible,
        height: document.querySelector('.titlebar').getBoundingClientRect().height,
        width: innerWidth,
      }));
      assert(geometry.visible && geometry.overlay.height === geometry.height);
      assert(geometry.width - geometry.overlay.width >= 120, 'Native control hit area must remain reserved');
    }
  } finally {
    await desktop.evaluate(({ BrowserWindow }) => {
      const target = BrowserWindow.getAllWindows()[0];
      target.setTitleBarOverlay = target.originalTitlebarSetter;
      delete target.originalTitlebarSetter;
      delete target.lastTitlebarOverlay;
    });
  }
};
