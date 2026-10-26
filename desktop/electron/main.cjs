const { app, BrowserWindow, ipcMain, dialog, shell, session, Menu, screen, clipboard } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const { Service } = require('./service.cjs');
const { isSplitLayout } = require('./window-layout.cjs');
const { PlatformHelpers } = require('./platform-helpers.cjs');
const platformHelpers = new PlatformHelpers();

let restartService;
const root = path.resolve(__dirname, '../..');
const page = path.resolve(__dirname, '../dist/index.html');
const pageURL = pathToFileURL(page).href;
const methods = new Set([
  'bootstrap', 'frontend.ready', 'settings.set', 'library.refresh', 'recording.open', 'recording.new', 'folder.create',
  'item.rename', 'item.move', 'item.trash', 'trash.list', 'trash.restore', 'trash.purge',
  'captions.page', 'captions.search', 'recording.save', 'audio.refresh', 'audio.select',
  'recording.start', 'recording.stop', 'recording.pause', 'playback.toggle', 'playback.seek',
  'playback.volume', 'models.prepare', 'models.cancel', 'models.retry', 'knowledge.open', 'knowledge.command',
  'models.inventory', 'models.delete', 'updates.check', 'library.cancel_migration',
  'models.check', 'models.cancel_check', 'layout.sidebar',
  'recording.close_recovered', 'knowledge.image',
]);
let window, overlay, knowledge, service, quitting = false, state, preferences, overlayRows = [];
let installed = false;
let fault = process.env.AGENTSCRIBE_FRONTEND_RECOVERY || '';
app.setName('AgentScribe');
const edited = new Set();
let closePrompt = false, switching = false, bootstrapped = false;
let platformHints = { doubleClickInterval: 500, dragDistance: 10 };
let material, materialTimer, materialRefresh, materialBusy = false, materialAgain = false;
let quitTask, quitReady = false;
const desktopPython = () => process.env.AGENTSCRIBE_DESKTOP_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const titlebarOverlay = () => ({ color: '#00000000',
  symbolColor: preferences?.appearance === 'dark' ? '#ededf0' : '#29292d', height: 36 });
function updateWindowControls() {
  if (process.platform === 'win32' && window && !window.isDestroyed()) window.setTitleBarOverlay(titlebarOverlay());
}
function materialPosition() {
  if (!window || window.isDestroyed() || !material) return null;
  const bounds = window.getContentBounds(), display = screen.getDisplayMatching(bounds);
  return { image: material.image, appearance: material.appearance, width: display.bounds.width, height: display.bounds.height,
    x: display.bounds.x - bounds.x, y: display.bounds.y - bounds.y };
}
function requestMaterial() {
  clearTimeout(materialTimer);
  if (quitting || state?.closing) return;
  materialTimer = setTimeout(renderMaterial, 80);
}
function cancelMaterial() {
  clearTimeout(materialTimer); materialAgain = false;
  platformHelpers.cancel();
}
function quitAfterOwnedProcesses() {
  if (quitTask) return quitTask;
  quitting = true;
  cancelMaterial(); clearInterval(materialRefresh);
  quitTask = (async () => {
    await platformHelpers.close();
    const backend = await service?.finished;
    quitReady = true;
    if (backend && (backend.code !== 0 || backend.signal)) {
      console.error('本地后台未正常退出：', backend, service.stderr);
      app.exit(1);
    }
    else app.quit();
  })();
  return quitTask;
}
async function renderMaterial() {
  if (!window || window.isDestroyed() || quitting || state?.closing) return;
  if (materialBusy) { materialAgain = true; return; }
  materialBusy = true;
  const bounds = window.getContentBounds(), display = screen.getDisplayMatching(bounds);
  const appearance = preferences?.appearance === 'dark' ? 'dark' : 'light';
  const key = `${display.id}:${display.bounds.width}:${display.bounds.height}:${appearance}`;
  try {
    const args = ['-m', 'linguaflow.desktop_platform', '--material', '--size', String(display.bounds.width), String(display.bounds.height),
      '--position', String(bounds.x), String(bounds.y), '--appearance', appearance];
    if (material?.key === key) args.push('--signature', JSON.stringify(material.signature));
    const result = await platformHelpers.run(desktopPython(), args, { cwd: root, env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      windowsHide: true, timeout: 15000, maxBuffer: 16 * 1024 * 1024 });
    const value = JSON.parse(result.stdout);
    if (quitting || window.isDestroyed()) return;
    // Moving within the same display only changes the sampling offset. Keep a
    // useful completed image even if another position refresh was requested.
    const currentDisplay = screen.getDisplayMatching(window.getContentBounds());
    const currentAppearance = preferences?.appearance === 'dark' ? 'dark' : 'light';
    if (key === `${currentDisplay.id}:${currentDisplay.bounds.width}:${currentDisplay.bounds.height}:${currentAppearance}`) {
      material = { key, appearance, signature: value.signature, image: value.unchanged ? material.image : value.image };
      publish({ event: 'material', data: materialPosition() });
    }
  } catch (error) { if (!quitting && !state?.closing && !window?.isDestroyed()) console.error('窗口材质生成失败：', error.message); }
  finally { materialBusy = false; if (materialAgain) { materialAgain = false; requestMaterial(); } }
}

function publish(value) {
  for (const target of [window, overlay, knowledge]) {
    if (target && !target.isDestroyed()) target.webContents.send('desktop:event', value);
  }
}

function windowLayout() {
  const bounds = window.getBounds(), display = screen.getDisplayMatching(bounds);
  return { split: isSplitLayout(bounds, display.workArea) || isSplitLayout(bounds, display.bounds) };
}

async function openKnowledge() {
  // Validate the recording and Beta permission before showing a reading window.
  await service.request('knowledge.open');
  if (knowledge && !knowledge.isDestroyed()) { knowledge.show(); knowledge.focus(); return; }
  knowledge = secureWindow({ useContentSize: true, width: 860, height: 680, minWidth: 640, minHeight: 540,
    title: '课程资料与笔记 · Beta', backgroundColor: preferences?.appearance === 'dark' ? '#191919' : '#ffffff',
  });
  knowledge.on('close', event => {
    if (!quitting) {
      event.preventDefault();
      // Keep the renderer alive on hide: per-course unsaved drafts survive navigation.
      knowledge.webContents.send('desktop:event', { event: 'knowledge-close', data: null });
    }
  });
  await knowledge.loadFile(page, { hash: 'knowledge' });
}

function secureWindow(options, inactive = false) {
  const target = new BrowserWindow({ ...options, show: false, webPreferences: {
    preload: path.join(__dirname, 'preload.cjs'), nodeIntegration: false, contextIsolation: true,
    sandbox: true, webSecurity: true, spellcheck: false,
  } });
  target.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  target.webContents.on('will-navigate', event => event.preventDefault());
  target.webContents.on('will-attach-webview', event => event.preventDefault());
  target.once('ready-to-show', () => inactive ? target.showInactive() : target.show());
  return target;
}

function createWindow() {
  window = secureWindow({ width: 1280, height: 840, minWidth: 640, minHeight: 480,
    title: 'AgentScribe · 本地同声字幕', backgroundColor: '#f7f5f5',
    titleBarStyle: 'hidden', ...(process.platform === 'win32' ? { titleBarOverlay: titlebarOverlay() } : {}),
    ...(process.platform === 'darwin' ? { trafficLightPosition: { x: 16, y: 13 } } : {}),
  });
  window.loadFile(page, process.argv.includes('--components') ? { hash: 'components' } : {});
  window.on('move', () => { publish({ event: 'material', data: materialPosition() }); publish({ event: 'window-layout', data: windowLayout() }); requestMaterial(); });
  window.on('resize', () => { publish({ event: 'material', data: materialPosition() }); publish({ event: 'window-layout', data: windowLayout() }); });
  window.once('closed', () => { cancelMaterial(); clearInterval(materialRefresh); });
  materialRefresh = setInterval(requestMaterial, 30000);
  requestMaterial();
  if (process.env.AGENTSCRIBE_FRONTEND_CONTEXT) {
    const saved = JSON.parse(fs.readFileSync(process.env.AGENTSCRIBE_FRONTEND_CONTEXT, 'utf8'));
    if (saved.geometry) {
      const area = screen.getDisplayMatching(saved.geometry).workArea;
      const width = Math.min(area.width, Math.max(640, saved.geometry.width));
      const height = Math.min(area.height, Math.max(480, saved.geometry.height));
      window.setBounds({ width, height, x: Math.max(area.x, Math.min(area.x + area.width - width, saved.geometry.x)), y: Math.max(area.y, Math.min(area.y + area.height - height, saved.geometry.y)) });
    }
  }
  window.on('close', async event => {
    if (!quitting && service && !service.closed) {
      event.preventDefault();
      if (closePrompt) return;
      if (edited.size) {
        closePrompt = true;
        const result = await dialog.showMessageBox(window, { type: 'warning', title: '有未保存的修改',
          message: '名称、课程术语或笔记仍有未保存修改。', detail: '继续编辑可保留这些修改；放弃后仍会等待录音与已提交内容保存完成。',
          buttons: ['继续编辑', '放弃未保存修改并退出'], defaultId: 0, cancelId: 0,
        });
        closePrompt = false;
        if (result.response !== 1) {
          if (switching) { await service.request('frontend.cancel'); switching = false; }
          return;
        }
        edited.clear();
      }
      service.request('app.close').catch(error => publish({ event: 'notice', data: { text: error.message, error: true } }));
    }
  });
}

async function toggleOverlay() {
  if (overlay && !overlay.isDestroyed()) { overlay.close(); return false; }
  const saved = await service.request('overlay.get');
  if (!saved.bounds && platformHints.overlayBounds) saved.bounds = platformHints.overlayBounds;
  const area = screen.getDisplayMatching(saved.bounds || window.getBounds()).workArea;
  const width = Math.min(area.width, Math.max(380, saved.bounds?.width || 780));
  const height = Math.min(area.height, Math.max(160, saved.bounds?.height || 220));
  overlay = secureWindow({ width, height, minWidth: 380, minHeight: 160,
    x: Math.round(Math.max(area.x, Math.min(area.x + area.width - width, saved.bounds?.x ?? area.x + (area.width - width) / 2))),
    y: Math.round(Math.max(area.y, Math.min(area.y + area.height - height, saved.bounds?.y ?? area.y + area.height - height - 40))), frame: false, transparent: true,
    alwaysOnTop: true, skipTaskbar: true, resizable: true, title: 'AgentScribe · 悬浮字幕',
  }, true);
  const target = overlay;
  let boundsTimer;
  const saveBounds = () => {
    clearTimeout(boundsTimer);
    if (!target.isDestroyed() && !service.closed && !quitting) service.request('overlay.set', { bounds: target.getBounds() }).catch(error => publish({ event: 'notice', data: { text: error.message, error: true } }));
  };
  target.on('move', () => { clearTimeout(boundsTimer); boundsTimer = setTimeout(saveBounds, 250); });
  target.on('resize', () => { clearTimeout(boundsTimer); boundsTimer = setTimeout(saveBounds, 250); });
  target.on('close', saveBounds);
  target.on('closed', () => clearTimeout(boundsTimer));
  overlay.setAlwaysOnTop(true, 'floating');
  if (process.platform === 'darwin') overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  await overlay.loadFile(page, { hash: 'overlay' });
  overlay.on('closed', () => { overlay = null; });
  return true;
}

function checkSender(event) {
  const target = BrowserWindow.fromWebContents(event.sender);
  if (![window, overlay, knowledge].includes(target) || event.senderFrame !== event.sender.mainFrame ||
      event.senderFrame.url.split('#')[0] !== pageURL) throw new Error('拒绝未知页面的桌面请求。');
  return target;
}

ipcMain.handle('desktop:request', async (event, request) => {
  const target = checkSender(event);
  if (!request || typeof request.method !== 'string' || typeof request.params !== 'object' || !request.params || Array.isArray(request.params)) {
    throw new Error('无效的桌面请求。');
  }
  const { method, params } = request;
  if (target === overlay) {
    if (method === 'overlay.snapshot') return { state, settings: preferences, rows: overlayRows, options: await service.request('overlay.get') };
    if (method === 'overlay.resize') {
      if (!Number.isInteger(params.width) || !Number.isInteger(params.height)) throw new Error('字幕窗口尺寸无效。');
      const area=screen.getDisplayMatching(overlay.getBounds()).workArea;
      overlay.setSize(Math.min(area.width,Math.max(380,params.width)),Math.min(area.height,Math.max(160,params.height)));
      return;
    }
    if (method === 'overlay.set') return service.request('overlay.set', params);
    if (method === 'overlay.close') { overlay.close(); return; }
    throw new Error('悬浮字幕不能执行后台操作。');
  }
  if (target === knowledge) {
    const allowed = new Set(['bootstrap', 'knowledge.open', 'knowledge.command', 'knowledge.image', 'knowledge.dismiss', 'knowledge.locate', 'window.edited']);
    if (!allowed.has(method) || (method === 'window.edited' && params.owner !== 'knowledge')) throw new Error('课程窗口不能执行此操作。');
    if (method === 'knowledge.dismiss') {
      if (edited.has('knowledge')) throw new Error('请先保存或明确放弃未保存的修改。');
      knowledge.hide(); return;
    }
    if (method === 'knowledge.locate') {
      const result = await service.request('captions.page', { seconds: params.seconds });
      if (state?.state !== 'IDLE') throw new Error('录音结束后可定位课堂来源。');
      const row = result.rows.find(row => row.start <= params.seconds && row.end > params.seconds);
      window.webContents.send('desktop:event', { event: 'caption-location', data: { page: result, identifier: row?.id ?? null } });
      window.show(); window.focus(); return;
    }
  }
  if (method === 'material.get') return materialPosition();
  if (method === 'window.layout') return windowLayout();
  if (method === 'window.minimize') { window.minimize(); return; }
  if (method === 'window.edited') {
    if (!['name', 'knowledge'].includes(params.owner) || typeof params.dirty !== 'boolean') throw new Error('无效的编辑状态。');
    if (params.dirty) edited.add(params.owner); else edited.delete(params.owner);
    if (process.platform === 'darwin') window.setDocumentEdited(edited.size > 0);
    return;
  }
  if (method === 'window.close') { window.close(); return; }
  if (method === 'frontend.switch' || method === 'updates.check' && installed) {
    if (edited.size) throw new Error('请先保存或取消名称、术语及笔记编辑，再切换界面。');
    if (switching) return;
    switching = true;
    try {
      await service.request('frontend.prepare', { owner_pid: process.pid, geometry: window.getBounds(), updates: method === 'updates.check' });
      window.close();
    } catch (error) { switching = false; throw error; }
    return;
  }
  if (method === 'overlay.toggle') return toggleOverlay();
  if (method === 'knowledge.window') return openKnowledge();
  if (method === 'captions.copy') {
    const latest = state?.preview?.source || overlayRows.at(-1)?.source;
    if (latest) clipboard.writeText([latest, state?.preview ? '' : overlayRows.at(-1)?.translation].filter(Boolean).join('\n'));
    return;
  }
  if (method === 'app.help') { await shell.openExternal('https://github.com/Rand0MGG/agentscribe-local/blob/main/docs/WORKSPACE.md'); return; }
  if (method === 'app.releases') { await shell.openExternal('https://github.com/Rand0MGG/agentscribe-local/releases'); return; }
  if (method === 'library.recover') {
    if (bootstrapped || !service?.closed) throw new Error('当前后台仍在运行，请在设置中更改保存位置。');
    const result = await dialog.showOpenDialog(window, { title: '选择可用的录音保存位置', properties: ['openDirectory', 'createDirectory'] });
    if (result.canceled || !result.filePaths[0]) return { cancelled: true };
    restartService(result.filePaths[0]);
    window.webContents.reload();
    return;
  }
  if (!service || service.closed) throw new Error(fault || '本地后台未连接，请重新打开应用。');
  if (method === 'path.reveal' || method === 'path.diagnostics') {
    const destination = await service.request(method === 'path.reveal' ? 'path.recording' : 'path.diagnostics',
      method === 'path.reveal' && params.identifier !== undefined ? { identifier: params.identifier } : {});
    const error = await shell.openPath(destination);
    if (error) throw new Error(error);
    return;
  }
  if (method === 'library.migrate') {
    const result = await dialog.showOpenDialog(window, { title: '选择新的录音保存位置', properties: ['openDirectory', 'createDirectory'] });
    if (result.canceled || !result.filePaths[0]) return { cancelled: true };
    return service.request(method, { path: result.filePaths[0] });
  }
  if (method === 'models.choose') {
    if (!['asr', 'qwen_model', 'translation', 'llama_model'].includes(params.key)) throw new Error('无效的模型类别。');
    const result = await dialog.showOpenDialog(window, { title: '选择本地模型', properties: [['llama_model', 'asr'].includes(params.key) ? 'openFile' : 'openDirectory'], ...(['llama_model', 'asr'].includes(params.key) ? { filters: [{ name: params.key === 'asr' ? 'Whisper 权重' : 'GGUF 模型', extensions: [params.key === 'asr' ? 'pt' : 'gguf'] }] } : {}) });
    if (result.canceled || !result.filePaths[0]) return { cancelled: true };
    if (params.apply === false) return { path: result.filePaths[0] };
    return service.request('settings.set', { values: { [params.key]: result.filePaths[0] } });
  }
  if (method === 'recording.export') {
    const format = ['srt', 'txt', 'md'].includes(params.format) ? params.format : 'srt';
    const result = await dialog.showSaveDialog(window, {
      title: params.recovery ? '备份全部文字' : '导出定稿',
      defaultPath: `${params.recovery ? '文字恢复备份' : '录音定稿'}.${params.recovery ? 'txt' : format}`,
      filters: [{ name: '字幕与文字', extensions: [params.recovery ? 'txt' : format] }],
    });
    if (result.canceled || !result.filePath) return { cancelled: true };
    return service.request(method, { path: result.filePath, format, recovery: params.recovery === true });
  }
  if (method === 'knowledge.command' && params.operation === 'import') {
    const result = await dialog.showOpenDialog(target, { title: '选择本课程课件', properties: ['openFile'],
      filters: [{ name: '课程资料', extensions: ['pdf', 'pptx', 'docx', 'xlsx', 'txt', 'md', 'html', 'png', 'jpg', 'jpeg'] }],
    });
    if (result.canceled || !result.filePaths[0]) return { cancelled: true };
    return service.request(method, { operation: 'import', values: { path: result.filePaths[0] } });
  }
  if (!methods.has(method)) throw new Error('不支持的桌面操作。');
  const result = await service.request(method, params);
  if (method === 'frontend.ready') bootstrapped = true;
  if (method === 'bootstrap') {
    installed = result.installed;
    preferences = result.settings;
    updateWindowControls();
    requestMaterial();
    state = result.state;
    overlayRows = result.captions.rows.slice(-2);
    return { ...result, fault, interaction: platformHints };
  }
  return result;
});

if (process.env.AGENTSCRIBE_DESKTOP_PROFILE) app.setPath('userData', process.env.AGENTSCRIBE_DESKTOP_PROFILE);
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (window) { window.restore(); window.focus(); } });
  app.whenReady().then(async () => {
    if (process.platform === 'darwin' && fs.existsSync(path.join(root, 'AgentScribe.png'))) app.dock.setIcon(path.join(root, 'AgentScribe.png'));
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);
    session.defaultSession.on('will-download', event => event.preventDefault());
    const python = process.env.AGENTSCRIBE_DESKTOP_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    try {
      const result = await platformHelpers.run(python, ['-m', 'linguaflow.desktop_platform'], {
        cwd: root, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 15000, windowsHide: true,
      });
      platformHints = JSON.parse(result.stdout);
    } catch (error) { console.error('无法读取系统交互阈值：', error.message); }
    if (quitting) return;
    const args = [];
    if (process.argv.includes('--no-audio') || process.env.AGENTSCRIBE_NO_AUDIO === '1') args.push('--no-audio');
    // Explicit development/test overrides. The renderer cannot choose these paths.
    if (process.env.AGENTSCRIBE_DESKTOP_LIBRARY) args.push('--library', process.env.AGENTSCRIBE_DESKTOP_LIBRARY);
    if (process.env.AGENTSCRIBE_DESKTOP_PREFERENCES) args.push('--preferences', process.env.AGENTSCRIBE_DESKTOP_PREFERENCES);
    restartService = library => {
      const launchArgs = [...args];
      if (library) {
        const index = launchArgs.indexOf('--library');
        if (index >= 0) launchArgs.splice(index, 2);
        launchArgs.push('--library', library, '--persist-library');
      }
      fault = ''; service = new Service(python, launchArgs, { cwd: root });
    service.on('event', value => {
      if (value.event === 'state') {
        const wasClosing = state?.closing;
        if (wasClosing && !value.data.closing) switching = false;
        state = value.data;
        if (state.closing) cancelMaterial();
        else if (wasClosing) requestMaterial();
      }
      if (value.event === 'settings') {
        preferences = value.data;
        requestMaterial();
        updateWindowControls();
      }
      if (value.event === 'captions') overlayRows = value.data.rows.slice(-2);
      if (value.event === 'caption') {
        overlayRows = [...overlayRows.filter(row => row.id !== value.data.caption.id), value.data.caption]
          .filter(row => row.source).sort((a, b) => a.id - b.id).slice(-2);
      }
      publish(value);
      if (value.event === 'closed') quitAfterOwnedProcesses();
    });
    service.on('fault', message => {
      if (quitting && service.closed && service.child.exitCode === 0) return;
      fault = message; publish({ event: 'notice', data: { text: message, error: true } });
      // A failed handoff must exit so the supervisor can reopen the old UI.
      // The service's stdin EOF still runs its ordinary save/close path.
      if (process.env.AGENTSCRIBE_FRONTEND_CONTEXT && !bootstrapped) {
        if (service.child.stdin.writable) service.child.stdin.end();
        quitAfterOwnedProcesses();
      }
    });
    service.on('exit', () => { if (quitting) quitAfterOwnedProcesses(); });
    };
    restartService();
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      ...(process.platform === 'darwin' ? [{ label: 'AgentScribe', submenu: [{ role: 'about' }, { type: 'separator' }, { role: 'hide' }, { role: 'quit' }] }] : []),
      { label: '编辑', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
      { label: '窗口', submenu: [{ role: 'minimize' }, { role: 'close' }] },
    ]));
    createWindow();
  });
  app.on('before-quit', event => {
    if (quitReady) return;
    event.preventDefault();
    if (quitting) return;
    if (service && !service.closed) window?.close();
    else quitAfterOwnedProcesses();
  });
  app.on('window-all-closed', () => { if (quitting || !service || service.closed) quitAfterOwnedProcesses(); });
}
