// Device-only substitute. The production preload and its async ordering run unchanged.
const { EventEmitter } = require('node:events');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function fixture({ delay = 0, log = () => {}, report = () => {} } = {}) {
 const ipc = new EventEmitter(), players = [];
 class Audio extends EventEmitter {
  constructor() { super(); this.readyState=0; this.paused=true;this.ended=false;this.offset=0;players.push(this); }
  addEventListener(name, callback) { this.on(name,callback); }
  set src(value) { this.source=value; if (delay) this.timer=setTimeout(()=>this.ready(),delay); }
  ready() { this.readyState=1;this.emit('loadedmetadata'); }
  get currentTime() { return this.offset; }
  set currentTime(value) { this.offset=value;log({action:'seek',position:value*1000});this.emit('timeupdate'); }
  async play() { this.paused=false;log({action:'play',position:this.offset*1000});this.emit('play'); }
  pause() { if (!this.paused) {this.paused=true;this.emit('pause');} }
  removeAttribute() { clearTimeout(this.timer); }
  load() {}
 }
 const node = () => ({gain:{value:1},connect(other){return other;}});
 class AudioContext {
  constructor(){this.destination=node();}
  createGain(){return node();} createWaveShaper(){return node();} createMediaElementSource(){return node();}
  async resume(){} async close(){}
 }
 ipc.send=(_name,value)=>report(value);
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../electron/audio-preload.cjs'),'utf8'),{
  require(name){if(name!=='electron')throw Error(name);return {ipcRenderer:ipc};},Audio,AudioContext,Float32Array});
 return {players,command(value){ipc.emit('audio:command',null,value);}};
}
module.exports={fixture};
if(require.main===module){
 const root=process.argv[2];
 const adapter=fixture({delay:350,log:row=>fs.appendFileSync(path.join(root,'media.jsonl'),JSON.stringify(row)+'\n'),
  report:value=>process.stdout.write(JSON.stringify(value)+'\n')});
 require('node:readline').createInterface({input:process.stdin}).on('line',line=>adapter.command(JSON.parse(line))).on('close',()=>process.exit(0));
}
