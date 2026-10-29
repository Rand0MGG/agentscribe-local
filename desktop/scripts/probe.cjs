// Isolated native-window probe. All Python children inherit the audio import guard.
const { _electron: electron } = require('playwright');
const { execFileSync } = require('node:child_process');
const { mkdtempSync, mkdirSync, existsSync, readFileSync, writeFileSync, appendFileSync } = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const closeWorkspace = require('./close-workspace.cjs');

async function main() {
  const root = path.resolve(__dirname, '../..');
  const appRoot = process.env.AGENTSCRIBE_PROBE_RESOURCES || root;
  const evidence = path.resolve(process.env.AGENTSCRIBE_PROBE_EVIDENCE || path.join(root, 'output/playwright/electron'));
  mkdirSync(evidence, { recursive: true });
  const fixture = mkdtempSync(path.join(evidence, 'probe-'));
  const python = process.env.AGENTSCRIBE_DESKTOP_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  execFileSync(python, ['-c', `
import sys
from pathlib import Path
from dataclasses import asdict
from linguaflow.library import Library
from linguaflow.core import Caption, Settings
from scripts.test_no_audio import GUARD
root = Path(sys.argv[1])
(root / 'sitecustomize.py').write_text(GUARD + chr(10) + 'from scripts.desktop_chain_fixture import install' + chr(10) + 'install()' + chr(10), encoding='utf-8')
library = Library(root / 'library')
folder = library.folder('课程笔记 · 示例')
item = library.create(folder['id'], asdict(Settings('preview')), '理解语言与上下文 · 示例')
library.save(item, [
 Caption(1,0,5,'Language is more than a sequence of words. It is a way of sharing ideas.','en','语言不只是词语的排列，也是分享想法的方式。'),
 Caption(2,5,10,'Context helps us understand what comes next.','en','上下文帮助我们理解接下来的内容。'),
 Caption(3,10,14,'Each new sentence brings the meaning into focus.','en','每一句新话都让意思更加清楚。')
], 'complete')
`, fixture], { cwd: root, encoding: 'utf8' });
  const errors = [];
  let desktop;
  try {
    desktop = await electron.launch({ executablePath: process.env.AGENTSCRIBE_PROBE_ELECTRON || require('electron'), args: [path.join(appRoot, 'desktop'), '--no-audio'],
      env: { ...process.env, AGENTSCRIBE_DESKTOP_PROFILE: path.join(fixture, 'profile'), AGENTSCRIBE_DESKTOP_LIBRARY: path.join(fixture, 'library'),
        AGENTSCRIBE_DESKTOP_PREFERENCES: path.join(fixture, 'prefs.ini'),
        AGENTSCRIBE_LOG_DIR: path.join(fixture, 'logs'), AGENTSCRIBE_CHAIN_FIXTURE: fixture,
        AGENTSCRIBE_AUDIO_GUARD_LOG: path.join(fixture, 'blocked.log'),
        PYTHONPATH: [fixture, root, process.env.PYTHONPATH || ''].join(path.delimiter),
      }, timeout: 20000,
    });
    desktop.process().stderr.on('data', chunk => appendFileSync(path.join(fixture, 'electron-stderr.log'), chunk));
    const page = await desktop.firstWindow();
    page.on('pageerror', error => errors.push(error.message));
    await page.getByRole('button', { name: '新录音', exact: false }).first().waitFor();
    await require('./titlebar-checks.cjs')(desktop, page);
    assert.equal(await page.getByRole('button', { name: '悬浮字幕', exact: true }).count(),0);
    assert.equal(await page.getByRole('button', { name: '导出定稿', exact: true }).count(),0);
    assert(await page.getByRole('button', { name: '开始聆听', exact: true }).isDisabled());
    await page.locator('.recording-title').click();
    await page.getByRole('textbox', { name: '录音名称', exact: true }).fill('待录音 · 不创建文件');
    await page.getByRole('textbox', { name: '录音名称', exact: true }).press('Enter');
    await page.getByRole('button', { name: '待录音 · 不创建文件', exact: true }).waitFor();
    assert.equal(await page.evaluate(async () => (await window.agentScribe.request('bootstrap')).library.sessions.length), 1);
    await page.screenshot({ path: path.join(evidence, 'workspace-pending.png') });
    writeFileSync(path.join(fixture, 'initial.txt'), await page.locator('body').innerText());
    await page.getByRole('button', { name: '理解语言与上下文 · 示例', exact: true }).click();
    await page.getByText('Context helps us understand what comes next.', { exact: true }).waitFor();
    const exported=path.join(fixture,'menu-export.srt');
    await desktop.evaluate(({dialog},filePath)=>{globalThis.originalSaveDialog=dialog.showSaveDialog;dialog.showSaveDialog=async()=>({canceled:false,filePath});},exported);
    try {
      await page.getByRole('button',{name:'更多操作',exact:true}).click();
      assert(await page.getByRole('menuitem',{name:'导出定稿',exact:true}).isEnabled());
      await page.getByRole('menuitem',{name:'导出定稿',exact:true}).click();
      await page.locator('.notification').filter({hasText:'导出完成'}).waitFor();
      assert(existsSync(exported));assert(readFileSync(exported,'utf8').includes('Context helps us understand what comes next.'));
    } finally {await desktop.evaluate(({dialog})=>{dialog.showSaveDialog=globalThis.originalSaveDialog;});}
    assert(await page.getByRole('button', { name: '开始聆听', exact: true }).isDisabled()); // Qt keeps idle controls for text-only recordings.
    await page.screenshot({ path: path.join(evidence, 'workspace-light.png'), scale: 'css' });
    await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setContentSize(900, 650));
    await page.screenshot({ path: path.join(evidence, 'workspace-light-900x650.png'), scale: 'css' });
    await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setContentSize(1280, 760));
    await page.getByRole('button', { name: '更多操作', exact: true }).click();
    await page.getByRole('menuitem', { name: '查找字幕', exact: true }).click();
    await page.getByRole('textbox', { name: '搜索当前录音字幕' }).fill('上下文');
    await page.getByRole('dialog').getByRole('button').filter({ hasText: 'Context helps' }).click();
    await page.locator('.caption.located').waitFor();
    await page.getByRole('button', { name: '新建文件夹', exact: true }).click();
    await page.getByRole('textbox', { name: '名称', exact: true }).fill('中文 新文件夹');
    await page.getByRole('dialog').getByRole('button', { name: '保存', exact: true }).click();
    await page.getByRole('button', { name: '中文 新文件夹', exact: true }).waitFor();
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await page.getByRole('combobox', { name: '外观', exact: true }).click();
    await page.getByRole('option', { name: '深色', exact: true }).click();
    await page.locator('html[data-theme=dark]').waitFor();
    const originalModel = await page.evaluate(async () => (await window.agentScribe.request('bootstrap')).settings.backend);
    await page.getByRole('button', { name: '模型管理', exact: true }).click();
    await page.getByRole('combobox', { name: '语音识别模型', exact: true }).click();
    await page.getByRole('option', { name: '模型设置…', exact: true }).click();
    await page.getByRole('button', { name: '高级设置…', exact: true }).click();
    await page.getByRole('combobox', { name: '对应引擎', exact: true }).click();
    await page.getByRole('option', { name: 'WhisperLiveKit · Whisper / AlignAtt', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
    assert.equal(await page.evaluate(async () => (await window.agentScribe.request('bootstrap')).settings.backend), originalModel);
    await page.getByRole('button', { name: '刷新', exact: true }).waitFor();
    // Inventory can contain alignment weights and engines from another platform.
    // Inject only display records; never touch or download actual model files.
    const initialSettings = await page.evaluate(async () => (await window.agentScribe.request('bootstrap')).settings);
    await page.evaluate(() => window.agentScribe.request('settings.set', { values: { compute: 'CPU（通用）' } }));
    await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.send('desktop:event', {
      event: 'inventory', data: { busy: false, result: [
        { id: 'probe-alignment', name: '仅对齐示例', kind: 'alignment', engine: null, path: '/example/alignment', size: 1024, deletable: true },
        { id: 'probe-unsupported', name: '平台不支持示例', kind: 'asr', engine: 'unsupported-test-engine', path: '/example/unsupported', size: 1024, deletable: false },
        ...(process.platform === 'darwin' ? [{ id: 'probe-mlx', name: 'MLX 设备示例', kind: 'asr', engine: 'qwen3-mlx', path: '/example/mlx', size: 1024, deletable: false }] : []),
      ] },
    }));
    const alignment = page.getByRole('option').filter({hasText:'仅对齐示例'});
    await alignment.dblclick();
    assert.equal(await page.getByRole('dialog').count(),0);
    await page.getByText('此模型用于时间戳对齐，当前识别流程不加载它，不能选作识别模型。',{exact:true}).waitFor();
    assert(await page.getByRole('button',{name:'删除模型',exact:true}).isEnabled());
    await page.getByRole('option').filter({hasText:'平台不支持示例'}).dblclick();
    assert.equal(await page.getByRole('dialog').count(),0);
    await page.getByText('这个识别模型的引擎不适用于当前平台。',{exact:true}).waitFor();
    if (process.platform === 'darwin') {
      await page.getByRole('option').filter({hasText:'MLX 设备示例'}).dblclick();
      await page.getByRole('button', { name: '高级设置…', exact: true }).click();
      assert.match(await page.getByRole('combobox', { name: '计算设备', exact: true }).innerText(), /Apple GPU · Metal \/ MLX/);
      await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
      assert.equal(await page.evaluate(async () => (await window.agentScribe.request('bootstrap')).settings.compute), 'CPU（通用）');
    }
    await page.evaluate(values => window.agentScribe.request('settings.set', { values }), { compute: initialSettings.compute });
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.getByRole('button', { name: '下载模型…', exact: true }).click();
    await page.screenshot({ path: path.join(evidence, 'model-catalog-dark.png'), scale: 'css' });
    await page.getByRole('dialog').getByRole('button', { name: '关闭下载模型', exact: true }).click();
    // Real renderer -> preload -> host -> Python validator -> Preparation -> supervised subprocess.
    const beforeBundle=await page.evaluate(()=>window.agentScribe.request('bootstrap'));
    await page.getByRole('button',{name:'下载模型…',exact:true}).click();
    await page.getByRole('button',{name:'下载并使用推荐组合',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.waitForFunction(() => document.querySelector('.preparation')?.textContent.includes('准备完成'));
    const bundle = readFileSync(path.join(fixture, 'commands.jsonl'), 'utf8').trim().split('\n').map(line => JSON.parse(line)).filter(args => args[0] === 'linguaflow.recommended_prepare' && !args.includes('--check'));
    assert.equal(bundle.length, 1); assert(!bundle[0].includes('--only'));
    const selection = JSON.parse(bundle[0][bundle[0].indexOf('--selection') + 1]);
    assert.equal(selection.backend, beforeBundle.options.recommended.backend);
    assert.equal(selection.translation_device, beforeBundle.settings.translation_device);
    const afterBundle=await page.evaluate(()=>window.agentScribe.request('bootstrap'));
    assert.equal(afterBundle.settings.backend,beforeBundle.options.recommended.backend);
    await page.evaluate(values=>window.agentScribe.request('settings.set',{values}),beforeBundle.settings);

    await page.getByRole('button', { name: '常规', exact: true }).click();
    await page.getByRole('switch', { name: '课程助手 Beta', exact: true }).click();
    await page.screenshot({ path: path.join(evidence, 'settings-dark.png') });
    await page.getByRole('button', { name: '返回录音', exact: false }).click();
    async function waitKnowledgeVisible(visible) {
      const deadline = Date.now() + 10000;
      while (Date.now() < deadline) {
        const actual = await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(win => win.webContents.getURL().endsWith('#knowledge'))?.isVisible());
        if (actual === visible) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error(`Course window native visibility did not become ${visible}`);
    }
    const knowledgeOpened = desktop.waitForEvent('window');
    await page.getByRole('button', { name: '课程资料与笔记 · Beta', exact: true }).click();
    const knowledge = await knowledgeOpened;
    knowledge.on('pageerror', error => errors.push(error.message));
    await knowledge.getByText(/本机已保存.*视觉读取/).waitFor();
    assert(await knowledge.evaluate(() => window.agentScribe.request('recording.new').then(() => false, () => true)));
    await knowledge.getByRole('tab', { name: '识别术语', exact: true }).click();
    await knowledge.getByRole('button', { name: '添加术语', exact: true }).click();
    await knowledge.getByRole('textbox', { name: '名称', exact: true }).fill('上下文 · Context');
    await knowledge.getByRole('dialog').getByRole('button', { name: '保存', exact: true }).click();
    await knowledge.getByRole('textbox', { name: '别名 1', exact: true }).pressSequentially('ML; DL');
    assert.equal(await knowledge.getByRole('textbox', { name: '别名 1', exact: true }).inputValue(), 'ML; DL');
    // A modeless reading window must not block the main recording workspace.
    await page.getByRole('button', { name: '更多操作', exact: true }).click();
    await page.keyboard.press('Escape');
    await knowledge.keyboard.press('Escape');
    await knowledge.getByText('术语有未保存修改，请先保存，或明确放弃修改后关闭。', { exact: true }).waitFor();
    await knowledge.getByRole('button', { name: '保存审核结果', exact: true }).click();
    await knowledge.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent === '保存审核结果' && button.disabled));
    await knowledge.screenshot({ path: path.join(evidence, 'knowledge-dark.png'), scale: 'css' });
    await knowledge.keyboard.press('Escape');
    await waitKnowledgeVisible(false);
    await page.getByRole('button', { name: '课程资料与笔记 · Beta', exact: true }).click();
    await waitKnowledgeVisible(true);
    assert.equal(await knowledge.getByRole('textbox', { name: '术语 1', exact: true }).inputValue(), '上下文 · Context');
    await knowledge.keyboard.press('Escape');
    await waitKnowledgeVisible(false);
    await page.screenshot({ path: path.join(evidence, 'workspace-dark.png') });
    const overlayOpened = desktop.waitForEvent('window');
    await page.getByRole('button', { name: '更多操作', exact: true }).click();
    await page.getByRole('menuitem', { name: '悬浮字幕', exact: true }).click();
    const overlay = await overlayOpened;
    overlay.on('pageerror', error => errors.push(error.message));
    assert.equal(await overlay.evaluate(() => typeof window.require), 'undefined');
    assert(await overlay.evaluate(() => window.agentScribe.request('recording.new').then(() => false, () => true)));
    await overlay.getByText('Each new sentence brings the meaning into focus.', { exact: true }).waitFor();
    assert.equal(await overlay.getByText('Context helps us understand what comes next.',{exact:true}).count(),0);
    await overlay.mouse.move(40,30);
    await overlay.getByRole('slider',{name:'字幕字号',exact:true}).press('ArrowRight');
    assert.equal(await overlay.evaluate(async()=> (await window.agentScribe.request('overlay.snapshot')).options.font),24);
    assert(await overlay.evaluate(()=>window.agentScribe.request('overlay.resize',{width:'invalid',height:100}).then(()=>false,()=>true)));
    await overlay.evaluate(()=>window.agentScribe.request('overlay.resize',{width:600,height:260}));
    await overlay.waitForFunction(()=>innerWidth===600&&innerHeight===260);
    const grip=await overlay.getByRole('separator',{name:'调整字幕窗口大小',exact:true}).boundingBox();
    await overlay.mouse.move(grip.x+10,grip.y+10); await overlay.mouse.down();
    await overlay.mouse.move(grip.x+50,grip.y+30,{steps:4}); await overlay.mouse.up();
    await overlay.waitForFunction(()=>innerWidth===640&&innerHeight===280);
    // Synthetic Playwright moves do not relocate the OS pointer. After a
    // native resize macOS can send its real position back into this window,
    // legitimately keeping controls visible. Isolate this owned test window
    // from that pointer before checking the leave behaviour.
    await desktop.evaluate(({ BrowserWindow, screen }) => {
      const target = BrowserWindow.getAllWindows().find(window => window.webContents.getURL().endsWith('#overlay'));
      const bounds = target.getBounds(), area = screen.getDisplayMatching(bounds).workArea;
      const cursor = screen.getCursorScreenPoint();
      const positions = [[area.x, area.y], [area.x + area.width - bounds.width, area.y],
        [area.x, area.y + area.height - bounds.height],
        [area.x + area.width - bounds.width, area.y + area.height - bounds.height]];
      const position = positions.find(([x, y]) => cursor.x < x - 40 || cursor.x > x + bounds.width + 40 ||
        cursor.y < y - 40 || cursor.y > y + bounds.height + 40);
      if (!position) throw new Error('No isolated position for the overlay pointer test');
      target.setPosition(...position);
    });
    await overlay.mouse.move(40,30);
    await overlay.mouse.move(-20,-20);
    await overlay.getByRole('button',{name:'关闭悬浮字幕',exact:true}).waitFor({state:'hidden'});
    await overlay.mouse.move(40,30);
    await overlay.screenshot({ path: path.join(evidence, 'overlay-dark.png') });
    const overlayClosed = overlay.waitForEvent('close');
    await overlay.getByRole('button', { name: '关闭悬浮字幕', exact: true }).click();
    await overlayClosed;
    await desktop.evaluate(({ BrowserWindow }) => { const win = BrowserWindow.getAllWindows().find(win => !win.webContents.getURL().includes('#')); win.setSize(640, 480); });
    await page.screenshot({ path: path.join(evidence, 'workspace-640.png') });
    const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    assert.equal(horizontalOverflow, false);
    await desktop.evaluate(({ BrowserWindow }, file) => {
      const target = BrowserWindow.getAllWindows().find(win => !win.webContents.getURL().includes('#'));
      target.setSize(1000, 800);
      return target.loadFile(file, { hash: 'components' });
    }, path.join(appRoot, 'desktop/dist/index.html'));
    await page.reload(); // A hash-only load preserves the existing React root.
    await desktop.evaluate(({ BrowserWindow }) => { const target = BrowserWindow.getAllWindows().find(win => win.webContents.getURL().endsWith('#components')); target.show(); target.focus(); });
    await page.evaluate(() => {
      window.probeFocusEvents = [];
      for (const type of ['focusin', 'keydown', 'pointermove']) document.addEventListener(type, event => {
        window.probeFocusEvents.push({ type, key: event.key, target: event.target.textContent?.slice(0, 90), at: performance.now() });
      }, true);
    });
    const choice = page.getByRole('combobox', { name: '示例选项', exact: true });
    await choice.click();
    await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'option');
    await page.keyboard.press('ArrowDown');
    await page.waitForFunction(() => document.activeElement?.textContent.includes('2 ·'));
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('[aria-label="示例选项"]').textContent.includes('2 ·'));
    assert.match(await choice.innerText(), /2 ·/);
    await choice.click();
    await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'option');
    await page.keyboard.press('ArrowDown');
    await page.waitForFunction(() => document.activeElement?.textContent.includes('4 ·'));
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('[aria-label="示例选项"]').textContent.includes('4 ·'));
    assert.match(await choice.innerText(), /4 ·/); // Skip disabled third option.
    await choice.click();
    await page.keyboard.press('Escape');
    await page.waitForFunction(()=>document.activeElement===document.querySelector('[aria-label="示例选项"]'),{},{timeout:1000});
    assert(await choice.evaluate(element => element === document.activeElement));
    const edit = page.getByRole('button', { name: '编辑示例名称', exact: true });
    await edit.click();
    const input = page.getByRole('textbox', { name: '名称', exact: true });
    await input.dispatchEvent('compositionstart', { data: '中' });
    await page.keyboard.press('Escape');
    assert(await input.isVisible());
    await input.dispatchEvent('compositionend', { data: '中文' });
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    await page.waitForFunction(() => document.activeElement?.textContent === '编辑示例名称');
    assert(await edit.evaluate(element => element === document.activeElement));
    const slider = page.getByRole('slider', { name: '示例音量', exact: true });
    await slider.focus();
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(() => document.querySelector('[role="slider"][aria-label="示例音量"]')?.getAttribute('aria-valuenow') === '101');
    assert.equal(await slider.getAttribute('aria-valuenow'), '101');
    await page.getByRole('button', { name: '追加示例文字', exact: true }).click();
    assert.equal(await page.getByLabel('动态字幕示例').textContent(), '上下文 é 👩‍💻 ');
    await page.getByRole('button', { name: '追加示例文字', exact: true }).click();
    await page.getByRole('button', { name: '修订示例文字', exact: true }).click();
    assert.equal(await page.getByLabel('动态字幕示例').textContent(), '修订立即替换。');
    const seek = page.getByRole('slider', { name: '播放位置', exact: true });
    // Compare rendered device pixels, not DOM floating-point roundoff at 150%.
    const before = await seek.evaluate(element => ({ width: Math.round(element.getBoundingClientRect().width * devicePixelRatio), y: Math.round((element.getBoundingClientRect().top + window.scrollY) * devicePixelRatio) }));
    await page.getByRole('button', { name: '回放音量', exact: true }).click();
    const gain = page.getByRole('slider', { name: '回放音量百分比', exact: true });
    await gain.waitFor();
    await gain.focus(); await page.keyboard.press('ArrowUp');
    await page.waitForFunction(() => document.querySelector('[role="slider"][aria-label="回放音量百分比"]')?.getAttribute('aria-valuenow') === '102');
    const after = await seek.evaluate(element => ({ width: Math.round(element.getBoundingClientRect().width * devicePixelRatio), y: Math.round((element.getBoundingClientRect().top + window.scrollY) * devicePixelRatio) }));
    assert.equal(after.width, before.width); assert.equal(after.y, before.y);
    await page.screenshot({ path: path.join(evidence, 'playback-volume.png'), scale: 'css' });
    await page.screenshot({ path: path.join(evidence, 'components-light.png') });
    assert.deepEqual(errors, []);
    await closeWorkspace(desktop, page);
    desktop = null;
    assert(!existsSync(path.join(fixture, 'blocked.log')), 'Native audio access was attempted');
    writeFileSync(path.join(evidence, 'result.json'), JSON.stringify({ passed: true, fixture, errors, native_audio_attempts: 0 }, null, 2));
    console.log('Electron workspace, library, search, IME, keyboard/focus, themes, restricted overlay and graceful shutdown passed; no native audio access.');
  } catch (error) {
    console.error(error);
    if (desktop) {
      const windows = desktop.windows();
      for (let index = 0; index < windows.length; index++) {
        await windows[index].screenshot({ path: path.join(evidence, `failure-${index}.png`), timeout: 2000 }).catch(() => {});
        writeFileSync(path.join(evidence, `failure-${index}.txt`), await windows[index].locator('body').innerText().catch(() => 'Window unavailable'));
        writeFileSync(path.join(evidence, `failure-${index}-focus.txt`), await windows[index].evaluate(() => document.activeElement?.outerHTML || '').catch(() => 'Window unavailable'));
        writeFileSync(path.join(evidence, `failure-${index}-events.json`), await windows[index].evaluate(() => JSON.stringify(window.probeFocusEvents || [])).catch(() => '[]'));
      }
    }
    throw error;
  } finally {
    if (desktop) await desktop.close();
    if (existsSync(path.join(fixture, 'blocked.log'))) console.error(readFileSync(path.join(fixture, 'blocked.log'), 'utf8'));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
