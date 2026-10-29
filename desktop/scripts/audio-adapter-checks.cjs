const assert = require('node:assert/strict');
const { fixture } = require('./fake-audio.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const logs=[],states=[],adapter=fixture({log:v=>logs.push(v),report:v=>states.push(v)});
 const send=(operation, extra={})=>adapter.command({operation,epoch:'one',...extra});
 send('load',{url:'http://127.0.0.1/fixture'});
 send('seek',{position:6000,play:true});send('seek',{position:12000,play:true});
 assert.equal(logs.length,0);adapter.players[0].ready();await tick();
 assert.deepEqual(logs,[{action:'seek',position:12000},{action:'play',position:12000}]);
 send('release');const count=states.length;adapter.players[0].emit('error');adapter.players[0].emit('timeupdate');
 assert.equal(states.length,count);
 send('load');send('seek',{position:9000,play:true});send('pause');adapter.players[1].ready();await tick();
 assert.deepEqual(logs.at(-1),{action:'seek',position:9000});assert.equal(logs.length,3);
 send('load');send('seek',{position:14000,play:true});adapter.players[2].emit('error');adapter.players[2].ready();await tick();
 assert.equal(logs.length,3);assert.equal(states.at(-1).state,'Error');
 send('load');send('play');adapter.players[3].ready();send('release');await tick();assert.equal(logs.length,3);
 console.log('Audio adapter: delayed latest seek, pause, release, stale callbacks and errors passed without devices');
})().catch(error=>{console.error(error);process.exitCode=1;});
