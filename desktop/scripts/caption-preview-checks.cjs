// Real renderer, simulated recognizer events; no audio or model calls.
const assert = require('node:assert/strict');
module.exports = async function(app, page, passed) {
  const original = await page.evaluate(async () => {
    const bootstrap = await window.agentScribe.request('bootstrap');
    return {state:bootstrap.state, reduceMotion:bootstrap.settings.reduce_motion,
      captions:await window.agentScribe.request('captions.page')};
  });
  const state = {...original.state, state:'LISTENING', preview:null};
  const rows = original.captions.rows.slice(0,2).map((row,i) => ({...row, id:i+1,
    start:i, end:i+1, source:`Sentence ${i+1}.`, translation:'', final:false}));
  assert.equal(rows.length,2);
  const captions = {...original.captions, start:0, total:2, rows};
  const send = values => app.evaluate(({BrowserWindow}, values) => {
    const win = BrowserWindow.getAllWindows().find(w=>!w.webContents.getURL().includes('#'));
    for (const value of values) win.webContents.send('desktop:event',value);
  }, values);
  try {
    await page.evaluate(()=>window.agentScribe.request('settings.set',{values:{reduce_motion:false}}));
    await page.waitForFunction(()=>document.documentElement.dataset.reducedMotion==='false');
    await send([{event:'state',data:state},{event:'captions',data:captions}]);
    await page.waitForFunction(()=>document.querySelectorAll('.caption-body [data-caption]').length===2);
    await page.evaluate(() => {
      window.originalCaptionNodes = [...document.querySelectorAll('.caption-body [data-caption]')];
    });
    const preview = {sequence:1,keep_ids:[],start:0,end:2,source:'Corrected first sentence. Second sentence.',language:'en'};
    // The first render displays the preview and hides, rather than unmounts, rows.
    await send([{event:'state',data:{...state,preview}}]);
    await page.locator('.caption.preview').waitFor();
    assert.equal(await page.locator('.caption.preview .source').innerText(),preview.source);
    assert.equal(await page.locator('.caption.preview .source span[style]').textContent(),'');
    assert.equal(await page.locator('.caption-body [data-caption]').count(),2);
    assert.equal(await page.locator('.caption-body [data-caption]:visible').count(),0);
    assert(await page.evaluate(()=>window.originalCaptionNodes.every(node=>node.isConnected&&node.hidden)));
    const newest = {...preview,sequence:2,source:'Latest corrected sentence. Second sentence.'};
    await send([{event:'state',data:{...state,preview:newest}}]);
    await page.waitForFunction(text=>document.querySelector('.caption.preview .source')?.innerText===text,newest.source);
    const mapped = {...captions,rows:[{...rows[0],source:'Latest corrected sentence.'},rows[1]]};
    await send([{event:'captions',data:mapped}]);
    await page.waitForFunction(text=>document.querySelector('[data-caption="1"] .source')?.textContent===text,mapped.rows[0].source);
    assert.equal(await page.locator('.caption-body [data-caption]:visible').count(),0);
    await send([{event:'state',data:state}]);
    await page.waitForFunction(()=>window.originalCaptionNodes.every(node=>node.isConnected&&!node.hidden));
    assert.equal(await page.locator('[data-caption="1"] .source').innerText(),mapped.rows[0].source);
    assert.equal(await page.locator('[data-caption="1"] .source span[style]').textContent(),'');
    assert.equal(await page.locator('.caption.preview').count(),0);
    assert(await page.evaluate(()=>window.originalCaptionNodes.every(node=>document.querySelector(`[data-caption="${node.dataset.caption}"]`)===node)));
    passed.push('Immediate ASR preview preserves caption nodes and reveals mapped text without retyping or display delay');
  } finally {
    await page.evaluate(()=>{delete window.originalCaptionNodes;});
    await page.evaluate(value=>window.agentScribe.request('settings.set',{values:{reduce_motion:value}}),original.reduceMotion);
    await send([{event:'state',data:original.state},{event:'captions',data:original.captions}]);
  }
};
