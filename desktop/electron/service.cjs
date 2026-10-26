const { EventEmitter } = require('node:events');
const { spawn } = require('node:child_process');
const { StringDecoder } = require('node:string_decoder');

const VERSION = 1;
const MAX_FRAME = 16 * 1024 * 1024;

class Service extends EventEmitter {
  constructor(python, args, options = {}) {
    super();
    this.sequence = 0;
    this.pending = new Map();
    this.buffer = '';
    this.decoder = new StringDecoder('utf8');
    this.closed = false;
    this.ready = false;
    this.stderr = '';
    this.child = spawn(python, ['-u', '-m', 'linguaflow.desktop_service', ...args], {
      ...options, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, ...options.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
    });
    this.finished = new Promise(resolve => this.child.once('close', (code, signal) => resolve({ code, signal })));
    this.child.stdout.on('data', chunk => this.receive(chunk));
    this.child.stderr.on('data', chunk => { this.stderr = (this.stderr + chunk.toString('utf8')).slice(-4000); });
    this.child.stdin.on('error', error => this.fail(error));
    this.child.on('error', error => this.fail(error));
    this.child.on('exit', (code, signal) => {
      this.closed = true;
      this.fail(new Error(`本地后台已退出（${code ?? signal}）。已有录音保留，请重新打开应用。`));
      this.emit('exit', { code, signal });
    });
  }

  receive(chunk) {
    this.buffer += this.decoder.write(chunk);
    if (Buffer.byteLength(this.buffer) > MAX_FRAME) {
      this.fail(new Error('后台消息超过容量限制。请保留录音并重新打开应用。'));
      this.child.stdin.end();
      return;
    }
    let index;
    while ((index = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, index);
      this.buffer = this.buffer.slice(index + 1);
      let value;
      try { value = JSON.parse(line); } catch {
        this.fail(new Error('后台通信格式无效，请重新打开应用。'));
        this.child.stdin.end();
        return;
      }
      if (!value || typeof value !== 'object') continue;
      if (value.event) {
        // Once durable shutdown completes, release the protocol reader before
        // waiting for Python's actual process exit.
        if (value.event === 'closed' && this.child.stdin.writable) this.child.stdin.end();
        if (value.event === 'ready') {
          if (value.data?.protocol !== VERSION) {
            this.fail(new Error('桌面与后台协议版本不一致。'));
            this.child.stdin.end();
            return;
          }
          this.ready = true;
        }
        this.emit('event', value);
      } else {
        const entry = this.pending.get(value.id);
        if (!entry) continue;
        clearTimeout(entry.timer);
        this.pending.delete(value.id);
        if (value.error) entry.reject(new Error(value.error.message));
        else entry.resolve(value.result);
      }
    }
  }

  request(method, params = {}) {
    if (this.closed || !this.child.stdin.writable) return Promise.reject(new Error('本地后台未连接。'));
    if (this.pending.size >= 64) return Promise.reject(new Error('操作过多，请等待当前请求完成。'));
    const id = ++this.sequence;
    const line = JSON.stringify({ version: VERSION, id, method, params }) + '\n';
    if (Buffer.byteLength(line) > 1024 * 1024) return Promise.reject(new Error('操作内容过大，请分批处理。'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('后台响应超时，操作可能仍在完成。请查看当前状态，避免重复提交。'));
      }, 60000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(line, 'utf8', error => { if (error) this.fail(error); });
    });
  }

  fail(error) {
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
    this.pending.clear();
    this.emit('fault', error.message);
  }
}

module.exports = { Service, VERSION };
