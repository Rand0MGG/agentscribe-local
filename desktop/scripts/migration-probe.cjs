// Real Electron -> IPC -> DesktopService -> PlaybackController -> WAV reader.
// Only media hardware (deliberately slow to load) and HTTP are offline adapters.
const { _electron: electron } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const closeWorkspace = require('./close-workspace.cjs');
const root = path.resolve(__dirname, '../..');
const output = path.join(root, 'output/playwright/migration-workflows');
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
 const errors=[], comparisons=[];
 app=await electron.launch({executablePath:require('electron'),args:[path.join(root,'desktop'),'--no-audio'],env:{...process.env,
  AGENTSCRIBE_DESKTOP_PYTHON:python,AGENTSCRIBE_DESKTOP_PROFILE:path.join(fixture,'profile'),AGENTSCRIBE_DESKTOP_LIBRARY:path.join(fixture,'library'),
  AGENTSCRIBE_DESKTOP_PREFERENCES:path.join(fixture,'prefs.ini'),AGENTSCRIBE_CHAIN_FIXTURE:fixture,AGENTSCRIBE_INTERACTION_FIXTURE:fixture,
  AGENTSCRIBE_AUDIO_GUARD_LOG:path.join(fixture,'blocked.log'),AGENTSCRIBE_LOG_DIR:path.join(fixture,'logs'),PYTHONPATH:[fixture,root,process.env.PYTHONPATH||''].join(path.delimiter)}});
 const page=await app.firstWindow();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));

 await page.getByRole('button',{name:'字幕回听',exact:true}).click();
 await page.locator('[data-caption="1"] .source').waitFor();
 await page.evaluate(()=>window.agentScribe.request('playback.seek',{milliseconds:6000}));
 const media=()=>fs.existsSync(path.join(fixture,'media.jsonl'))?fs.readFileSync(path.join(fixture,'media.jsonl'),'utf8').trim().split('\n').map(JSON.parse):[];
 let deadline=Date.now()+10000;
 while(!media().some(row=>row.action==='seek'&&row.position===6000)){assert(Date.now()<deadline);await pause(30);}
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('menuitem',{name:'查找字幕',exact:true}).click();
 await page.getByRole('textbox',{name:'搜索当前录音字幕'}).fill('Sentence 5:');
 await page.getByRole('dialog').getByRole('button').filter({hasText:'Sentence 5:'}).click();
 await page.locator('[data-caption="5"].located').waitFor();
 const seeks=media().filter(row=>row.action==='seek');
 comparisons.push({id:'search-position',qt_expected_position:10000,electron_position:seeks.at(-1).position,match:seeks.at(-1).position===10000});
 await page.evaluate(()=>window.agentScribe.request('settings.set',{values:{beta_features:true}}));
 await page.evaluate(()=>window.agentScribe.request('knowledge.window'));
 deadline=Date.now()+10000;
 let course;
 while(!(course=app.windows().find(win=>win.url().includes('#knowledge')))){assert(Date.now()<deadline);await pause(30);}
 await course.getByRole('checkbox',{name:'允许云端读取课件图像',exact:true}).waitFor();
 await course.locator('.knowledge-status').filter({hasText:'本机已保存'}).waitFor();
 // Display-only busy/consent fixture: never authorize a real cloud request.
 await app.evaluate(({BrowserWindow})=>{
  const win=BrowserWindow.getAllWindows().find(win=>win.webContents.getURL().includes('#knowledge'));
  win.webContents.send('desktop:event',{event:'knowledge',data:{type:'view',busy:true,
   course:{id:'audit-course',terms:[],material_images_cloud:true},manifest:{session_id:'audit-recording',notes_cloud:true},blocks:[]}});
 });
 await course.waitForFunction(()=>document.querySelector('[aria-label="允许云端读取课件图像"]').checked && !document.querySelector('[aria-label="允许云端读取课件图像"]').disabled);
 const materialDisabled=await course.getByRole('checkbox',{name:'允许云端读取课件图像',exact:true}).isDisabled();
 await course.getByRole('tab',{name:'课堂笔记',exact:true}).click();
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(win=>win.webContents.getURL().includes('#knowledge')).webContents.send('desktop:event',{event:'knowledge',data:{type:'status',busy:true}}));
 await course.waitForFunction(()=>!document.querySelector('[aria-label="允许云端处理已保存文字"]').disabled);
 const notesDisabled=await course.getByRole('checkbox',{name:'允许云端处理已保存文字',exact:true}).isDisabled();
 comparisons.push({id:'revoke-permission-while-busy',qt_expected_disabled:false,electron_material_disabled:materialDisabled,electron_notes_disabled:notesDisabled,match:!materialDisabled&&!notesDisabled});
 await course.screenshot({path:path.join(output,'busy-permission.png')});
 const menu=await app.evaluate(({Menu})=>Menu.getApplicationMenu().items.map(item=>({label:item.label,items:item.submenu?.items.map(row=>({label:row.label,role:row.role}))})));
 const menuItems=menu.flatMap(row=>row.items||[]).map(row=>row.label);
 comparisons.push({id:'native-update-menu',qt_expected:['版本与更新…','检查更新…'],electron_labels:menuItems,match:process.platform !== 'darwin' || menuItems.includes('检查更新…') && menuItems.includes('版本与更新…')});
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(win=>!win.webContents.getURL().includes('#')).webContents.send('desktop:event', {
  event:'updates',data:{stage:'available',text:'发现迁移测试更新',version:'test',notes:'本地显示测试'}}));
 await page.getByRole('button',{name:'查看更新',exact:true}).waitFor();
 await pause(5500);
 assert(await page.getByRole('button',{name:'查看更新',exact:true}).isVisible());
 await page.locator('.notification').getByRole('button',{name:'收起通知',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:'查看更新',exact:true}).count(),0);
 await app.evaluate(({BrowserWindow})=>{
  const win=BrowserWindow.getAllWindows().find(win=>!win.webContents.getURL().includes('#'));
  win.webContents.send('desktop:event',{event:'updates-reveal',data:null});
  win.webContents.send('desktop:event',{event:'updates',data:{stage:'available',text:'发现迁移测试更新',version:'test',notes:'本地显示测试'}});
 });
 await page.getByRole('button',{name:'查看更新',exact:true}).waitFor();
 await page.getByRole('button',{name:'查看更新',exact:true}).click();
 await page.getByRole('dialog',{name:'更新到 test'}).waitFor();
 await page.getByRole('dialog').getByRole('button',{name:'稍后',exact:true}).click();
 comparisons.push({id:'update-confirmation-persists-until-choice',match:true});
 // Freeze only the search debounce so an old result remains visible after a
 // real recording switch; identical caption IDs must not retarget the new file.
 await page.getByRole('button',{name:'更多操作',exact:true}).click();
 await page.getByRole('menuitem',{name:'查找字幕',exact:true}).click();
 await page.getByRole('textbox',{name:'搜索当前录音字幕'}).fill('Sentence 1:');
 await page.getByRole('dialog').getByRole('button').filter({hasText:'Sentence 1:'}).waitFor();
 await page.clock.install({time:Date.now()}); await page.clock.pauseAt(Date.now());
 await page.evaluate(async()=>{
  const data=await window.agentScribe.request('bootstrap');
  const item=data.library.sessions.find(row=>row.name==='跨文件夹录音 B');
  await window.agentScribe.request('recording.open',{identifier:item.id});
 });
 deadline=Date.now()+10000;
 while(!(await page.locator('.workspace-header').textContent()).includes('跨文件夹录音 B')){assert(Date.now()<deadline);await pause(25);}
 await page.getByRole('dialog').getByRole('button').filter({hasText:'Sentence 1:'}).dispatchEvent('click');
 deadline=Date.now()+10000;
 while(!(await page.locator('.notification').textContent()).includes('录音内容已变化')){assert(Date.now()<deadline);await pause(25);}
 await page.clock.resume(); await page.keyboard.press('Escape');
 comparisons.push({id:'stale-search-result-cannot-retarget-another-recording',match:true});
 for (const result of comparisons) assert(result.match, JSON.stringify(result));
 assert.deepEqual(errors,[]);
 assert.equal(media().filter(row=>row.action==='play').length,0);
 await closeWorkspace(app,page);app=null;
 assert(!fs.existsSync(path.join(fixture,'blocked.log')));
 fs.writeFileSync(path.join(output,'comparisons.json'),JSON.stringify({comparisons,fixture,errors,native_audio_attempts:0},null,2));
 console.log(JSON.stringify(comparisons,null,2));
}
main().catch(async error=>{console.error(error);process.exitCode=1;if(app)await app.evaluate(({app})=>app.exit(1)).catch(()=>{});});
