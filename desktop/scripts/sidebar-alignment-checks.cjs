const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async function(app,page,rpc,output,passed){
 const measure=()=>page.locator('.sidebar').evaluate(sidebar=>{
  const box=n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,cx:r.x+r.width/2};};
  return {sidebar:box(sidebar),actions:[...sidebar.querySelectorAll('.sidebar-action')].map(n=>({name:n.getAttribute('aria-label'),...box(n),icon:box(n.querySelector('svg')),label:n.querySelector('.sidebar-label')?box(n.querySelector('.sidebar-label')):null})),folders:[...sidebar.querySelectorAll('.library-row.folder[aria-level="1"]')].map(n=>({row:box(n),icon:box([...n.querySelectorAll('.tree-toggle svg,.compact-folder-icon svg')].find(icon=>icon.getBoundingClientRect().width>0)),label:box(n.querySelector('.sidebar-label'))}))};
 });
 let layout=await measure(),actions=layout.actions.filter(n=>n.label);
 for(const action of actions){assert.equal(action.height,36);assert(action.width>36);assert.equal(action.width,actions[0].width);assert.equal(action.icon.width,20);assert.equal(action.icon.cx,actions[0].icon.cx);assert.equal(action.label.x,actions[0].label.x);}
 assert(await page.locator('.sidebar-action').evaluateAll(nodes=>nodes.every(n=>getComputedStyle(n).maxHeight==='36px')));
 assert(await page.locator('.sidebar button').evaluateAll(nodes=>nodes.filter(n=>n.getBoundingClientRect().height>0).every(n=>n.getBoundingClientRect().height===36)));
 for(const folder of layout.folders){assert.equal(folder.row.height,36);assert.equal(folder.icon.cx,actions[0].icon.cx);assert.equal(folder.label.x,actions[0].label.x);}
 const create=layout.actions.find(n=>n.name==='新建文件夹');assert.equal(create.width,36);assert.equal(create.height,36);
 const toggle=actions.find(n=>n.name==='收起侧边栏');assert.equal(create.y-toggle.y-toggle.height,8);
 assert(await page.getByRole('button',{name:'新建文件夹',exact:true}).isEnabled());
 await page.getByRole('button',{name:'新建文件夹',exact:true}).hover();
 await page.getByRole('tooltip').filter({hasText:'新建文件夹'}).waitFor();
 await page.mouse.move(400,100);await page.getByRole('tooltip').waitFor({state:'hidden'});
 await page.screenshot({path:path.join(output,'sidebar-aligned-expanded-light.png'),scale:'css'});
 await rpc('settings.set',{values:{appearance:'dark'}});await page.locator('html[data-theme=dark]').waitFor();
 await page.screenshot({path:path.join(output,'sidebar-aligned-expanded-dark.png'),scale:'css'});
 await page.getByRole('button',{name:'收起侧边栏',exact:true}).click();layout=await measure();
 for(const action of layout.actions){assert.equal(action.width,36);assert.equal(action.height,36);assert.equal(action.icon.cx,layout.sidebar.cx);}
 const compactCreate=layout.actions.find(n=>n.name==='新建文件夹'),compactToggle=layout.actions.find(n=>n.name==='展开侧边栏');
 assert.equal(compactCreate.y-compactToggle.y-compactToggle.height,4);
 for(const folder of layout.folders){assert.equal(folder.row.height,36);assert.equal(folder.icon.cx,layout.sidebar.cx);}
 assert(await page.locator('.sidebar button').evaluateAll(nodes=>nodes.filter(n=>n.getBoundingClientRect().height>0).every(n=>{const r=n.getBoundingClientRect();return r.width===36&&r.height===36;})));
 // Exercise an overflowing compact tree without changing the isolated backend
 // library used by the remaining workflow checks.
 const originalLibrary=(await rpc('bootstrap')).library;
 const publishLibrary=library=>app.evaluate(({BrowserWindow},data)=>BrowserWindow.getAllWindows()[0].webContents.send('desktop:event',{event:'library',data}),library);
 try {
  await publishLibrary({folders:Array.from({length:30},(_,index)=>({id:`overflow-${index}`,name:`滚动目录 ${index}`,parent:null})),sessions:[]});
  await page.waitForFunction(()=>document.querySelectorAll('.library-tree .library-row').length===30);
  assert(await page.locator('.library-tree').evaluate(n=>n.scrollHeight>n.clientHeight&&n.clientWidth===36));
  const overflow=await measure();
  for(const folder of overflow.folders){assert.equal(folder.row.width,36);assert.equal(folder.icon.cx,overflow.sidebar.cx);}
  const last=page.getByRole('treeitem',{name:'滚动目录 29',exact:true});
  await last.scrollIntoViewIfNeeded();assert(await last.isVisible());
  assert(await page.locator('.library-tree').evaluate(n=>n.scrollTop>0));
 } finally {await publishLibrary(originalLibrary);await page.waitForFunction(()=>!document.querySelector('[data-library-id="overflow-0"]'));}
 await page.screenshot({path:path.join(output,'sidebar-aligned-compact-dark.png'),scale:'css'});
 await rpc('settings.set',{values:{appearance:'light'}});await page.locator('html[data-theme=light]').waitFor();
 await page.screenshot({path:path.join(output,'sidebar-aligned-compact-light.png'),scale:'css'});
 await page.getByRole('button',{name:'设置',exact:true}).click();
 const settings=await page.locator('.settings-nav .button').evaluateAll(nodes=>nodes.map(n=>({height:n.getBoundingClientRect().height,padding:getComputedStyle(n).paddingLeft,font:getComputedStyle(n).fontSize})));
 for(const button of settings){assert.equal(button.height,36);assert.equal(button.padding,'8px');assert.equal(button.font,'13px');}
 await page.screenshot({path:path.join(output,'sidebar-aligned-settings-light.png'),scale:'css'});
 await page.getByRole('button',{name:'返回录音',exact:false}).click();
 await page.getByRole('button',{name:'展开侧边栏',exact:true}).click();
 passed.push('Sidebar alignment: identical 36px actions/rows, 20px icons, shared icon centers and text baselines, square compact targets and consistent settings buttons');
};
