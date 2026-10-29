const net = require('node:net');

function watchLauncher(endpoint, onLost) {
  if (!endpoint) return;
  const match = /^(\d+):([a-f0-9]{32})$/.exec(endpoint);
  if (!match || Number(match[1]) < 1 || Number(match[1]) > 65535) throw new Error('桌面启动连接无效。');
  let lost = false;
  const disconnected = () => { if (!lost) { lost = true; onLost(); } };
  const channel = net.createConnection({ host: '127.0.0.1', port: Number(match[1]) });
  channel.once('connect', () => channel.write(match[2] + '\n'));
  channel.once('end', disconnected);
  channel.once('error', disconnected);
  return channel;
}

module.exports = { watchLauncher };
