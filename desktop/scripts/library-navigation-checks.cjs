// Real pointer hit areas across sibling/nested folders; keep menu triggers independent.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
module.exports=async function(app,page,root,fixture,passed){
 const tree=page.getByRole('tree',{name:'录音文件夹'});
 const row=name=>tree.getByRole('treeitem',{name,exact:true});
 const button=name=>row(name).getByRole('button',{name,exact:true});
 const original='字幕回听',b='跨文件夹录音 B',c='跨文件夹录音 C';
 const shown=async name=>{
  await page.waitForFunction(name=>document.querySelector('.recording-title')?.textContent===name,name);
  await page.waitForFunction(name=>document.querySelector('.library-row[aria-selected=true]')?.getAttribute('aria-label')===name,name);
  await page.waitForFunction(()=>![...document.querySelectorAll('.item-name')].some(n=>n.disabled));
 };
 await button(original).click();await shown(original);
 await row(b).locator('svg').first().click();await shown(b);
 await page.getByText(b+' contents',{exact:true}).waitFor();
 await row(c).click({position:{x:8,y:19}});await shown(c);
 await page.getByText(c+' contents',{exact:true}).waitFor();
 let box=await row(original).boundingBox();await row(original).click({position:{x:box.width-40,y:box.height/2}});await shown(original);
 await page.waitForFunction(()=>document.querySelectorAll('[data-caption]').length===650);
 // One ordinary click publishes only one recording-open request, even on text.
 await app.evaluate((_e,root)=>{const {Service}=process.getBuiltinModule('module').createRequire(root+'/desktop/package.json')('./electron/service.cjs');globalThis.libraryRealRequest=Service.prototype.request;globalThis.libraryOpenCalls=[];Service.prototype.request=function(method,params){if(method==='recording.open')globalThis.libraryOpenCalls.push(params.identifier);return globalThis.libraryRealRequest.call(this,method,params);};},root);
 await button(b).click();await shown(b);
 assert.equal(await app.evaluate(()=>globalThis.libraryOpenCalls.length),1);
 // Right-click and the trailing menu button do not navigate to another recording.
 await row(c).click({button:'right'});await page.getByRole('menuitem',{name:'重命名',exact:true}).waitFor();await page.keyboard.press('Escape');
 assert.equal(await page.locator('.recording-title').textContent(),b);
 await row(c).getByRole('button',{name:c+'的操作',exact:true}).click();await page.getByRole('menuitem',{name:'重命名',exact:true}).waitFor();await page.keyboard.press('Escape');
 assert.equal(await page.locator('.recording-title').textContent(),b);
 await button(original).click();await shown(original);
 const brokenPath=fs.readFileSync(path.join(fixture,'broken-path'),'utf8'),before=fs.readFileSync(brokenPath);
 try {
  fs.writeFileSync(brokenPath,'{}');await button('损坏导航录音').click();
  await page.locator('.notification.error').waitFor();await shown(original);
  assert.equal((await page.locator('[data-caption="1"] .source').textContent()).includes('Sentence 1:'),true);
 } finally {fs.writeFileSync(brokenPath,before);}
 await page.locator('.notification.error').getByRole('button',{name:'收起通知'}).click();
 await app.evaluate((_e,root)=>{const {Service}=process.getBuiltinModule('module').createRequire(root+'/desktop/package.json')('./electron/service.cjs');Service.prototype.request=globalThis.libraryRealRequest;},root);
 passed.push('Cross-folder recording rows: one click across icon/indent/empty/text; menus never navigate; failed loads retain original selection/content');
};
