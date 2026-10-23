// Visual fixtures exercise production components; the real service remains --no-audio.
const { _electron: electron } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, message) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) { if (await check()) return; await pause(50); }
  throw new Error(message);
}
async function main() {
  const root = path.resolve(__dirname, '../..'), output = path.join(root, '.work/browser/ui-parity/electron');
  fs.mkdirSync(output, { recursive: true });
  const fixture = fs.mkdtempSync(path.join(output, 'fixture-'));
  const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  execFileSync(python, ['-c', `
from pathlib import Path
from dataclasses import asdict
import sys
from scripts.test_no_audio import GUARD
from linguaflow.library import Library
from linguaflow.core import Caption, Settings
root=Path(sys.argv[1]);(root/'sitecustomize.py').write_text(GUARD)
library=Library(root/'library');folder=library.folder('课程笔记 · 示例')
item=library.create(folder['id'],asdict(Settings('preview')),'理解语言与上下文 · 示例')
library.save(item,[Caption(1,0,5,'Language is more than a sequence of words. It is a way of sharing ideas.','en','语言不只是词语的排列，也是分享想法的方式。'),Caption(2,5,10,'Context helps us understand what comes next.','en','上下文帮助我们理解接下来的内容。'),Caption(3,10,14,'Each new sentence brings the meaning into focus.','en','每一句新话都让意思更加清楚。')],'complete')
`, fixture], { cwd: root });
  let app;
  const errors = [], records = [];
  try {
    app = await electron.launch({ executablePath: require('electron'), args: [path.join(root, 'desktop'), '--no-audio'], env: {
      ...process.env, AGENTSCRIBE_DESKTOP_PROFILE: path.join(fixture, 'profile'), AGENTSCRIBE_DESKTOP_LIBRARY: path.join(fixture, 'library'),
      AGENTSCRIBE_DESKTOP_PREFERENCES: path.join(fixture, 'prefs.ini'), AGENTSCRIBE_LOG_DIR: path.join(fixture, 'logs'),
      AGENTSCRIBE_AUDIO_GUARD_LOG: path.join(fixture, 'blocked.log'), PYTHONPATH: [fixture, root].join(path.delimiter),
    }, timeout: 30000 });
    const page = await app.firstWindow();
    page.on('pageerror', error => errors.push(error.message));
    await page.getByRole('button', { name: '设置', exact: true }).waitFor();
    // Only the visual bootstrap is enriched with sample devices. Capture requests
    // remain rejected by the actual Python service and the inherited import guard.
    await app.evaluate(({ BrowserWindow }, root) => {
      const { Service } = process.getBuiltinModule('module').createRequire(root + '/desktop/package.json')('./electron/service.cjs');
      const original = Service.prototype.request;
      Service.prototype.request = async function(method, params) {
        if (method === 'audio.refresh') return [];
        if (method === 'models.check') return null;
        if (method === 'models.inventory') {
          const bootstrap=await original.call(this,'bootstrap',{}), chosen=bootstrap.options.recommended;
          this.emit('event',{event:'inventory',data:{busy:false,result:[
            {id:'preview-asr',name:'Qwen3-ASR 1.7B · 示例',kind:'asr',engine:chosen.backend,path:'/preview/models/qwen',selection:chosen.asr_model,size:1024**3,deletable:false},
            {id:'preview-hy',name:'HY-MT2 1.8B Q4_K_M · 示例',kind:'translation',engine:'llama',path:'/preview/models/hy.gguf',selection:chosen.translation_model,size:1280*1024**2,deletable:false},
          ]}}); return null;
        }
        const result = await original.call(this, method, params);
        if (method === 'bootstrap') return { ...result, root:'/录音示例', no_audio: false,
          devices: [{ id: 'speaker-preview', name: '系统音频 · 扬声器（示例）', loopback: true }, { id: 'mic-preview', name: '外部输入 · 麦克风（示例）', loopback: false }], device: ['speaker-preview', true] };
        return result;
      };
    }, root);
    await page.reload();
    await page.getByRole('button', { name: '理解语言与上下文 · 示例', exact: true }).click();
    await page.getByText('Context helps us understand what comes next.', { exact: true }).waitFor();
    async function size(width, height) {
      await app.evaluate(({ BrowserWindow, screen }, size) => { const win = BrowserWindow.getAllWindows().find(w => !w.webContents.getURL().includes('#')); const area=screen.getDisplayMatching(win.getBounds()).workArea; win.setPosition(area.x,area.y,false); win.setContentSize(...size); win.show(); win.focus(); }, [width, height]);
      await page.waitForFunction(([width,height]) => innerWidth === width && innerHeight === height, [width,height], {timeout:3000}).catch(async error => { throw new Error(`Requested ${width}x${height}; got ${await page.evaluate(()=>innerWidth+'x'+innerHeight)}: ${error.message}`); });
      await pause(120);
    }
    async function settings(values) { await page.evaluate(values => window.agentScribe.request('settings.set', { values }), values); }
    async function send(event, data) { await app.evaluate(({ BrowserWindow }, value) => BrowserWindow.getAllWindows().find(w => !w.webContents.getURL().includes('#')).webContents.send('desktop:event', value), { event, data }); }
    async function shot(name, target = page, movePointer = true) {
      await pause(180);
      if(movePointer) await target.mouse.move(5, 5);
      await target.screenshot({ path: path.join(output, name + '.png'), scale: 'css', omitBackground:true });
      records.push({ name, ...await target.evaluate(() => ({ width: innerWidth, height: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth,
        dialog: (() => {const d=document.querySelector('[role=dialog]');if(!d)return null;const r=d.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})(), island: (() => { const node = document.querySelector('.control-island,.playback'); if (!node) return null; const r = node.getBoundingClientRect(); return { x:r.x,y:r.y,width:r.width,height:r.height }; })() })) });
    }
    const sizes = [[1280,797],[900,650],[640,480]];
    for (const theme of ['light','dark']) {
      await settings({ appearance: theme, reduce_motion: true });
      await until(() => page.evaluate(async theme => {
        const material = await window.agentScribe.request('material.get');
        if (material?.appearance !== theme) return false;
        const background = getComputedStyle(document.querySelector('.app')).backgroundImage;
        if (!background.includes(material.image)) return false;
        const image = new Image(); image.src = material.image; await image.decode();
        return image.width === material.width && image.height === material.height;
      }, theme), `The ${theme} wallpaper material never reached the rendered page`);
      for (const dimensions of sizes) { await size(...dimensions); await shot(`workspace-${theme}-${dimensions.join('x')}`); }
      await size(1280,797);
      await page.getByRole('button', { name: '设置', exact: true }).click();
      for (const [category,slug] of [['常规','general'],['聆听','listening'],['模型管理','models'],['字幕与延迟','captions'],['运行环境','runtime'],['使用指南','guide']]) {
        await page.getByRole('button', { name: category, exact: true }).first().click();
        for (const dimensions of sizes) { await size(...dimensions); await shot(`settings-${slug}-${theme}-${dimensions.join('x')}`); }
        if (category === '字幕与延迟') { await page.getByRole('button',{name:'显示高级参数',exact:true}).click(); await shot(`settings-advanced-${theme}-640x480`); await page.getByRole('button',{name:'收起高级参数',exact:true}).click(); }
      }
      await size(900,650);
      await page.getByRole('button', { name:'模型管理',exact:true }).click();
      await page.getByRole('button', { name:'下载模型…',exact:true }).click();
      await shot(`catalog-${theme}`);
      await page.getByRole('dialog').getByRole('button',{name:'关闭下载模型',exact:true}).click();
      await page.getByRole('combobox',{name:'语音识别模型',exact:true}).click();
      await page.getByRole('option',{name:'模型设置…',exact:true}).click();
      await shot(`model-editor-${theme}`);
      await page.getByRole('button',{name:'高级设置…',exact:true}).click();
      await shot(`model-advanced-${theme}`);
      await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
      await page.getByRole('button',{name:'返回录音',exact:false}).click();
      await page.getByRole('button',{name:'新建文件夹',exact:true}).click(); await shot(`name-dialog-${theme}`);
      await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
      await page.getByRole('button',{name:'最近删除',exact:true}).click(); await shot(`deleted-${theme}`);
      await page.getByRole('dialog').getByRole('button',{name:'关闭最近删除',exact:true}).click();
      await page.getByRole('button',{name:'更多操作',exact:true}).click(); await shot(`menu-${theme}`); await page.keyboard.press('Escape');
      await page.getByRole('button',{name:'新录音',exact:false}).first().click(); await shot(`new-${theme}`);
      await page.getByRole('button',{name:'语言设置',exact:true}).click(); await shot(`language-${theme}`); await page.keyboard.press('Escape');
      await page.getByRole('button',{name:'理解语言与上下文 · 示例',exact:true}).click();
      await page.getByText('Context helps us understand what comes next.',{exact:true}).waitFor();
      await until(() => page.evaluate(async()=>!!(await window.agentScribe.request('bootstrap')).state.item), 'Recording did not finish opening');
      const original = (await page.evaluate(() => window.agentScribe.request('bootstrap'))).state;
      await send('state',{...original,state:'LISTENING'}); await send('clock',{seconds:754}); await send('level',.024);
      for (const dimensions of sizes) { await size(...dimensions); await shot(`recording-${theme}-${dimensions.join('x')}`); }
      await send('state',{...original,state:'PAUSED'}); await send('level',0); await shot(`paused-${theme}`);
      await send('state',{...original,has_audio:true}); await send('playback',{position:7000,duration:94000,state:'StoppedState'});
      for (const dimensions of sizes) { await size(...dimensions); await shot(`playback-${theme}-${dimensions.join('x')}`); }
      await page.getByRole('button',{name:'回放音量',exact:true}).click(); await shot(`volume-${theme}`);
      await send('state',original);
      await size(1280,797);
      await settings({ beta_features:true });
      const opened = theme === 'light' ? app.waitForEvent('window') : null; await page.getByRole('button',{name:'课程资料与笔记 · Beta',exact:true}).click();
      const knowledge = theme === 'light' ? await opened : app.windows().find(p => p.url().endsWith('#knowledge'));
      await knowledge.getByText(/本机已保存.*视觉读取/).waitFor();
      for (const [tab,slug] of [['课件','materials'],['识别术语','terms'],['课堂笔记','notes']]) { await knowledge.getByRole('tab',{name:tab,exact:true}).click(); await shot(`knowledge-${slug}-${theme}`,knowledge); }
      await knowledge.keyboard.press('Escape');
      await settings({ beta_features:false });
      const overlayOpened=app.waitForEvent('window');
      await page.getByRole('button',{name:'悬浮字幕',exact:true}).click();
      const overlay=await overlayOpened;
      await overlay.getByText('Each new sentence brings the meaning into focus.',{exact:true}).waitFor();
      await overlay.mouse.move(40,30);
      await shot(`overlay-controls-${theme}`,overlay);
      await overlay.mouse.move(-20,-20); await pause(450);
      await shot(`overlay-reading-${theme}`,overlay,false);
      await overlay.mouse.move(40,30);
      await overlay.getByRole('button',{name:'关闭悬浮字幕',exact:true}).click();
    }
    await settings({reduce_motion:false});
    await page.getByRole('button',{name:'设置',exact:true}).click();
    const workspaceFade = await page.locator('.page-stack').evaluate(node=>node.getAnimations().map(a=>a.effect.getTiming()));
    await page.getByRole('button',{name:'聆听',exact:true}).click();
    const settingsFade = await page.locator('.settings-page-body').evaluate(node=>node.getAnimations().map(a=>a.effect.getTiming()));
    assert(workspaceFade.some(t=>t.duration===150)); assert(settingsFade.some(t=>t.duration===150));
    console.log(`Captured ${records.length} page states; checking animation frames.`);
    fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify({fixture,records,errors,audioAttempts:0,motion:'pending'},null,2));
    // Native renderer traces of the same components used by the workspace.
    await app.evaluate(async ({ BrowserWindow }, root) => {
      const win=BrowserWindow.getAllWindows().find(w => !w.webContents.getURL().includes('#'));
      await win.loadFile(root + '/desktop/dist/index.html', {hash:'components'});
      win.webContents.reload();
    },root);
    await page.getByRole('button',{name:'切换模拟录音状态',exact:true}).waitFor();
    const traces = {};
    async function trace(selector,label,reverseAt = 0) {
      return await page.evaluate(async ({selector,label,reverseAt}) => {
        const node = document.querySelector(selector), button = [...document.querySelectorAll('button')].find(b => b.textContent === label || b.getAttribute('aria-label') === label);
        const rows = [], began = performance.now(); let reversed = false;
        function take(now) { const r=node.getBoundingClientRect(); rows.push({t:now-began,width:r.width,height:r.height,bottom:r.bottom,x:r.x,transform:getComputedStyle(node).transform,opacity:Number(getComputedStyle(node).opacity)}); }
        take(began); button.click();
        await new Promise(resolve => { function frame(now) { take(now); if(reverseAt && !reversed && now-began >= reverseAt) { reversed=true;button.click(); } if(now-began<650) requestAnimationFrame(frame); else resolve(); } requestAnimationFrame(frame); });
        return rows;
      },{selector,label,reverseAt});
    }
    console.log('Component route ready.');
    traces.islandExpand = await trace('.control-island','切换模拟录音状态');
    traces.islandCollapse = await trace('.control-island','切换模拟录音状态');
    traces.islandInterrupted = await trace('.control-island','切换模拟录音状态',100);
    fs.writeFileSync(path.join(output,'motion-partial.json'),JSON.stringify(traces,null,2));
    for (const [name,start,end] of [['islandExpand',58,84],['islandCollapse',84,58],['islandInterrupted',58,58]]) {
      const rows=traces[name]; assert.equal(rows[0].height,start);assert.equal(rows.at(-1).height,end);
      assert(rows.some(r=>r.height>58.5 && r.height<83.5),name+' missing intermediate frames');
      assert(Math.max(...rows.map(r=>r.bottom))-Math.min(...rows.map(r=>r.bottom))<1,name+' lost bottom anchor');
    }
    for(const name of ['islandExpand','islandCollapse']) { const end=traces[name].at(-1).height; const finish=traces[name].find(r=>r.t>30&&r.height===end).t; assert(finish>=250&&finish<=360,name+' duration '+finish); }
    const seek=await page.getByRole('slider',{name:'播放位置',exact:true}).boundingBox();
    traces.volumeExpand = await trace('.playback-volume','回放音量');
    assert.equal(traces.volumeExpand.at(-1).height,170);
    const volumeFinish=traces.volumeExpand.find(r=>r.height===170).t; assert(volumeFinish>=170&&volumeFinish<=280,'Volume duration '+volumeFinish);
    assert(traces.volumeExpand.some(r=>r.height>58&&r.height<170));
    assert.deepEqual(await page.getByRole('slider',{name:'播放位置',exact:true}).boundingBox(),seek);
    traces.volumeInterrupted = await trace('.playback-volume','回放音量',70);
    assert.equal(traces.volumeInterrupted.at(-1).height,170);
    traces.toggle = await trace('.switch-thumb','示例开关');
    assert(new Set(traces.toggle.map(r=>r.transform)).size>3,'Toggle jumped instead of animating');
    await page.evaluate(()=>document.documentElement.dataset.reducedMotion='true');
    traces.reducedIsland=await trace('.control-island','切换模拟录音状态');
    assert(traces.reducedIsland.slice(1).every(r=>r.height===84),'Reduced motion did not settle immediately');
    await page.evaluate(()=>document.documentElement.dataset.reducedMotion='false');
    await page.getByRole('button',{name:'编辑示例名称',exact:true}).click();
    const dialogTiming=await page.getByRole('dialog').evaluate(node=>node.getAnimations().map(a=>a.effect.getTiming()));
    assert(dialogTiming.some(t=>t.duration===140),'Dialog fade duration changed');
    await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
    await page.getByRole('button',{name:'追加示例文字',exact:true}).click();
    await pause(350);
    assert.equal(await page.locator('[aria-label="动态字幕示例"]>span>span').innerText(),'');
    await page.getByRole('button',{name:'修订示例文字',exact:true}).click();
    assert.equal(await page.locator('[aria-label="动态字幕示例"]').innerText(),'修订立即替换。');
    fs.writeFileSync(path.join(output,'motion.json'),JSON.stringify({traces,dialogTiming,workspaceFade,settingsFade},null,2));
    assert.deepEqual(errors,[]);
    assert(records.every(record => !record.overflow),'A page overflowed horizontally');
    await page.evaluate(()=>window.agentScribe.request('window.close'));
    await app.close(); app=null;
    assert(!fs.existsSync(path.join(fixture,'blocked.log')),'Attempted native audio access');
    fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify({fixture,records,errors,audioAttempts:0},null,2));
    console.log(`Captured ${records.length} production UI states with isolated sample data.`);
  } finally { if(app) await app.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
