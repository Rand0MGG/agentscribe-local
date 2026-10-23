import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Button, Range } from './components';
import { CaptionText } from './CaptionText';
import { bridge, request, type Caption, type Settings, type State } from './types';

export function Overlay() {
  const [rows, setRows] = useState<Caption[]>([]), [state, setState] = useState<State | null>(null);
  const [opacity, setOpacity] = useState(80), [font, setFont] = useState(23), [controls, setControls] = useState(false);
  const [translate, setTranslate] = useState(true), [animate, setAnimate] = useState(false), [error, setError] = useState('');
  const hide = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const resizing = useRef<{x:number;y:number;width:number;height:number} | null>(null);
  function update(values: { font?: number; opacity?: number }) {
    if (values.font !== undefined) setFont(values.font);
    if (values.opacity !== undefined) setOpacity(values.opacity);
    request('overlay.set', values).catch(e => setError(e.message));
  }
  useEffect(() => {
    function settings(value: Settings) {
      document.documentElement.dataset.theme = String(value.appearance || 'light');
      document.documentElement.dataset.reducedMotion = String(!!value.reduce_motion);
      setTranslate(!!value.translate);
    }
    request('overlay.snapshot').then(value => { setState(value.state); setRows(value.rows); setFont(value.options.font); setOpacity(value.options.opacity); if (value.settings) settings(value.settings); }).catch(e => setError(e.message));
    const unsubscribe = bridge?.subscribe(({event,data}) => {
      if (event === 'state') setState(data);
      if (event === 'settings') settings(data);
      if (event === 'captions') { setRows(data.rows.slice(-2)); setAnimate(false); }
      if (event === 'caption') { setAnimate(true); setRows(old => [...old.filter(row => row.id !== data.caption.id),data.caption].filter(row => row.source).sort((a,b)=>a.start-b.start || a.id-b.id).slice(-2)); }
    });
    return () => { unsubscribe?.(); clearTimeout(hide.current); };
  }, []);
  const preview = state?.preview;
  const caption = rows.filter(row => !preview || preview.keep_ids.includes(row.id)).sort((a,b)=>a.start-b.start || a.id-b.id).at(-1);
  const source = preview?.source || caption?.source || '等待语音…';
  const stale = !!caption?.translation_source && caption.translation_source !== caption.source;
  const prefix = stale ? caption?.error ? '译文更新失败 · ' : '正在更新译文 · ' : caption?.translation_phase === 'initial' ? '初译 · ' : '';
  const translating = state?.state !== 'IDLE' ? state?.translating ?? translate : translate;
  const target = !preview?.source && translating && caption?.translation ? prefix + caption.translation : '';
  return <div className="overlay-shell" style={{'--overlay-opacity':opacity/100,'--caption-size':`${font}px`} as CSSProperties}
    onPointerEnter={() => {clearTimeout(hide.current);setControls(true);}}
    onPointerLeave={() => {clearTimeout(hide.current);hide.current=setTimeout(()=>{if(!resizing.current)setControls(false);},400);}}>
    <div className="overlay-backdrop">
      {controls && <div className="overlay-controls"><label>字号</label><Range label="字幕字号" min={12} max={56} value={font} onChange={value=>update({font:value})} /><span>{font}</span>
        <label>背景</label><Range label="字幕背景不透明度" max={100} value={opacity} onChange={value=>update({opacity:value})} /><span>{opacity}%</span>
        <Button variant="quiet" aria-label="关闭悬浮字幕" onClick={()=>request('overlay.close').catch(e=>setError(e.message))}>×</Button></div>}
      {error && <p role="alert">{error}</p>}
      <div className="overlay-text"><p className={preview?.source || !caption?.final ? 'draft' : ''}><CaptionText text={source} animate={animate && !preview?.source} /></p>{target && <p className="translation"><CaptionText text={target} animate={animate} /></p>}</div>
      {controls && <div className="overlay-resize" role="separator" aria-label="调整字幕窗口大小" title="拖动调整字幕窗口宽高"
        onPointerDown={event=>{resizing.current={x:event.screenX,y:event.screenY,width:innerWidth,height:innerHeight};event.currentTarget.setPointerCapture(event.pointerId);}}
        onPointerMove={event=>{const start=resizing.current;if(start) request('overlay.resize',{width:Math.round(start.width+event.screenX-start.x),height:Math.round(start.height+event.screenY-start.y)}).catch(e=>setError(e.message));}}
        onPointerUp={event=>{resizing.current=null;event.currentTarget.releasePointerCapture(event.pointerId);}}
        onPointerCancel={()=>{resizing.current=null;}}><svg width="20" height="20" aria-hidden="true"><path d="M4 18L18 4M9 18L18 9M14 18L18 14" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg></div>}
    </div>
  </div>;
}
