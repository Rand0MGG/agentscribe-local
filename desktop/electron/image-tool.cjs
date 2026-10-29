const { app, nativeImage } = require('electron');
const fs = require('node:fs');
const lifetime = require('./helper-lifetime.cjs').ownHelper(app, {timeout: 14000});
const request=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
app.disableHardwareAcceleration();
app.setPath('userData', require('node:path').join(require('node:path').dirname(process.argv[2]), '.image-browser'));
app.whenReady().then(async()=>{
  try {
    let image=nativeImage.createFromPath(request.source);
    if(image.isEmpty())throw Error('无法读取桌面背景图像。');
    const size=image.getSize(), ratio=Math.max(request.width/size.width,request.height/size.height);
    image=image.resize({width:Math.ceil(size.width*ratio),height:Math.ceil(size.height*ratio),quality:'best'});
    const resized=image.getSize();
    image=image.crop({x:Math.floor((resized.width-request.width)/2),y:Math.floor((resized.height-request.height)/2),width:request.width,height:request.height});
    const bytes=image.toBitmap();
    for(let i=0;i<bytes.length;i+=4){const b=bytes[i];bytes[i]=bytes[i+2];bytes[i+2]=b;}
    await lifetime.finish(bytes.toString('base64'));
  }catch(error){await lifetime.fail(error);}
});
