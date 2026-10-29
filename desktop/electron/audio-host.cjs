const { BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
class AudioHost {
  constructor(send, noAudio) {
    this.send = send; this.noAudio = noAudio; this.window = null; this.ready = null;
    this.listener = (event, value) => {
      if (this.window && event.sender === this.window.webContents) this.send(value).catch(error => console.error('Playback state:', error.message));
    };
    ipcMain.on('audio:state', this.listener);
  }
  async command(value) {
    if (value.operation === 'release' && !this.window) return;
    if (this.noAudio) throw Error('无音频模式禁止初始化播放器。');
    if (!this.window) {
      this.window = new BrowserWindow({ show: false, webPreferences: {
        preload: path.join(__dirname, 'audio-preload.cjs'), sandbox: true, contextIsolation: true,
        nodeIntegration: false, backgroundThrottling: false, partition: 'audio-playback',
      } });
      this.window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
      this.window.webContents.on('will-navigate', event => event.preventDefault());
      this.window.webContents.session.setPermissionRequestHandler((_c, _p, done) => done(false));
      this.ready = this.window.loadURL('data:text/html,' + encodeURIComponent('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; media-src http://127.0.0.1:*">'));
    }
    const target = this.window;
    await this.ready;
    if (target === this.window && !target.isDestroyed()) target.webContents.send('audio:command', value);
  }
  reset() {
    this.window?.destroy(); this.window = null; this.ready = null;
  }
  close() {
    ipcMain.removeListener('audio:state', this.listener);
    this.reset();
  }
}
module.exports = { AudioHost };
