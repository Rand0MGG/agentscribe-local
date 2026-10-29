const { app, BrowserWindow } = require('electron');
const fs=require('node:fs'), path=require('node:path');
const lifetime = require('./helper-lifetime.cjs').ownHelper(app);
const args=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 let win;
 try{
  win=new BrowserWindow({show:false,webPreferences:{sandbox:true,nodeIntegration:false,contextIsolation:true}});
  await win.loadURL('data:text/html,<meta charset="utf-8">');
  const source='data:image/svg+xml;base64,'+fs.readFileSync(args.source).toString('base64');
  for(const item of args.outputs){
   const data=await win.webContents.executeJavaScript(`(async()=>{const i=new Image();i.src=${JSON.stringify(source)};await i.decode();const c=document.createElement('canvas');c.width=c.height=${item.size};c.getContext('2d').drawImage(i,0,0,c.width,c.height);return c.toDataURL('image/png').split(',')[1]})()`);
   fs.writeFileSync(item.path,Buffer.from(data,'base64'));
  }
  win.destroy();await lifetime.finish({ok:true});
 }catch(error){win?.destroy();await lifetime.fail(error);}
});
