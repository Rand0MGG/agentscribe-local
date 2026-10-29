// Real disposable Electron image tool, disconnected output and abruptly lost parent.
const { spawn, execFileSync } = require('node:child_process');
const { once } = require('node:events');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const assert = require('node:assert/strict');
const executable = require('electron');
const root = path.resolve(__dirname, '../..');
async function finished(child) {
 let errors='';child.stderr?.on('data',data=>errors+=data);
 const timeout=setTimeout(()=>child.kill('SIGKILL'),10000);
 try { const [code,signal]=await once(child,'close');assert.equal(signal,null,errors);assert.equal(code,0,errors); }
 finally {clearTimeout(timeout);}
 assert(!/Uncaught Exception|UnhandledPromiseRejection/.test(errors),errors);
}
(async()=>{
 const work=fs.mkdtempSync(path.join(os.tmpdir(),'agentscribe-helper-test-'));
 try {
  // Tiny valid PNG; expand output above a pipe buffer to exercise asynchronous writes.
  fs.writeFileSync(path.join(work,'image.png'),Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=','base64'));
  const request=path.join(work,'request.json');fs.writeFileSync(request,JSON.stringify({source:path.join(work,'image.png'),width:1024,height:1024}));
  const script=path.join(root,'desktop/electron/image-tool.cjs');
  let child=spawn(executable,[script,request],{stdio:['ignore','pipe','pipe'],env:{...process.env,AGENTSCRIBE_HELPER_OWNER_PID:String(process.pid)}});
  const done=finished(child);child.stdout.destroy();await done;
  child=spawn(executable,[script,request],{stdio:['ignore','pipe','pipe']});
  let output='';child.stdout.on('data',data=>output+=data);await finished(child);
  assert.equal(Buffer.from(JSON.parse(output),'base64').length,1024*1024*4);
  // An already exited owner models a kill before Electron has registered with AppKit.
  const owner=Number(execFileSync(process.execPath,['-e','process.stdout.write(String(process.pid))'],{encoding:'utf8'}));
  const waiting=path.join(work,'waiting.cjs');
  fs.writeFileSync(waiting,`const {app}=require('electron');require(${JSON.stringify(path.join(root,'desktop/electron/helper-lifetime.cjs'))}).ownHelper(app);app.whenReady().then(()=>setInterval(()=>{},1000));`);
  child=spawn(executable,[waiting],{stdio:['ignore','pipe','pipe'],env:{...process.env,AGENTSCRIBE_HELPER_OWNER_PID:String(owner)}});
  child.stdout.resume();await finished(child);
  console.log('Native helpers: closed output and exited parent finish without modal errors or orphan processes');
 } finally {fs.rmSync(work,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
