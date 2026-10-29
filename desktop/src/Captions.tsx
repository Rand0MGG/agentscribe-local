import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { CaptionText } from './CaptionText';
import { Button, Tip } from './components';
import { clock, type Page, type State, type Caption, type Interaction } from './types';

export function Captions({ seekRevision = 0, visible = true, page, state, position, onPage, onSeek, locate, onFollow, summary, interaction = { doubleClickInterval: 500, dragDistance: 10 } }: {
  seekRevision?: number; visible?: boolean; page: Page; state: State; position: number; onPage: (start?: number) => void;
  onSeek: (milliseconds: number) => void; locate: number | null;
  onFollow: (value: boolean) => void;
  summary?: ReactNode; interaction?: Interaction;
}) {
  const container = useRef<HTMLDivElement>(null), body = useRef<HTMLDivElement>(null);
  const following = useRef(true), frame = useRef(0), clickTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const followFrame = useRef(0), goal = useRef(0);
  const [returnBottom, setReturnBottom] = useState(110);
  const forceSeek = useRef(false);
  const [follow, setFollow] = useState(true), [returnDirection, setReturnDirection] = useState(0);
  const anchor = useRef<{ id: string; offset: number } | null>(null);
  const humanScroll = useRef(false), playbackOffset = useRef<number | null>(null), previousPlaying = useRef<number | undefined>(undefined), lastPlaying = useRef<number | undefined>(undefined);
  const pointer = useRef<{ x: number; y: number; at: number; button: number } | null>(null);
  const playing = page.rows.find(row => row.start * 1000 <= position && row.end * 1000 > position)?.id;
  const active = state.state !== 'IDLE';
  // Match the original feed: previews hide existing cards, never destroy them.
  // Keeping their text components prevents old words from being typed again.
  const rows = page.rows;
  const animate = active && !state.preview;
  function readableHeight() {
    const area = container.current;
    if (!area) return 0;
    const transport = area.closest('.workspace')?.querySelector('.transport-area')?.getBoundingClientRect();
    return Math.min(area.clientHeight, transport ? transport.top - area.getBoundingClientRect().top - 12 : area.clientHeight);
  }
  function visiblePlaying() {
    const area = container.current, target = area?.querySelector<HTMLElement>(`[data-caption="${playing}"]`);
    return area && target && target.offsetTop >= area.scrollTop + 16 && target.offsetTop + Math.min(target.offsetHeight, 80) <= area.scrollTop + readableHeight() ? target : null;
  }
  function updateReturnIndicator() {
    const area = container.current;
    if (!area || following.current) { setReturnDirection(0); return; }
    const target = area.querySelector<HTMLElement>(`[data-caption="${playing}"]`);
    if (!active && state.has_audio && target) {
      const top = target.offsetTop, bottom = top + Math.min(target.offsetHeight, 80);
      setReturnDirection(top < area.scrollTop ? -1 : bottom > area.scrollTop + readableHeight() ? 1 : 0);
    } else if (!active && state.has_audio && position >= 0 && page.rows.length) {
      setReturnDirection(position < page.rows[0].start * 1000 ? -1 : position >= page.rows.at(-1)!.end * 1000 ? 1 : 0);
    } else if (!active && state.has_audio) setReturnDirection(0);
    else setReturnDirection(area.scrollHeight - area.scrollTop - area.clientHeight > 3 || page.start + page.rows.length < page.total ? 1 : 0);
  }
  function remember() {
    const area = container.current;
    if (!area) return;
    const item = [...area.querySelectorAll<HTMLElement>('[data-caption]')]
      .find(element => element.offsetTop + element.offsetHeight > area.scrollTop);
    anchor.current = item ? { id: item.dataset.caption!, offset: item.offsetTop - area.scrollTop } : null;
  }
  function followTarget() {
    const area = container.current;
    if (!area || !visible || !area.clientHeight) return;
    if (!active && playing != null) {
      const target = area.querySelector<HTMLElement>(`[data-caption="${playing}"]`);
      if (target && (forceSeek.current || playbackOffset.current !== null && previousPlaying.current !== playing || !visiblePlaying())) {
        goal.current = Math.max(0, target.offsetTop - (playbackOffset.current ?? Math.min(96, readableHeight() * .22)));
        forceSeek.current = false; previousPlaying.current = playing;
      } else {
        return;
      }
    } else if (!active) return;
    else goal.current = Math.max(0, area.scrollHeight - area.clientHeight);
    if (document.documentElement.dataset.reducedMotion === 'true' || matchMedia('(prefers-reduced-motion: reduce)').matches) {
      cancelAnimationFrame(followFrame.current); followFrame.current = 0; area.scrollTop = goal.current; return;
    }
    if (followFrame.current) return;
    let previous = performance.now();
    function step(now: number) {
      followFrame.current = 0;
      if (!area || !following.current) return;
      const distance = goal.current - area.scrollTop;
      if (Math.abs(distance) < 2) { area.scrollTop = goal.current; return; }
      area.scrollTop += distance * (1 - Math.exp(-Math.min(64, now - previous) / 85));
      previous = now;
      followFrame.current = requestAnimationFrame(step);
    }
    followFrame.current = requestAnimationFrame(step);
  }
  function stopFollowing() { following.current = false; onFollow(false); setFollow(false); cancelAnimationFrame(followFrame.current); followFrame.current = 0; remember(); updateReturnIndicator(); }
  useEffect(() => {
    following.current = true; setFollow(true); anchor.current = null; playbackOffset.current = null; previousPlaying.current = undefined;
    humanScroll.current = false; pointer.current = null; lastPlaying.current = undefined; forceSeek.current = false; clearTimeout(clickTimer.current);
  }, [state.generation]);
  useEffect(() => { if (active) clearTimeout(clickTimer.current); }, [active]);
  useLayoutEffect(() => {
    if (!seekRevision) return;
    humanScroll.current = false; playbackOffset.current = null; anchor.current = null;
    forceSeek.current = true; following.current = true; setFollow(true); onFollow(true);
    followTarget();
  }, [seekRevision]);
  useLayoutEffect(() => {
    const transport = container.current?.closest('.workspace')?.querySelector<HTMLElement>('.control-island,.playback-group');
    if (!transport) return;
    const area = container.current!;
    const observer = new ResizeObserver(() => {
      if (area.clientHeight) setReturnBottom(Math.max(16, area.getBoundingClientRect().bottom - transport.getBoundingClientRect().top + 16));
    });
    observer.observe(transport); observer.observe(area);
    return () => observer.disconnect();
  }, [active, state.has_audio, visible]);
  useLayoutEffect(() => {
    const area = container.current, previous = lastPlaying.current;
    if (playing !== undefined && playing !== previous) {
      const card = area?.querySelector<HTMLElement>(`[data-caption="${previous}"]`);
      // Like Qt, resume only when the next sentence arrives while the previous
      // one remains readable. Scrolling across it must not steal wheel control.
      if (!active && !following.current && area && card && card.offsetTop >= area.scrollTop
          && card.offsetTop + Math.min(card.offsetHeight, 80) <= area.scrollTop + readableHeight()) {
        playbackOffset.current = card.offsetTop - area.scrollTop;
        following.current = true; setFollow(true); onFollow(true);
      }
      lastPlaying.current = playing;
    }
  }, [playing]);
  useLayoutEffect(() => {
    if (!visible) { cancelAnimationFrame(followFrame.current); followFrame.current = 0; return; }
    if (following.current) followTarget();
    else if (anchor.current && container.current) {
      const target = container.current.querySelector<HTMLElement>(`[data-caption="${anchor.current.id}"]`);
      if (target) container.current.scrollTop = target.offsetTop - anchor.current.offset;
    }
    updateReturnIndicator();
  }, [page, state.preview, position, follow, visible]);
  const followCallback = useRef(followTarget); followCallback.current = followTarget;
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => { if (following.current) followCallback.current(); });
    });
    if (body.current) observer.observe(body.current);
    return () => { observer.disconnect(); cancelAnimationFrame(frame.current); cancelAnimationFrame(followFrame.current); followFrame.current = 0; clearTimeout(clickTimer.current); };
  }, []);
  useEffect(() => {
    if (locate === null || !container.current) return;
    humanScroll.current = false;
    stopFollowing();
    container.current.querySelector(`[data-caption="${locate}"]`)?.scrollIntoView({ block: 'center' });
    remember(); updateReturnIndicator();
  }, [locate, page.start]);
  function activate(event: React.MouseEvent, row: Caption) {
    const down = pointer.current;
    pointer.current = null;
    if (!down || down.button !== 0 || active || performance.now() - down.at > 400 ||
        Math.abs(event.clientX - down.x) + Math.abs(event.clientY - down.y) >= interaction.dragDistance || window.getSelection()?.toString() || event.detail > 1 || !state.has_audio) return;
    // Only actual text hitboxes initiate seeking. Whitespace and selection remain inert.
    const range = document.createRange(); range.selectNodeContents(event.currentTarget);
    if (![...range.getClientRects()].some(rect => event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom)) return;
    clearTimeout(clickTimer.current);
    clickTimer.current = setTimeout(() => onSeek(row.start * 1000), interaction.doubleClickInterval);
  }
  return <div className="caption-region" data-active={active}><div className="caption-scroll" ref={container} tabIndex={0} aria-label="双语字幕"
    onPointerDown={event => {
      const area = container.current;
      if (area && event.target === area && (event.clientX >= area.getBoundingClientRect().left + area.clientWidth || event.clientX <= area.getBoundingClientRect().left + 12)) {
        humanScroll.current = true; stopFollowing();
      }
    }}
    onWheel={event => { const area = container.current; if (area && ((event.deltaY < 0 && area.scrollTop > 0) || (event.deltaY > 0 && area.scrollTop + area.clientHeight < area.scrollHeight))) { humanScroll.current = true; stopFollowing(); } }}
    onTouchMove={() => { humanScroll.current = true; stopFollowing(); }} onKeyDown={event => { if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) { humanScroll.current = true; stopFollowing(); } }}
    onScroll={() => {
      if (!following.current) remember();
      updateReturnIndicator();
      if (!humanScroll.current || !container.current) return;
      if (active && container.current.scrollHeight - container.current.scrollTop - container.current.clientHeight < 3) {
        following.current = true; setFollow(true); onFollow(true);
      }
    }}>
    <div className="caption-body" ref={body}>
      {active && page.start > 0 && <Button variant="quiet" onClick={() => { stopFollowing(); onPage(Math.max(0, page.start - 200)); }}>较早的字幕</Button>}
      {!rows.length && !state.preview && (summary || <div className="empty"><div>{active ? state.failure || state.capture?.waiting || (state.state === 'PAUSED' ? '已暂停聆听' : state.status) : '无内容'}</div></div>)}
      {rows.map(row => <article key={row.id} data-caption={row.id} hidden={!!state.preview && !state.preview.keep_ids.includes(row.id)} className={`caption ${playing === row.id && !active ? 'playing' : ''} ${locate === row.id ? 'located' : ''}`}>
        <div className="timestamp">{clock(row.start).slice(row.start >= 3600 ? 0 : 3)}{row.final ? ' · 已定稿' : ' · 优化中'}</div>
        <p className={`source ${!row.final ? 'draft' : ''}`} onMouseDown={event => { pointer.current = { x: event.clientX, y: event.clientY, at: performance.now(), button: event.button }; }}
          onClick={event => activate(event, row)} onDoubleClick={() => clearTimeout(clickTimer.current)}><CaptionText text={row.source} animate={animate} /></p>
        {row.translation && <p className="translation" onMouseDown={event => { pointer.current = { x: event.clientX, y: event.clientY, at: performance.now(), button: event.button }; }} onClick={event => activate(event, row)} onDoubleClick={() => clearTimeout(clickTimer.current)}><CaptionText text={row.translation} animate={animate} /></p>}
        {(row.error || row.translation && !['译文已定稿', '已保存译文'].includes(row.translation_status)) && <p className={`caption-status ${row.error ? 'error' : ''}`}>{row.error || row.translation_status}</p>}
      </article>)}
      {state.preview && <article className="caption preview"><div className="timestamp">{clock(state.preview.start).slice(state.preview.start >= 3600 ? 0 : 3)} · 实时原文</div><p className="source draft"><CaptionText text={state.preview.source} animate={false} /></p></article>}
      {active && page.start + page.rows.length < page.total && <Button variant="quiet" onClick={() => { stopFollowing(); onPage(page.start + 200); }}>较新的字幕</Button>}
    </div>
  </div>{!follow && returnDirection !== 0 && <Tip label={active ? '回到最新字幕' : `返回播放位置（${returnDirection < 0 ? '上方' : '下方'}）`}><Button className="return-caption" style={{bottom:returnBottom}} aria-label={active ? '回到最新字幕并恢复自动跟随' : '返回播放位置并恢复跟随'} onClick={() => { humanScroll.current = false; playbackOffset.current = null; anchor.current = null; following.current = true; onFollow(true); setFollow(true); onPage(); requestAnimationFrame(followTarget); }}>
    <svg aria-hidden="true" width="38" height="38" viewBox="0 0 40 40" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{transform:returnDirection < 0 ? 'rotate(180deg)' : undefined}}><path d="M20 12v15m-6-6 6 6 6-6" /></svg>
  </Button></Tip>}</div>;
}
