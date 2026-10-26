// Inspect actual rendered widths, including interruption and reduced motion.
const assert=require('node:assert/strict');
module.exports=async function(app,page,rpc,passed){
 const recording=(await rpc('bootstrap')).state.item?.id;
 const settings=()=>page.getByRole('button',{name:'设置',exact:true});
 const back=()=>page.getByRole('button',{name:'返回录音',exact:false});
 const sample=()=>page.evaluate(()=>{
  window.navigationWidths=[];const until=performance.now()+1500;
  const frame=()=>{const nav=document.querySelector('.settings-nav')||document.querySelector('.sidebar');window.navigationWidths.push(nav.getBoundingClientRect().width);if(performance.now()<until)requestAnimationFrame(frame);};requestAnimationFrame(frame);
 });
 await rpc('settings.set',{values:{reduce_motion:false}});
 await page.waitForFunction(()=>document.documentElement.dataset.reducedMotion==='false');
 await page.getByRole('button',{name:'收起侧边栏',exact:true}).click();
 await page.waitForFunction(()=>Math.abs(document.querySelector('.sidebar').getBoundingClientRect().width-36)<.5);
 await sample();await settings().click();
 await page.waitForFunction(()=>window.navigationWidths.some(width=>width>40&&width<165));
 await page.waitForFunction(()=>{const nav=document.querySelector('.settings-nav');return nav&&Math.abs(nav.getBoundingClientRect().width-Math.max(170,Math.min(250,innerWidth*.2)))<.5;});
 await sample();await back().click();
 await page.waitForFunction(()=>window.navigationWidths.some(width=>width>40&&width<165));
 await page.waitForFunction(()=>Math.abs(document.querySelector('.sidebar').getBoundingClientRect().width-36)<.5);
 // Keep observation, reversal and the next-frame sample in the renderer so
 // host scheduling cannot turn a rapid return into a completed transition.
 const reversal=await page.evaluate(()=>new Promise((resolve,reject)=>{
  let frame=0;
  const timer=setTimeout(()=>{cancelAnimationFrame(frame);reject(new Error('No intermediate settings navigation width'));},2000);
  const sample=()=>{
   const nav=document.querySelector('.settings-nav'),width=nav?.getBoundingClientRect().width;
   if(width>40&&width<180){
    [...nav.querySelectorAll('button')].find(node=>node.textContent.includes('返回录音')).click();
    frame=requestAnimationFrame(()=>{clearTimeout(timer);resolve({width,resumed:document.querySelector('.sidebar').getBoundingClientRect().width});});
   }else frame=requestAnimationFrame(sample);
  };
  document.querySelector('.sidebar button[aria-label="设置"]').click();
  frame=requestAnimationFrame(sample);
 }));
 assert(reversal.width>40&&reversal.width<180);
 assert(reversal.resumed<=reversal.width+16,'Rapid return must continue from the current navigation width');
 await page.waitForFunction(()=>Math.abs(document.querySelector('.sidebar').getBoundingClientRect().width-36)<.5);
 assert.equal(await page.locator('.sidebar.compact').count(),1);
 await settings().click();await rpc('settings.set',{values:{reduce_motion:true}});
 await page.waitForFunction(()=>document.documentElement.dataset.reducedMotion==='true');
 assert.equal(await page.locator('.settings-nav').evaluate(n=>n.getAnimations().filter(a=>a.playState==='running').length),0);
 assert.equal(await page.locator('.settings-nav').evaluate(n=>Math.round(n.getBoundingClientRect().width)),await page.evaluate(()=>Math.max(170,Math.min(250,innerWidth*.2))));
 await back().click();assert.equal((await page.locator('.sidebar').boundingBox()).width,36);
 assert.equal((await rpc('bootstrap')).state.item?.id,recording);
 await page.getByRole('button',{name:'展开侧边栏',exact:true}).click();
 passed.push('Compact sidebar: folder name tooltip; settings navigation animates both directions, reverses quickly, retains compact state and honors reduced motion');
};
