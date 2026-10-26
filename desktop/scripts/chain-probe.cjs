// Native UI/IPC/service/shared-backend regressions. Only external execution is isolated.
const { _electron: electron } = require('playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const evidence = path.join(root, 'output/playwright/parity-fixed');
fs.mkdirSync(evidence, {recursive:true});
const fixture = fs.mkdtempSync(path.join(evidence, 'chain-'));
const python = process.env.AGENTSCRIBE_DESKTOP_PYTHON || path.join(root,'.venv',process.platform === 'win32' ? 'Scripts/python.exe':'bin/python');
const pause = ms => new Promise(resolve => setTimeout(resolve,ms));
async function until(test, label) { const deadline=Date.now()+15000; while(Date.now()<deadline) { if(await test()) return; await pause(50); } throw new Error('Timed out: '+label); }
async function closeWorkspace(application,page) {
 const child=application.process(),closed=application.waitForEvent('close',{timeout:15000});
 // A successful close may destroy the renderer before its IPC receipt arrives.
 // Accept only that transport outcome, then require an actual clean process exit.
 const receipt=page.evaluate(()=>window.agentScribe.request('window.close')).catch(error=>{
  if(!error.message.includes('Target page, context or browser has been closed'))throw error;
 });
 await Promise.all([closed,receipt]);
 await until(()=>child.exitCode!==null||child.signalCode!==null,'Electron process exit');
 assert(page.isClosed());assert.equal(child.exitCode,0);assert.equal(child.signalCode,null);
}
execFileSync(python, ['-c', String.raw`
import sys, wave
from pathlib import Path
from dataclasses import asdict
from linguaflow.library import Library
from linguaflow.core import Caption, Settings
from scripts.test_no_audio import GUARD
root=Path(sys.argv[1])
(root/'sitecustomize.py').write_text(GUARD+'\nfrom scripts.desktop_chain_fixture import install\ninstall()\n')
cache=root/'hf'/'hub'/'models--fixture--nllb'/'snapshots'/'sample'
cache.mkdir(parents=True);(cache/'config.json').write_text('{"model_type":"m2m_100"}');(cache/'model.safetensors').write_bytes(b'fixture')
library=Library(root/'library'); folder=library.folder('全链路测试课程')
for name in ('录音 A','录音 B'):
 item=library.create(folder['id'],asdict(Settings('preview')),name)
 library.save(item,[Caption(i,i*40,i*40+30,f'Sentence {i}: context and evidence.','en',f'第 {i} 段中文译文。',final=True) for i in range(1,121)],'complete')
 with wave.open(str(library.directory(item['id'])/'录音.wav'),'wb') as f:
  f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(bytes(32000*2))
`, fixture], {cwd:root, encoding:'utf8'});
let app;
const passed=[], errors=[]; passed.push = (...values) => { console.log(...values); return Array.prototype.push.apply(passed,values); };
async function main() {
 app=await electron.launch({executablePath:require('electron'),args:[path.join(root,'desktop'),'--no-audio'],env:{...process.env,
  HF_HOME:path.join(fixture,'hf'),AGENTSCRIBE_DESKTOP_PYTHON:python,AGENTSCRIBE_DESKTOP_LIBRARY:path.join(fixture,'library'),AGENTSCRIBE_DESKTOP_PREFERENCES:path.join(fixture,'prefs.ini'),
  AGENTSCRIBE_DESKTOP_PROFILE:path.join(fixture,'profile'),AGENTSCRIBE_LOG_DIR:path.join(fixture,'logs'),AGENTSCRIBE_AUDIO_GUARD_LOG:path.join(fixture,'blocked.log'),AGENTSCRIBE_CHAIN_FIXTURE:fixture,
  PYTHONPATH:[fixture,root,process.env.PYTHONPATH||''].join(path.delimiter)}});
 const page=await app.firstWindow();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
 await page.getByRole('button',{name:'录音 A',exact:true}).waitFor();
 const rpc=(method,params={})=>page.evaluate(({method,params})=>window.agentScribe.request(method,params),{method,params});
 await page.evaluate(()=>{window.chainEvents=[];window.agentScribe.subscribe(event=>window.chainEvents.push(event));});
 await page.getByRole('button',{name:'录音 A',exact:true}).click();
 await page.getByText('00:00 / 00:02',{exact:true}).waitFor();
 assert.equal((await rpc('bootstrap')).state.playback.supports_gain,true);passed.push('WAV metadata before playback without opening any device');
 // Saved audio opens at the beginning. Establish a reading position with real
 // keyboard input before testing native scrollbar ownership and navigation.
 const captions=page.locator('.caption-scroll');
 await until(()=>captions.locator('[data-caption]').count().then(count=>count===120),'saved captions loaded');
 assert.equal(await captions.evaluate(el=>el.scrollTop),0);
 await captions.focus();await captions.press('End');
 await until(()=>captions.evaluate(el=>el.scrollTop>0&&el.scrollHeight-el.scrollTop-el.clientHeight<3),'keyboard caption tail');
 const tail=await captions.evaluate(el=>el.scrollTop);
 const rect=await page.locator('.caption-scroll').boundingBox();
 await page.mouse.move(rect.x+rect.width-3,rect.y+rect.height-18);await page.mouse.down();await page.mouse.move(rect.x+rect.width-3,rect.y+rect.height*.25,{steps:12});await page.mouse.up();
 await pause(350);const dragged=await page.locator('.caption-scroll').evaluate(el=>el.scrollTop);
 assert(dragged<tail,`scrollbar drag failed: ${dragged} >= ${tail}`);
 await page.screenshot({path:path.join(evidence,'scrollbar-reading.png')});
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'返回录音',exact:false}).click();await pause(350);
 assert(Math.abs(await page.locator('.caption-scroll').evaluate(el=>el.scrollTop)-dragged)<2);passed.push('native scrollbar and settings round trip retain reading position');
 // Hold the actual serializer after the first request to force all three exports into its queue.
 fs.writeFileSync(path.join(fixture,'hold-export'),'');
 await app.evaluate(({dialog},fixture)=>{globalThis.exportNumber=0;dialog.showSaveDialog=async()=>({canceled:false,filePath:fixture+`/export-${++globalThis.exportNumber}.txt`});},fixture);
 await rpc('recording.export',{format:'txt'});await until(()=>fs.existsSync(path.join(fixture,'export-started')),'writer started');
 await rpc('recording.export',{format:'txt'});await rpc('recording.export',{format:'txt'});
 assert(!fs.existsSync(path.join(fixture,'export-1.txt')));fs.unlinkSync(path.join(fixture,'hold-export'));
 await until(()=>[1,2,3].every(i=>fs.existsSync(path.join(fixture,`export-${i}.txt`))),'all explicit export files');
 for(const i of [1,2,3]) assert(fs.readFileSync(path.join(fixture,`export-${i}.txt`),'utf8').includes('Sentence 120'));
 const notices=await page.evaluate(()=>window.chainEvents.filter(e=>e.event==='notice'&&e.data.key==='export').map(e=>e.data));
 assert.equal(notices.filter(n=>!n.busy).length,1);passed.push('three queued exports retain every request and one final receipt');
 // Exercise real validation, then full preparation despite translation being off.
 await assert.rejects(()=>rpc('models.prepare',{only:''}),/无效的准备范围/);
 await rpc('settings.set',{values:{translate:false}});await rpc('models.check').catch(()=>{});
 await until(async()=>!(await rpc('bootstrap')).state.checking_models,'initial model check');
 assert.equal((await rpc('bootstrap')).state.translation_available,false);
 if(await page.getByRole('button',{name:'稍后',exact:true}).isVisible()) await page.getByRole('button',{name:'稍后',exact:true}).click();
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'模型管理',exact:true}).click();
 await page.getByRole('button',{name:'下载模型…',exact:true}).click();await page.getByRole('button',{name:'下载并使用推荐组合',exact:true}).click();
 await page.getByRole('dialog').waitFor({state:'hidden'});
 await until(async()=>{const s=(await rpc('bootstrap')).state;return !s.preparing&&!s.checking_models&&s.translation_available&&s.preparation_status==='准备完成';},'automatic readiness refresh');
 const commands=fs.readFileSync(path.join(fixture,'commands.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
 assert(commands.some(args=>args[0]==='linguaflow.recommended_prepare'&&!args.includes('--check')&&!args.includes('--only')));
 passed.push('recommended selection passes real validator, prepares both models, and refreshes readiness');
 await rpc('models.inventory');
 await page.getByRole('combobox',{name:'翻译模型',exact:true}).click();await page.getByRole('option',{name:'fixture/nllb',exact:true}).click();
 await until(async()=>{const data=await rpc('bootstrap');return data.settings.translation_engine==='pytorch'&&data.options.translation_devices.pytorch.includes(data.settings.translation_device);},'translation shortcut chooses compatible device');
 passed.push('real inventory shortcut changes translation engine with a compatible platform device');
 fs.writeFileSync(path.join(fixture,'prepare-mode'),'hold');await rpc('models.prepare');
 await page.getByRole('button',{name:'常规',exact:true}).click();await page.locator('.notification').getByRole('button',{name:'取消准备',exact:true}).click();
 await until(async()=>!(await rpc('bootstrap')).state.preparing,'preparation cancellation');
 assert.match((await rpc('bootstrap')).state.preparation_status,/取消/);
 fs.writeFileSync(path.join(fixture,'prepare-mode'),'fail');await rpc('models.retry');
 await until(async()=>!(await rpc('bootstrap')).state.preparing,'failed preparation');
 await page.locator('.notification.error').filter({hasText:'准备未完成'}).waitFor();
 fs.writeFileSync(path.join(fixture,'prepare-mode'),'success');await rpc('models.retry');await until(async()=>!(await rpc('bootstrap')).state.preparing,'retry completion');
 passed.push('progress outside model page, cancel, failure notification, retry use real subprocess lifetime');
 await rpc('settings.set',{values:{beta_features:true}});fs.writeFileSync(path.join(fixture,'prepare-mode'),'hold');await rpc('models.prepare',{kind:'documents'});
 await rpc('settings.set',{values:{beta_features:false}});await until(async()=>!(await rpc('bootstrap')).state.preparing,'Beta cancellation');
 assert.match((await rpc('bootstrap')).state.preparation_status,/取消/);passed.push('disabling Beta cancels owned document installer');
 await rpc('settings.set',{values:{beta_features:true}});await page.getByRole('button',{name:'返回录音',exact:false}).click();
 const opening=app.waitForEvent('window');await page.getByRole('button',{name:'课程资料与笔记 · Beta',exact:true}).click();const knowledge=await opening;knowledge.setDefaultTimeout(10000);knowledge.on('pageerror',e=>errors.push(e.message));
 await knowledge.getByText(/本机已保存.*视觉读取/).waitFor();await knowledge.evaluate(()=>{window.knowledgeView=null;window.agentScribe.subscribe(e=>{if(e.event==='knowledge'&&e.data.type==='view')window.knowledgeView=e.data;});});await knowledge.getByRole('tab',{name:'识别术语',exact:true}).click();await knowledge.getByRole('button',{name:'添加术语',exact:true}).click();
 await knowledge.getByRole('textbox',{name:'名称',exact:true}).fill('Machine Learning');await knowledge.getByRole('dialog').getByRole('button',{name:'保存',exact:true}).click();
 await knowledge.getByRole('textbox',{name:'别名 1',exact:true}).pressSequentially('ML; DL');assert.equal(await knowledge.getByRole('textbox',{name:'别名 1',exact:true}).inputValue(),'ML; DL');
 await knowledge.getByRole('button',{name:'保存审核结果',exact:true}).click();await until(()=>knowledge.getByRole('button',{name:'保存审核结果',exact:true}).isDisabled(),'term persistence receipt');
 await knowledge.getByRole('tab',{name:'课堂笔记',exact:true}).click();await knowledge.getByRole('checkbox',{name:'允许云端处理已保存文字',exact:true}).click();
 await until(()=>knowledge.getByRole('checkbox',{name:'允许云端处理已保存文字',exact:true}).isChecked(),'permission persisted');
 await knowledge.getByRole('textbox',{name:'课程问题',exact:true}).fill('录音 A 的问题');await knowledge.getByRole('button',{name:'提问',exact:true}).click();
 await knowledge.getByText('本地测试回答：录音 A 的问题',{exact:true}).waitFor();
 await rpc('settings.set',{values:{appearance:'dark'}});await knowledge.locator('html[data-theme=dark]').waitFor();assert(await knowledge.getByText('本地测试回答：录音 A 的问题',{exact:true}).isVisible());
 await page.getByRole('button',{name:'录音 B',exact:true}).click();
 const recordingB=(await rpc('bootstrap')).state.item.id;await until(()=>knowledge.evaluate(id=>window.knowledgeView?.manifest?.session_id===id,recordingB),'new worker view belongs to recording B');
 await until(()=>knowledge.getByText('本地测试回答：录音 A 的问题',{exact:true}).count().then(n=>n===0),'answer cleared on recording switch');
 await knowledge.getByRole('tab',{name:'识别术语',exact:true}).click();await until(()=>knowledge.getByRole('textbox',{name:'别名 1',exact:true}).inputValue().then(v=>v==='ML; DL'),'aliases round trip from real worker');
 await knowledge.screenshot({path:path.join(evidence,'terms-persisted.png')});passed.push('terms preserve separators through worker persistence; recording switch clears prior answer');
 await knowledge.keyboard.press('Escape');
 await page.getByRole('button',{name:'最近删除',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'关闭最近删除',exact:true}).click();
 const items=(await rpc('bootstrap')).library.sessions;for(const item of items) await rpc('item.trash',{identifier:item.id});
 await page.getByRole('button',{name:'最近删除',exact:true}).click();await page.getByRole('checkbox',{name:'选择 录音 A',exact:true}).waitFor();assert.equal((await page.getByRole('dialog',{name:'最近删除',exact:true}).boundingBox()).height,440);assert.equal(await page.getByRole('dialog').locator('.deleted-row small').count(),2);
 await page.getByRole('checkbox',{name:'选择 录音 A',exact:true}).check();await page.getByRole('checkbox',{name:'选择 录音 B',exact:true}).check();await page.getByRole('button',{name:'恢复选中',exact:true}).click();
 await page.getByText('最近删除为空。',{exact:true}).waitFor();assert.equal((await rpc('bootstrap')).library.sessions.length,2);passed.push('trash dates and selected batch restore');
 await page.screenshot({path:path.join(evidence,'trash-restored.png')});await page.getByRole('button',{name:'关闭最近删除',exact:true}).click();
 for(const item of (await rpc('bootstrap')).library.sessions) await rpc('item.trash',{identifier:item.id});
 await page.getByRole('button',{name:'最近删除',exact:true}).click();await page.getByRole('button',{name:'清空最近删除',exact:true}).click();
 await page.getByRole('dialog',{name:'永久删除 2 项？',exact:true}).getByRole('button',{name:'取消',exact:true}).click();assert.equal((await rpc('trash.list')).length,2);
 await page.getByRole('button',{name:'清空最近删除',exact:true}).click();await page.getByRole('dialog',{name:'永久删除 2 项？',exact:true}).getByRole('button',{name:'永久删除',exact:true}).click();
 await page.getByText('最近删除为空。',{exact:true}).waitFor();assert.equal((await rpc('trash.list')).length,0);await page.getByRole('button',{name:'关闭最近删除',exact:true}).click();passed.push('bulk purge confirmation cancellation preserves all files; confirmation purges captured entries');
 assert.deepEqual(errors,[]);await closeWorkspace(app,page);app=null;
 assert(!fs.existsSync(path.join(fixture,'blocked.log')));
 // A failed library startup can recover through a native directory choice.
 const broken=path.join(fixture,'not-a-directory');fs.writeFileSync(broken,'keep this original');
 const recovered=path.join(fixture,'recovered-library');
 app=await electron.launch({executablePath:require('electron'),args:[path.join(root,'desktop'),'--no-audio'],env:{...process.env,
  HF_HOME:path.join(fixture,'hf'),AGENTSCRIBE_DESKTOP_PYTHON:python,AGENTSCRIBE_DESKTOP_LIBRARY:broken,AGENTSCRIBE_DESKTOP_PREFERENCES:path.join(fixture,'recovered.ini'),AGENTSCRIBE_DESKTOP_PROFILE:path.join(fixture,'recovery-profile'),
  AGENTSCRIBE_AUDIO_GUARD_LOG:path.join(fixture,'blocked.log'),AGENTSCRIBE_LOG_DIR:path.join(fixture,'recovery-logs'),AGENTSCRIBE_CHAIN_FIXTURE:fixture,PYTHONPATH:[fixture,root].join(path.delimiter)}});
 const recoveryPage=await app.firstWindow();recoveryPage.setDefaultTimeout(10000);
 await recoveryPage.getByRole('button',{name:'选择其他录音保存位置',exact:true}).waitFor();
 await app.evaluate(({dialog},target)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[target]});},recovered);
 await recoveryPage.getByRole('button',{name:'选择其他录音保存位置',exact:true}).click();
 await recoveryPage.getByRole('button',{name:'设置',exact:true}).waitFor();
 assert.equal((await recoveryPage.evaluate(()=>window.agentScribe.request('bootstrap'))).root,recovered);
 assert.equal(fs.readFileSync(broken,'utf8'),'keep this original');
 await recoveryPage.screenshot({path:path.join(evidence,'startup-recovered.png')});
 await closeWorkspace(app,recoveryPage);app=null;
 passed.push('failed library startup chooses, validates and persists a new directory while preserving originals');
 assert(!fs.existsSync(path.join(fixture,'blocked.log')));
 fs.writeFileSync(path.join(evidence,'result.json'),JSON.stringify({passed,fixture,errors,native_audio_attempts:0},null,2));console.log(JSON.stringify({passed,fixture},null,2));
}
main().catch(async error=>{console.error(error);process.exitCode=1;if(app){for(const [index,win] of app.windows().entries()){fs.writeFileSync(path.join(evidence,`failure-${index}.txt`),await win.locator('body').innerText().catch(()=>''));await win.screenshot({path:path.join(evidence,`failure-${index}.png`)}).catch(()=>{});}await app.evaluate(({app})=>app.exit(1)).catch(()=>{});app=null;}}).finally(async()=>{if(app)await app.close();});
