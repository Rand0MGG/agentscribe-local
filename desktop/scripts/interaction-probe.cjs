// Real Electron -> IPC -> DesktopService -> PlaybackController -> WAV reader.
// Only media hardware (deliberately slow to load) and HTTP are offline adapters.
const { _electron: electron } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const closeWorkspace = require('./close-workspace.cjs');
const clickWhileBusy = require('./caption-click-checks.cjs');
const playbackDiagnostics = require('./playback-diagnostics.cjs');
const root = path.resolve(__dirname, '../..');
const output = path.join(root, 'output/playwright/interaction-fixes');
fs.mkdirSync(output, { recursive: true });
const fixture = fs.mkdtempSync(path.join(output, 'probe-'));
const python = process.env.AGENTSCRIBE_DESKTOP_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
execFileSync(python, ['-c', String.raw`
import sys, wave
from pathlib import Path
from dataclasses import asdict
from linguaflow.library import Library
from linguaflow.core import Settings, Caption
from scripts.test_no_audio import GUARD
root=Path(sys.argv[1])
(root/'prepared').touch()
(root/'sitecustomize.py').write_text(GUARD+'\nfrom scripts.desktop_chain_fixture import install\ninstall()\nfrom scripts.desktop_playback_fixture import install\ninstall()\n')
library=Library(root/'library');folder=library.folder('交互测试')
item=library.create(folder['id'],asdict(Settings('preview')),'字幕回听')
library.save(item,[Caption(i,i*2,i*2+2,f'Sentence {i}: context and evidence.','en',f'第 {i} 句文字。',final=True) for i in range(1,651)],'complete')
with wave.open(str(library.directory(item['id'])/'录音.wav'),'wb') as audio:
 audio.setparams((1,2,8000,0,'NONE','not compressed'));audio.writeframes(bytes(1304*8000*2))
other=library.folder('导航课程 B')
nested=library.folder('子课程',parent=library.folder('导航课程 C')['id'])
for folder,name in ((other,'跨文件夹录音 B'),(nested,'跨文件夹录音 C')):
 entry=library.create(folder['id'],asdict(Settings('preview')),name)
 library.save(entry,[Caption(1,0,2,name+' contents','en',final=True)],'complete')
broken=library.create(other['id'],asdict(Settings('preview')),'损坏导航录音')
(root/'broken-path').write_text(str(library.directory(broken['id'])/'session.json'),encoding='utf-8')
`, fixture], { cwd: root, encoding: 'utf8' });
let app;
async function main() {
 const errors=[], passed=[];
 app=await electron.launch({executablePath:require('electron'),args:[path.join(root,'desktop'),'--no-audio'],env:{...process.env,
  AGENTSCRIBE_DESKTOP_PYTHON:python,AGENTSCRIBE_DESKTOP_PROFILE:path.join(fixture,'profile'),AGENTSCRIBE_DESKTOP_LIBRARY:path.join(fixture,'library'),
  AGENTSCRIBE_DESKTOP_PREFERENCES:path.join(fixture,'prefs.ini'),AGENTSCRIBE_CHAIN_FIXTURE:fixture,AGENTSCRIBE_INTERACTION_FIXTURE:fixture,
  AGENTSCRIBE_AUDIO_GUARD_LOG:path.join(fixture,'blocked.log'),AGENTSCRIBE_LOG_DIR:path.join(fixture,'logs'),PYTHONPATH:[fixture,root,process.env.PYTHONPATH||''].join(path.delimiter)}});
 const page=await app.firstWindow();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
 await playbackDiagnostics.install(app,root);
 await page.locator('.notification').getByRole('button',{name:'收起通知'}).click();
 await page.getByRole('button',{name:'音频来源',exact:true}).click();
 await page.getByRole('menuitemradio',{name:'隔离输入',exact:true}).waitFor();
 await page.getByRole('button',{name:'保存文件夹',exact:true}).click();
 assert.equal(await page.getByRole('menuitemradio',{name:'隔离输入',exact:true}).count(),0);
 assert.equal(await page.locator('.popup').count(),1);
 await page.getByRole('button',{name:'语言设置',exact:true}).click();
 assert.equal(await page.getByRole('menu').count(),0);
 await page.getByRole('combobox',{name:'原文语言',exact:true}).click();
 await page.getByRole('option',{name:'简体中文',exact:true}).click();
 assert.equal(await page.locator('.control-popup').count(),1); // Nested select keeps its owner.
 await page.keyboard.press('Escape');assert.equal(await page.locator('.popup').count(),0);
 passed.push('Sibling menus are exclusive; nested language selector and Escape retain focus behavior');
 await require('./library-navigation-checks.cjs')(app,page,root,fixture,passed);
 const row=page.locator('.library-row').filter({has:page.getByRole('button',{name:'字幕回听',exact:true})});
 await row.hover();
 const highlight=await row.evaluate(node=>({background:getComputedStyle(node,'::before').backgroundColor,token:getComputedStyle(document.documentElement).getPropertyValue('--row-hover').trim()}));
 assert.match(highlight.background,/rgba\(/);
 await page.screenshot({path:path.join(output,'hover-light.png')});
 await row.getByRole('button',{name:'字幕回听',exact:true}).click();
 await page.locator('[data-caption="1"] .source').waitFor();
 const transcript=page.locator('.caption-scroll');
 const completeTranscript=await page.waitForFunction(()=>{
  const ids=[...document.querySelectorAll('.caption-scroll [data-caption]')].map(node=>Number(node.dataset.caption));
  return ids.length===650&&ids.every((id,index)=>id===index+1)?ids:null;
 });
 assert.deepEqual(await completeTranscript.jsonValue(),Array.from({length:650},(_,i)=>i+1));
 assert.equal(await transcript.evaluate(node=>node.scrollTop),0);
 assert.equal(await page.getByRole('button',{name:/较早的字幕|较新的字幕/}).count(),0);
 await transcript.focus();await transcript.press('End');
 await page.waitForFunction(()=>{const area=document.querySelector('.caption-scroll'),last=area.querySelector('[data-caption="650"]'),a=area.getBoundingClientRect(),r=last.getBoundingClientRect();return area.scrollHeight-area.scrollTop-area.clientHeight<3&&r.top>=a.top&&r.bottom<=a.bottom;});
 assert.equal(await transcript.locator('[data-caption]').count(),650);
 await page.screenshot({path:path.join(output,'complete-transcript-end.png')});
 await transcript.press('Home');await page.waitForFunction(()=>document.querySelector('.caption-scroll').scrollTop===0);
 await page.screenshot({path:path.join(output,'complete-transcript-start.png')});
 passed.push('650 saved captions load together in forward order at the beginning; Home/End never page or discard text');
 const target=page.locator('[data-caption="3"] .source');
 await clickWhileBusy(target);
 await page.getByRole('button',{name:'暂停回听',exact:true}).waitFor();
 await playbackDiagnostics.capture(app,page,fixture,output,'first-caption-playing');
 const media=()=>fs.readFileSync(path.join(fixture,'media.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
 assert.deepEqual(media().map(row=>[row.action,row.position]),[['seek',6000],['play',6000]]);
 await page.locator('[data-caption="3"].playing').waitFor();
 passed.push('Short source click survives a 500 ms renderer stall, waits for WAV readiness, seeks to 6 s and plays once');
 for(const selector of ['.source','.translation']) {
  await page.locator(`[data-caption="3"] ${selector}`).click({position:{x:15,y:10},delay:450});
  await pause(650);assert.equal(media().length,2);
 }
 const textBox=await target.boundingBox();
 await page.mouse.move(textBox.x+15,textBox.y+10);await page.mouse.down();
 try {await page.mouse.move(textBox.x+120,textBox.y+10,{steps:5});} finally {await page.mouse.up();}
 await pause(650);assert.equal(media().length,2);
 assert(await page.evaluate(()=>!!getSelection().toString()));
 await page.evaluate(()=>getSelection().removeAllRanges());
 await page.locator('[data-caption="5"] .source').dblclick({position:{x:15,y:10}});await pause(650);
 assert.equal(media().length,2);await page.evaluate(()=>getSelection().removeAllRanges());
 // Wheel away from the current caption; return restores reading without a seek.
 const scroll=page.locator('.caption-scroll');await scroll.hover();await page.mouse.wheel(0,1500);
 const back=page.getByRole('button',{name:'返回播放位置并恢复跟随',exact:true});await back.waitFor();
 const geometry=await back.boundingBox();assert.equal(geometry.width,40);assert.equal(geometry.height,40);
 const transport=await page.locator('.playback-group').boundingBox();assert(Math.abs(transport.y-geometry.y-geometry.height-16)<1);
 await page.screenshot({path:path.join(output,'return-caption.png')});
 await back.click();await pause(900);assert.equal(await back.count(),0);assert.equal(media().length,2);
 await scroll.hover();await page.mouse.wheel(0,900);await back.waitFor();
 const visibleTarget=await scroll.locator('.source').evaluateAll(nodes=>{
  const area=document.querySelector('.caption-scroll').getBoundingClientRect();
  return nodes.find(node=>{const r=node.getBoundingClientRect();return r.top>area.top+50&&r.bottom<area.top+250;})?.closest('[data-caption]').dataset.caption;
 });
 assert(visibleTarget);await clickWhileBusy(page.locator(`[data-caption="${visibleTarget}"] .translation`));
 await pause(900);assert.equal(await back.count(),0);assert.equal(media().at(-1).position,Number(visibleTarget)*2000);
 passed.push('Long press, drag selection and double-click do not seek; return follows without seeking; short translation click survives a busy renderer and resumes follow');
 await page.evaluate(()=>window.agentScribe.request('playback.seek',{milliseconds:1250000,play:false}));
 await page.locator('[data-caption="625"].playing').waitFor();
 assert.equal(await transcript.locator('[data-caption]').count(),650);
 await page.evaluate(()=>window.agentScribe.request('playback.seek',{milliseconds:2000,play:false}));
 await page.locator('[data-caption="1"].playing').waitFor();
 assert.equal(await transcript.locator('[data-caption]').count(),650);
 passed.push('Seeking beyond the former 200/400 boundaries and back retains every caption');
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('menuitem',{name:'查找字幕',exact:true}).click();
 await page.getByRole('textbox',{name:'搜索当前录音字幕'}).fill('Sentence 425:');
 await page.getByRole('dialog').getByRole('button').filter({hasText:'Sentence 425:'}).click();
 await page.locator('[data-caption="425"].located').waitFor();
 assert.equal(await transcript.locator('[data-caption]').count(),650);
 passed.push('Search locates saved text beyond the old page boundary without replacing the complete transcript');
 await page.getByRole('button',{name:'检查更新',exact:true}).click();
 await page.locator('.notice-progress').waitFor();
 await page.screenshot({path:path.join(output,'update-progress.png'),animations:'allow'});
 assert(await page.getByRole('button',{name:'正在检查…',exact:true}).isDisabled());
 const motion=await page.evaluate(async()=>{
  const bar=document.querySelector('.notice-progress');const r=bar.getBoundingClientRect(), frames=[],transforms=[];
  let mutations=0;const observer=new MutationObserver(records=>mutations+=records.length);observer.observe(document.querySelector('.caption-body'),{subtree:true,attributes:true,childList:true,characterData:true});
  await new Promise(resolve=>{const start=performance.now();function tick(t){frames.push(t);transforms.push(getComputedStyle(bar.firstElementChild).transform);if(t-start<1200)requestAnimationFrame(tick);else resolve();}requestAnimationFrame(tick);});observer.disconnect();
  const gaps=frames.slice(1).map((t,i)=>t-frames[i]).sort((a,b)=>a-b);
  return {width:r.width,height:r.height,frames:frames.length,p95:gaps[Math.floor(gaps.length*.95)],max:Math.max(...gaps),transforms:new Set(transforms).size,captionMutations:mutations};
 });
 assert.equal(motion.width,64);assert.equal(motion.height,4);assert(motion.transforms>10);assert.equal(motion.captionMutations,0);

 await page.getByText(/当前已是最新版本/).waitFor();
 passed.push('Real background update task uses compact animated progress and does not mutate captions');
 await page.getByRole('button',{name:'最近删除',exact:true}).click();await page.getByRole('dialog',{name:'最近删除',exact:true}).waitFor();
 await page.screenshot({path:path.join(output,'deleted-preserved.png')});
 await page.getByRole('button',{name:'关闭最近删除',exact:true}).click();
 await page.evaluate(()=>window.agentScribe.request('settings.set',{values:{appearance:'dark',reduce_motion:true}}));
 await page.locator('html[data-theme=dark]').waitFor();
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(640,480));
 await page.getByRole('button',{name:'最近删除',exact:true}).click();await page.getByRole('dialog',{name:'最近删除',exact:true}).waitFor();
 const closePoint=await page.getByRole('button',{name:'关闭最近删除',exact:true}).boundingBox();
 assert(await page.evaluate(({x,y})=>document.elementFromPoint(x,y)?.closest('button')?.getAttribute('aria-label')==='关闭最近删除',{x:closePoint.x+closePoint.width/2,y:closePoint.y+closePoint.height/2}));
 await page.screenshot({path:path.join(output,'deleted-dark-narrow.png')});
 const dialogBox=await page.getByRole('dialog',{name:'最近删除',exact:true}).boundingBox();assert(dialogBox.x>=0&&dialogBox.y>=0&&dialogBox.x+dialogBox.width<=640&&dialogBox.y+dialogBox.height<=480);
 await page.getByRole('button',{name:'关闭最近删除',exact:true}).click();
 passed.push('Existing delete dialog preserved in light mode and dark narrow window with reduced motion');
 await require('./caption-preview-checks.cjs')(app,page,passed);
 await require('./parity-checks.cjs')(app,page,root,output,passed);
 assert.deepEqual(errors,[]);assert(!fs.existsSync(path.join(fixture,'blocked.log')));
 fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({fixture,passed,highlight,motion,errors,native_audio_attempts:0},null,2));
 await closeWorkspace(app,page);app=null;console.log(JSON.stringify({passed,motion},null,2));
}
main().catch(async error=>{console.error(error);if(app){for(const page of app.windows()){await playbackDiagnostics.capture(app,page,fixture,output,'failed').catch(console.error);await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});}await app.evaluate(({app})=>app.exit(1)).catch(()=>{});}process.exitCode=1;});
