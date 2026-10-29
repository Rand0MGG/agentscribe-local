// Disposable offline document renderer. Only backend-approved snapshot files can load.
const { app, BrowserWindow, session } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL, fileURLToPath } = require('node:url');
const textScript = require('./document-text.cjs');
const lifetime = require('./helper-lifetime.cjs').ownHelper(app);
const request = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
app.disableHardwareAcceleration();
for (const flag of ['disable-audio-input', 'disable-audio-output', 'use-fake-device-for-media-stream', 'disable-background-networking']) app.commandLine.appendSwitch(flag);
app.commandLine.appendSwitch('force-device-scale-factor', '1');
app.setPath('userData', path.join(path.dirname(request.output), '.browser'));
app.whenReady().then(async () => {
  let window;
  try {
    const permitted = new Set(request.permitted.map(p => fs.realpathSync(p)));
    const profile = session.fromPartition('document-render');
    let failed = false;
    profile.webRequest.onBeforeRequest((details, callback) => {
      let allowed = /^(data|blob|about):/.test(details.url);
      try { if (details.url.startsWith('file:')) allowed = permitted.has(fs.realpathSync(fileURLToPath(details.url.split('#')[0].split('?')[0]))); } catch { allowed = false; }
      if (!allowed) failed = true;
      callback({ cancel: !allowed });
    });
    profile.setPermissionRequestHandler((_c, _p, done) => done(false));
    profile.setPermissionCheckHandler(() => false);
    profile.on('will-download', event => { event.preventDefault(); failed = true; });
    window = new BrowserWindow({ show: false, width: 1200, height: 1500, useContentSize: true,
      webPreferences: { session: profile, sandbox: true, nodeIntegration: false, contextIsolation: true,
        webSecurity: true, webgl: false, disableDialogs: true, imageAnimationPolicy: 'noAnimation', backgroundThrottling: false, offscreen: true } });
    const page = window.webContents;
    page.setAudioMuted(true);
    page.setWindowOpenHandler(() => { failed = true; return { action: 'deny' }; });
    page.on('will-navigate', event => { event.preventDefault(); failed = true; });
    page.on('console-message', details => { if (details.level === 'error') failed = true; });
    page.on('will-prevent-unload', event => event.preventDefault());
    page.on('will-attach-webview', event => event.preventDefault());
    await page.loadURL(pathToFileURL(request.entry).href);
    fs.mkdirSync(request.output);
    let result;
    if (request.kind === 'image') {
      let animated = false;
      const mime = {'.gif':'image/gif','.webp':'image/webp','.png':'image/png'}[path.extname(request.source).toLowerCase()];
      if (mime) {
        const bytes = fs.readFileSync(request.source).toString('base64');
        animated = await page.executeJavaScript(`(async()=>{
          const data=Uint8Array.from(atob(${JSON.stringify(bytes)}),c=>c.charCodeAt(0));
          const decoder=new ImageDecoder({data,type:${JSON.stringify(mime)}});
          try{await decoder.tracks.ready;await decoder.completed;return decoder.tracks.selectedTrack.frameCount>1;}finally{decoder.close();}
        })()`);
      }
      const value = await page.executeJavaScript(`(async()=>{
        const image = new Image(); image.src=${JSON.stringify(pathToFileURL(request.source).href)}; await image.decode();
        if(!image.naturalWidth || image.naturalWidth*image.naturalHeight > 64*1024**2)throw Error('图片超过 6400 万像素预算。');
        let ratio=Math.min(1,4096/Math.max(image.naturalWidth,image.naturalHeight),Math.sqrt(4*1024**2/(image.naturalWidth*image.naturalHeight)));
        const canvas=document.createElement('canvas');
        for(let i=0;i<8;i++){
          canvas.width=Math.max(1,Math.floor(image.naturalWidth*ratio));canvas.height=Math.max(1,Math.floor(image.naturalHeight*ratio));
          canvas.getContext('2d',{colorSpace:'srgb'}).drawImage(image,0,0,canvas.width,canvas.height);
          const data=canvas.toDataURL('image/png').split(',')[1];
          if(data.length*3/4<=4*1024**2)return data;
          ratio*=.8;
        }
        throw Error('图片标准化后仍超过 4 MiB 预算。');
      })()`);
      fs.writeFileSync(path.join(request.output, 'page-0001.png'), Buffer.from(value, 'base64'));
      result = { pageCount: 1, images: [{ page: 1, path: 'page-0001.png' }], native_text: [''], missingFonts: [], staticFrame: animated };
    } else {
      await page.executeJavaScript(`(async()=>{
        const style=document.createElement('style');style.textContent='::-webkit-scrollbar{width:0!important;height:0!important;}';document.head.append(style);
        for(const image of document.images)image.loading='eager';
        await Promise.all([document.fonts.ready,...[...document.images].map(i=>i.decode())]);
        for(const el of document.querySelectorAll('*'))if(['fixed','sticky'].includes(getComputedStyle(el).position)){
          el.style.setProperty('position','static','important');for(const key of ['top','right','bottom','left'])el.style.setProperty(key,'auto','important');
        }
        await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      })()`);
      const [width,height] = await page.executeJavaScript('[Math.ceil(Math.max(innerWidth,document.documentElement.scrollWidth)),Math.ceil(Math.max(innerHeight,document.documentElement.scrollHeight))]');
      const columns = Math.ceil(width/1200), rows = Math.ceil(height/1500);
      if (columns*rows > request.limit) throw Error('网页超过页面分片预算。');
      const extracted = JSON.parse(await page.executeJavaScript(textScript));
      if (extracted.error || extracted.texts?.length !== columns*rows) throw Error('课件原生文字提取失败或超出预算。');
      let used = 0; const images = [];
      for (let y=0;y<rows;y++) for (let x=0;x<columns;x++) {
        const left=x*1200, top=y*1500;
        const [sx,sy] = await page.executeJavaScript(`(async()=>{scrollTo({left:${left},top:${top},behavior:'instant'});await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return [scrollX,scrollY];})()`);
        const rectangle = { x: left-sx, y: top-sy, width: Math.min(1200,width-left), height: Math.min(1500,height-top) };
        const image = await page.capturePage(rectangle);
        const png = image.toPNG(); used += png.length;
        if (!png.length || png.length>4*1024**2 || used>256*1024**2) throw Error('课件页面图片超过预算。');
        const filename=`page-${String(images.length+1).padStart(4,'0')}.png`;
        fs.writeFileSync(path.join(request.output,filename),png);
        images.push({page:images.length+1,path:filename,rectangle:{...rectangle,x:left,y:top}});
      }
      result = {pageCount:images.length,images,resources:request.assets,missingFonts:[],native_text:extracted.texts,
        viewport:{width:1200,height:1500},layoutVersion:request.version};
    }
    if (failed) throw Error('网页加载了快照外的资源或页面加载失败，请保存完整离线课件。');
    window.destroy();window = null;
    await lifetime.finish(result);
  } catch (error) { window?.destroy();await lifetime.fail(error); }
});
