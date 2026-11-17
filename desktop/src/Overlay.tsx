import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Button, Range } from './components';
import { CaptionText, captionLanguage } from './CaptionText';
import { projectCaptionRows } from './captionPreview';
import { bridge, request, type Caption, type Settings, type State } from './types';

export function Overlay() {
  const [rows, setRows] = useState<Caption[]>([]), [state, setState] = useState<State | null>(null);
  const [opacity, setOpacity] = useState(80), [font, setFont] = useState(23), [controls, setControls] = useState(false);
  const [translate, setTranslate] = useState(true), [animate, setAnimate] = useState(false), [error, setError] = useState('');
  const hide = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const shell = useRef<HTMLDivElement>(null), hovered = useRef(false);
  const resizing = useRef<{x:number;y:number;width:number;height:number} | null>(null);
  function showControls() { clearTimeout(hide.current); setControls(true); }
  function hideControls() {
    clearTimeout(hide.current);
    hide.current = setTimeout(() => {
      if (!hovered.current && !resizing.current && !shell.current?.contains(document.activeElement)) setControls(false);
    }, 400);
  }
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
  const projected = projectCaptionRows(rows, preview).views.filter(row => !row.hidden);
  const last = preview?.rows?.filter(row => row.source).at(-1);
  const caption = (last ? projected.find(row => row.caption.id === last.id) : projected.at(-1))?.caption;
  const pending = preview?.rows ? last && !caption ? last.source : '' : preview?.source;
  const source = pending || caption?.source || '等待语音…';
  const stale = !!caption?.translation_source && caption.translation_source !== caption.source;
  const prefix = stale ? caption?.error ? '译文更新失败 · ' : '正在更新译文 · ' : caption?.translation_phase === 'initial' ? '初译 · ' : '';
  const translating = state?.state !== 'IDLE' ? state?.translating ?? translate : translate;
  const target = !pending && translating && caption?.translation ? prefix + caption.translation : '';
  return <div ref={shell} className="overlay-shell" role="region" aria-label="悬浮字幕" tabIndex={0} style={{'--overlay-opacity':opacity/100,'--caption-size':`${font}px`} as CSSProperties}
    onFocusCapture={showControls} onBlurCapture={hideControls}
    onPointerEnter={() => {hovered.current=true;showControls();}}
    onPointerLeave={() => {hovered.current=false;hideControls();}}>
    <div className="overlay-backdrop">
      {controls && <div className="overlay-controls"><label>字号</label><Range label="字幕字号" min={12} max={56} value={font} onChange={value=>update({font:value})} /><span>{font}</span>
        <label>背景</label><Range label="字幕背景不透明度" max={100} value={opacity} onChange={value=>update({opacity:value})} /><span>{opacity}%</span>
        <Button variant="quiet" aria-label="关闭悬浮字幕" onClick={()=>request('overlay.close').catch(e=>setError(e.message))}>×</Button></div>}
      {error && <p role="alert">{error}</p>}
      <div className="overlay-text"><p lang={pending ? state?.caption_languages?.source || '' : caption ? captionLanguage(caption.language, state?.caption_languages?.source) : 'zh-CN'} className={pending || !caption?.final ? 'draft' : ''}><CaptionText text={source} animate={animate && !preview} /></p>{target && <p className="translation" lang={state?.caption_languages?.target || ''}>{prefix && <span lang="zh-CN">{prefix}</span>}<CaptionText text={caption?.translation || ''} animate={animate && !preview} /></p>}</div>
      {controls && <button type="button" className="overlay-resize" aria-label="调整字幕窗口大小" title="拖动或使用方向键调整宽高；Shift 加快"
        onKeyDown={event => {
          if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
          event.preventDefault();
          const step=event.shiftKey?40:10;
          request('overlay.resize',{width:innerWidth+(event.key==='ArrowRight'?step:event.key==='ArrowLeft'?-step:0),height:innerHeight+(event.key==='ArrowDown'?step:event.key==='ArrowUp'?-step:0)}).catch(e=>setError(e.message));
        }}
        onPointerDown={event=>{resizing.current={x:event.screenX,y:event.screenY,width:innerWidth,height:innerHeight};event.currentTarget.setPointerCapture(event.pointerId);}}
        onPointerMove={event=>{const start=resizing.current;if(start) request('overlay.resize',{width:Math.round(start.width+event.screenX-start.x),height:Math.round(start.height+event.screenY-start.y)}).catch(e=>setError(e.message));}}
        onPointerUp={event=>{resizing.current=null;event.currentTarget.releasePointerCapture(event.pointerId);}}
        onPointerCancel={()=>{resizing.current=null;hideControls();}}><svg width="20" height="20" aria-hidden="true"><path d="M4 18L18 4M9 18L18 9M14 18L18 14" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg></button>}
    </div>
  </div>;
}
