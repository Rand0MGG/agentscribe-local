"""Build an offline, source-image comparison from both isolated native probes."""
import html
import json
from pathlib import Path

from PySide6.QtGui import QImage, QPainter

ROOT = Path(__file__).resolve().parents[1] / '.work/browser/ui-parity'


def main():
    qt = json.loads((ROOT / 'qt/manifest.json').read_text())
    electron = json.loads((ROOT / 'electron/manifest.json').read_text())
    if electron.get('motion') == 'pending' or electron.get('audioAttempts') != 0 or qt.get('audioAttempts') != 0:
        raise ValueError('Both native probes must finish before building the comparison.')
    current = {row['name']: row for row in electron['records']}
    pairs, geometry = [], []
    derived = ROOT / 'comparison'
    derived.mkdir(exist_ok=True)
    for old in qt['records']:
        name = old['name']
        if name not in current:
            continue
        new = current[name]
        before, after = ROOT / 'qt' / (name + '.png'), ROOT / 'electron' / (name + '.png')
        qi, ei = QImage(str(before)), QImage(str(after))
        if name.startswith(('catalog-', 'model-editor-', 'model-advanced-')) and new.get('dialog'):
            qi = qi.copy(16, 12, qi.width() - 32, qi.height() - 32)
            rect = new['dialog']
            ei = ei.copy(round(rect['x']), round(rect['y']), round(rect['width']), round(rect['height']))
            before, after = derived / ('qt-' + name + '.png'), derived / ('electron-' + name + '.png')
            qi.save(str(before))
            ei.save(str(after))
        pairs.append(dict(name=name, qt=str(before.relative_to(ROOT)), electron=str(after.relative_to(ROOT)),
                          qtSize=[qi.width(), qi.height()], electronSize=[ei.width(), ei.height()]))
        if name.startswith(('workspace-', 'recording-', 'playback-')) and old.get('island') and new.get('island'):
            geometry.append(dict(name=name, delta={key: round(new['island'][key] - old['island'][key], 3)
                                                  for key in ('x', 'y', 'width', 'height')}))
        if name in ('workspace-light-900x650', 'settings-general-light-900x650', 'knowledge-materials-dark'):
            canvas = QImage(qi.width() + ei.width(), max(qi.height(), ei.height()), QImage.Format.Format_RGB32)
            canvas.fill(0xffffffff)
            painter = QPainter(canvas)
            painter.drawImage(0, 0, qi)
            painter.drawImage(qi.width(), 0, ei)
            painter.end()
            canvas.save(str(derived / (name + '.png')))
    motion = json.loads((ROOT / 'electron/motion.json').read_text())
    payload = json.dumps(dict(pairs=pairs, geometry=geometry, motion=motion), ensure_ascii=False).replace('</', '<\\/')
    options = ''.join(f'<option value="{i}">{html.escape(pair["name"])}</option>' for i, pair in enumerate(pairs))
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AgentScribe · Qt / Electron 页面与动画对照</title>
<style>body{font:15px system-ui;margin:28px;background:#f4f3f4;color:#29292d}header,section{max-width:1600px;margin:0 auto 24px}h1{font-size:24px}p{line-height:1.7}select,button,input{font:inherit;padding:8px}nav{display:flex;gap:12px;align-items:center;flex-wrap:wrap;position:sticky;top:0;background:#f4f3f4;padding:10px 0;z-index:2}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0;min-width:0}figcaption{padding:10px;font-weight:600}.pair img{width:100%;height:auto;border:1px solid #bbb}.stage{position:relative;width:100%;max-width:1280px}.stage img{display:block;width:100%}.stage img:last-child{position:absolute;top:0;left:0;clip-path:inset(0 50% 0 0)}details{padding:12px;background:white;border-radius:10px;margin:10px 0}pre{white-space:pre-wrap;font-size:13px}svg{background:white;border:1px solid #ddd;max-width:100%}.motion{display:flex;gap:16px;flex-wrap:wrap}.motion article{flex:1;min-width:340px}.legend{font-size:13px;color:#555}[hidden]{display:none!important}</style>
<header><h1>AgentScribe · 新旧前端逐页对照</h1><p>Qt：v0.10.2 页面实现，保留双前端切换入口。Electron：本轮本地修改。两个原生窗口使用相同示例正文、模型清单和显示路径；深浅主题 × 三种尺寸。录音状态、电平和回放均为显示夹具，后台禁止音频访问；没有下载模型或发送云端内容。截图按逻辑像素保存。字体栅格化及原生窗口装饰仍可能不同。</p>
<nav><label>页面 <select id="page">OPTIONS</select></label><button id="prev">上一页</button><button id="next">下一页</button><label><input type="checkbox" id="overlay">叠加比较</label><label id="wipeLabel" hidden>分界 <input type="range" id="wipe" min="0" max="100" value="50"></label></nav>
<p id="dimensions"></p><div class="pair" id="pair"><figure><figcaption>Qt 原版</figcaption><img id="q"></figure><figure><figcaption>Electron 当前</figcaption><img id="e"></figure></div><div class="stage" id="stage" hidden><img id="bottom"><img id="top"></div></header>
<section><h2>动画实测</h2><p>下图来自原生 Electron 连续帧的几何读数。蓝线为实测，灰线为原版 Qt 的时长与缓动公式；反向操作从当时的尺寸继续。弹窗 140ms、切页 150ms 的实际动画对象，以及减少动态效果、音量展开不移动进度条，均由探针检查。曲线是尺寸采样，不是屏幕录像。</p><div class="motion" id="motion"></div><details><summary>小岛位置和尺寸差值（Electron − Qt，逻辑像素）</summary><pre id="geometry"></pre></details><details><summary>验证信息</summary><p>动画采样：electron/motion.json；页面清单：qt/manifest.json、electron/manifest.json。Windows 原生渲染、跨屏缩放和真实音频不在本轮验证范围。旧 DMG 不含本轮修改。</p></details></section>
<script>const data=PAYLOAD;const $=id=>document.getElementById(id);function show(){const p=data.pairs[+$('page').value];$('q').src=$('bottom').src=p.qt;$('e').src=$('top').src=p.electron;$('dimensions').textContent=p.name+' · Qt '+p.qtSize.join('×')+' / Electron '+p.electronSize.join('×');const same=p.qtSize.join()===p.electronSize.join();$('overlay').disabled=!same;if(!same)$('overlay').checked=false;const over=$('overlay').checked;$('pair').hidden=over;$('stage').hidden=!over;$('wipeLabel').hidden=!over;$('stage').style.maxWidth=p.qtSize[0]+'px';} $('page').onchange=$('overlay').onchange=show;$('prev').onclick=()=>{$('page').value=(+$('page').value+data.pairs.length-1)%data.pairs.length;show()};$('next').onclick=()=>{$('page').value=(+$('page').value+1)%data.pairs.length;show()};$('wipe').oninput=()=>$('top').style.clipPath='inset(0 '+(100-$('wipe').value)+'% 0 0)';show();$('geometry').textContent=JSON.stringify(data.geometry,null,2);const curve=t=>t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;for(const [key,label,lo,hi,duration,out] of [['islandExpand','录音小岛展开',58,84,280,false],['islandCollapse','录音小岛收起',84,58,280,false],['islandInterrupted','100ms 时反向收起',58,84,280,false],['volumeExpand','音量展开',58,170,200,true]]){const rows=data.motion.traces[key];const x=t=>30+t/650*440,y=v=>155-(v-Math.min(lo,hi))/(Math.abs(hi-lo))*125;const points=rows.map(r=>x(r.t)+','+y(r.height)).join(' ');const reference=Array.from({length:66},(_,i)=>{const t=i*10,p=Math.min(1,t/duration);const v=lo+(hi-lo)*(out?1-(1-p)**3:curve(p));return x(t)+','+y(v)}).join(' ');const article=document.createElement('article');article.innerHTML='<h3>'+label+'</h3><svg viewBox="0 0 500 190"><path d="M30 20V155H480" fill="none" stroke="#bbb"/>'+(key.includes('Interrupted')?'':'<polyline points="'+reference+'" fill="none" stroke="#b9bac0" stroke-width="4"/>')+'<polyline points="'+points+'" fill="none" stroke="#2875c8" stroke-width="2"/><text x="30" y="180">0 ms</text><text x="410" y="180">650 ms</text></svg><p class="legend">采样 '+rows.length+' 帧；结束高度 '+rows.at(-1).height+' px</p>';$('motion').appendChild(article)}</script></html>'''
    (ROOT / 'index.html').write_text(document.replace('OPTIONS', options).replace('PAYLOAD', payload))
    (ROOT / 'comparison.json').write_text(json.dumps(dict(pairs=len(pairs), geometry=geometry), indent=2))
    print(f'Created {len(pairs)} paired views: {ROOT / "index.html"}')


if __name__ == '__main__':
    main()
