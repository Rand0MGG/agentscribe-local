const { ipcRenderer } = require('electron');
let current;
function report(session, error = '') {
  if (session !== current) return;
  const audio = session.audio;
  // A seek while output is resuming must not overwrite the backend play intent.
  if (!error && audio.paused && session.desiredPlaying && !audio.ended) return;
  ipcRenderer.send('audio:state', { epoch: session.epoch,
    state: error ? 'Error' : audio.ended ? 'StoppedState' : audio.paused ? 'PausedState' : 'PlayingState',
    position: Number.isFinite(audio.currentTime) ? audio.currentTime * 1000 : 0, error });
}
async function apply(session) {
  if (session !== current || session.audio.readyState < 1) return;
  const { audio, context } = session;
  if (session.pendingSeek !== undefined) { audio.currentTime = session.pendingSeek / 1000; session.pendingSeek = undefined; }
  if (session.desiredPlaying) {
    await context.resume();
    if (session === current && session.desiredPlaying) await audio.play();
  } else audio.pause();
}
function update(session) {
  apply(session).catch(error => {
    if (session === current && error.name !== 'AbortError') {
      session.desiredPlaying = false;
      session.pendingSeek = undefined;
      report(session, error.message);
    }
  });
}
ipcRenderer.on('audio:command', (_event, command) => {
  if (command.operation === 'release' || command.operation === 'load') {
    const previous = current;
    current = undefined; // Invalidate callbacks before resetting the old media element.
    if (previous) {
      previous.audio.pause(); previous.audio.removeAttribute('src'); previous.audio.load();
      previous.context.close().catch(() => {});
    }
    if (command.operation === 'release') return;
    const audio = new Audio(), context = new AudioContext(), gain = context.createGain();
    const session = current = { audio, context, gain, epoch: command.epoch, desiredPlaying: false };
    audio.crossOrigin = 'anonymous'; audio.preload = 'auto';
    const clip = context.createWaveShaper(); clip.curve = new Float32Array([-1, 0, 1]);
    context.createMediaElementSource(audio).connect(gain).connect(clip).connect(context.destination);
    for (const name of ['timeupdate', 'play', 'pause', 'ended']) audio.addEventListener(name, () => report(session));
    audio.addEventListener('error', () => {
      session.desiredPlaying = false; session.pendingSeek = undefined;
      report(session, '录音无法解码或音频输出不可用，请重新打开后重试。');
    });
    audio.addEventListener('loadedmetadata', () => update(session));
    audio.src = command.url;
    return;
  }
  const session = current;
  if (!session || command.epoch !== session.epoch) return;
  if (command.operation === 'volume') session.gain.gain.value = command.value / 100;
  if (command.operation === 'seek') { session.pendingSeek = command.position; if (command.play) session.desiredPlaying = true; }
  if (command.operation === 'play') session.desiredPlaying = true;
  if (command.operation === 'pause') session.desiredPlaying = false;
  update(session);
});
