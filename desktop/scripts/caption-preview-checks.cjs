// Real renderer, simulated recognizer events; no audio or model calls.
const assert = require('node:assert/strict');
module.exports = async function(app, page, passed) {
  const original = await page.evaluate(async () => {
    const bootstrap = await window.agentScribe.request('bootstrap');
    return {state:bootstrap.state, reduceMotion:bootstrap.settings.reduce_motion,
      captions:await window.agentScribe.request('captions.page')};
  });
  const state = {...original.state, state:'LISTENING', preview:null};
  const rows = Array.from({length:3}, (_,i) => original.captions.rows[i] || original.captions.rows[0]).map((row,i) => ({...row, id:i+1,
    start:i, end:i+1, source:`Sentence ${i+1}.`, translation:`译文 ${i+1}。`, translation_source:`Sentence ${i+1}.`, final:true}));
  assert.equal(rows.length,3);
  const captions = {...original.captions, start:0, total:3, rows};
  const send = values => app.evaluate(({BrowserWindow}, values) => {
    const win = BrowserWindow.getAllWindows().find(w=>!w.webContents.getURL().includes('#'));
    for (const value of values) win.webContents.send('desktop:event',value);
  }, values);
  try {
    await page.evaluate(()=>window.agentScribe.request('settings.set',{values:{reduce_motion:false}}));
    await page.waitForFunction(()=>document.documentElement.dataset.reducedMotion==='false');
    await send([{event:'state',data:state},{event:'captions',data:captions}]);
    await page.waitForFunction(()=>document.querySelectorAll('.caption-body [data-caption]').length===3);
    await page.evaluate(() => {
      window.originalCaptionNodes = [...document.querySelectorAll('.caption-body [data-caption]')];
    });
    const patches = rows.map((row,index)=>({id:row.id,index,source:row.source,start:row.start,end:row.end}));
    patches[0] = {...patches[0],source:'Sentence 1!'};
    const preview = {sequence:1,keep_ids:[],start:0,end:3,
      source:patches.map(row=>row.source).join(' '),language:'en',rows:patches};
    await page.evaluate(()=>{window.originalTranslationNodes=[...document.querySelectorAll('.caption-body .translation')];});
    await send([{event:'state',data:{...state,preview}}]);
    await page.waitForFunction(()=>document.querySelector('[data-caption="1"] .source')?.innerText==='Sentence 1!');
    assert.equal(await page.locator('.caption-body [data-caption]:visible').count(),3);
    assert.equal(await page.locator('.caption.preview').count(),0);
    assert.equal(await page.locator('[data-caption="1"] .source span[style]').textContent(),'');
    assert.equal(await page.locator('[data-caption="2"] .translation').innerText(),rows[1].translation);
    assert.equal(await page.locator('[data-caption="3"] .translation').innerText(),rows[2].translation);
    assert(await page.evaluate(()=>window.originalCaptionNodes.every(node=>node.isConnected&&!node.hidden)));
    assert(await page.evaluate(()=>window.originalTranslationNodes.every(node=>node.isConnected)));
    const newest = {...preview,sequence:2,source:'Latest corrected sentence. Sentence 2. Sentence 3.',
      rows:[{...patches[0],source:'Latest corrected sentence.'},...patches.slice(1)]};
    await send([{event:'state',data:{...state,preview:newest}}]);
    await page.waitForFunction(()=>document.querySelector('[data-caption="1"] .source')?.innerText==='Latest corrected sentence.');
    // An older completed mapping must not replace the newest display revision.
    await send([{event:'captions',data:{...captions,rows:[{...rows[0],source:'Sentence 1!'},...rows.slice(1)]}}]);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(await page.locator('[data-caption="1"] .source').innerText(),'Latest corrected sentence.');
    assert.equal(await page.locator('.caption-body [data-caption]:visible').count(),3);
    const mapped = {...captions,rows:[{...rows[0],source:'Latest corrected sentence.'},...rows.slice(1)]};
    await send([{event:'captions',data:mapped},{event:'state',data:state}]);
    await page.waitForFunction(()=>!document.querySelector('.caption.preview') &&
      document.querySelector('[data-caption="1"] .source')?.innerText==='Latest corrected sentence.');
    assert.equal(await page.locator('[data-caption="1"] .source span[style]').textContent(),'');
    assert(await page.evaluate(()=>window.originalCaptionNodes.every(node=>document.querySelector(`[data-caption="${node.dataset.caption}"]`)===node)));
    // A genuine deleted span hides only its own slot, preserving both neighbours.
    await send([{event:'state',data:{...state,preview:{...newest,sequence:3,
      rows:newest.rows.map(row=>row.id===2?{...row,source:''}:row)}}}]);
    await page.waitForFunction(()=>document.querySelector('[data-caption="2"]')?.hidden);
    assert.equal(await page.locator('.caption-body [data-caption]:visible').count(),2);
    assert.equal(await page.locator('[data-caption="3"] .translation').innerText(),rows[2].translation);
    passed.push('Local ASR preview edits preserve three card identities and unchanged translations, reject stale mapping, and hide only deleted spans');
  } finally {
    await page.evaluate(()=>{delete window.originalCaptionNodes;delete window.originalTranslationNodes;});
    await page.evaluate(value=>window.agentScribe.request('settings.set',{values:{reduce_motion:value}}),original.reduceMotion);
    await send([{event:'state',data:original.state},{event:'captions',data:original.captions}]);
  }
};
