import { useEffect, useId, useRef, useState } from 'react';
import { Modal } from './components';
import { clock, request, type Page, type RequestResults } from './types';

type SearchProps = {
  identifier: string;
  generation: number;
  onLocate: (page: Page, id: number) => void;
};

export function CaptionSearch({ onClose, ...owner }: SearchProps & { onClose: () => void }) {
  const [query, setQuery] = useState('');
  return <Modal title="查找字幕" description="搜索原文或译文，选择结果定位，不会自动播放。" open onClose={onClose}>
    <input aria-label="搜索当前录音字幕" placeholder="搜索原文或译文…" value={query}
      maxLength={1024} onChange={event => setQuery(event.target.value)} autoFocus />
    <Results key={query} query={query} {...owner} />
  </Modal>;
}

const rowHeight = 64;
const maxHeight = 320;

function Results({ query, identifier, generation, onLocate }: SearchProps & { query: string }) {
  const prefix = useId();
  const area = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(maxHeight);
  const locateTicket = useRef(0);
  const [top, setTop] = useState(0), [active, setActive] = useState(0);
  const [chunk, setChunk] = useState<(RequestResults['captions.search'] & { start: number }) | null>(null);
  const [error, setError] = useState('');
  const total = chunk?.total ?? 0;
  const firstVisible = Math.min(Math.max(0, total - 1), Math.floor(top / rowHeight));
  const lastVisible = Math.min(total - 1, Math.ceil((top + height) / rowHeight) - 1);
  const first = Math.max(0, firstVisible - 1);
  const end = Math.min(total, first + Math.ceil(maxHeight / rowHeight) + 3);
  // Each reply carries up to 100 hits. Overlap windows so scrolling can continue during a request.
  const start = Math.floor(first / 50) * 50;
  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      request('captions.search', { query, start }).then(result => {
        if (current && result.generation === generation) {
          setChunk({ ...result, start });
          setError('');
        }
      }).catch(reason => { if (current) setError(reason.message); });
    }, start === 0 ? 100 : 0);
    return () => { current = false; clearTimeout(timer); };
  }, [query, generation, start]);
  useEffect(() => () => { locateTicket.current++; }, []);

  async function choose(id: number) {
    const ticket = ++locateTicket.current;
    try {
      const result = await request('captions.locate', { identifier, generation, caption_id: id });
      if (ticket === locateTicket.current && result.page.generation === generation) onLocate(result.page, id);
    } catch (reason) {
      if (ticket === locateTicket.current) setError((reason as Error).message);
    }
  }

  const hasResults = total > 0;
  useEffect(() => {
    const element = area.current;
    if (!element) return;
    const resize = new ResizeObserver(() => setHeight(element.clientHeight));
    resize.observe(element);
    return () => resize.disconnect();
  }, [hasResults]);
  const selected = Math.max(firstVisible, Math.min(active, lastVisible));
  const rowAt = (index: number) => chunk?.rows[index - chunk.start];
  return <>
    <p role="status">{error || (!chunk ? '正在查找…' : total ? `共 ${total} 条，显示 ${firstVisible + 1}–${lastVisible + 1}` : '没有匹配内容。')}</p>
    {total > 0 && <div className="search-results" role="listbox" aria-label="匹配字幕" tabIndex={0} ref={area}
      aria-activedescendant={rowAt(selected) ? `${prefix}-${selected}` : undefined}
      style={{ height: Math.min(maxHeight, total * rowHeight) }}
      onScroll={event => setTop(event.currentTarget.scrollTop)}
      onKeyDown={event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          const hit = rowAt(selected);
          if (hit) void choose(hit.id);
          return;
        }
        const next = { ArrowDown: selected + 1, ArrowUp: selected - 1, End: total - 1, Home: 0 }[event.key];
        if (next === undefined) return;
        event.preventDefault();
        const index = Math.max(0, Math.min(total - 1, next));
        const area = event.currentTarget;
        area.scrollTop = Math.max((index + 1) * rowHeight - area.clientHeight, Math.min(area.scrollTop, index * rowHeight));
        setTop(area.scrollTop); setActive(index);
      }}>
      <div style={{ height: total * rowHeight, position: 'relative' }}>
        {Array.from({ length: Math.max(0, end - first) }, (_, offset) => {
          const index = first + offset, row = rowAt(index);
          if (!row) return null;
          return <div className="search-hit" role="option" key={row.id} id={`${prefix}-${index}`}
            aria-selected={selected === index} aria-posinset={index + 1} aria-setsize={total}
            style={{ top: index * rowHeight, height: rowHeight }} title={[row.source, row.translation].join('\n')}
            onClick={() => { setActive(index); void choose(row.id); }}>
            <span>{clock(row.start).slice(row.start >= 3600 ? 0 : 3)}　{row.source}</span><span>{row.translation}</span>
          </div>;
        })}
      </div>
    </div>}
  </>;
}
