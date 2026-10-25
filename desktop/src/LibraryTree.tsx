import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ActionMenu, ContextActions, Icon, type MenuAction } from './components';
import type { Item, Library } from './types';

export function LibraryTree({ library, current, folder, blocked, onOpen, onFolder, actions, folderActions }: {
  library: Library; current?: string; folder: string; blocked: boolean; onOpen: (item: Item) => void;
  onFolder: (id: string) => void; actions: (item: Item) => MenuAction[]; folderActions: (item: Item) => MenuAction[];
}) {
  const [collapsed, setCollapsed] = useState(new Set<string>()), [focused, setFocused] = useState(current || folder);
  const tree = useRef<HTMLDivElement>(null);
  const rows: { item: Item; folder: boolean; depth: number; parent?: string }[] = [];
  function collect(parent: string | null = null, depth = 0, seen = new Set<string>()) {
    for (const item of library.folders.filter(item => (item.parent || null) === parent)) {
      if (seen.has(item.id)) continue;
      seen.add(item.id); rows.push({ item, folder: true, depth, parent: parent || undefined });
      if (!collapsed.has(item.id)) {
        for (const recording of library.sessions.filter(row => row.folder === item.id)) rows.push({ item: recording, folder: false, depth: depth + 1, parent: item.id });
        collect(item.id, depth + 1, seen);
      }
    }
  }
  collect();
  const target = rows.some(row => row.item.id === focused) ? focused : rows[0]?.item.id;
  useEffect(() => { if (!tree.current?.contains(document.activeElement)) setFocused(current || folder); }, [current, folder]);
  function focus(id: string) {
    setFocused(id);
    requestAnimationFrame(() => tree.current?.querySelector<HTMLElement>(`[data-library-id="${CSS.escape(id)}"]`)?.focus());
  }
  function toggle(id: string) { setCollapsed(old => { const next = new Set(old); if (next.has(id)) next.delete(id); else next.add(id); return next; }); }
  return <div ref={tree} role="tree" aria-label="录音文件夹" className="library-tree">{rows.map((row, index) => {
    const { item } = row, expanded = row.folder && !collapsed.has(item.id);
    const select = () => { setFocused(item.id); if (row.folder) onFolder(item.id); else if (!blocked) onOpen(item); };
    return <ContextActions key={item.id} actions={row.folder ? folderActions(item) : actions(item)}><div
      role="treeitem" aria-label={item.name} data-library-id={item.id} aria-level={row.depth + 1} aria-selected={target === item.id}
      aria-expanded={row.folder ? expanded : undefined} tabIndex={target === item.id ? 0 : -1}
      className={`library-row ${row.folder ? 'folder' : ''} ${target === item.id ? 'selected' : ''}`} style={{ paddingLeft: 12 + row.depth * 14 }}
      onFocus={() => setFocused(item.id)} onKeyDown={event => {
        if ((event.target as HTMLElement).closest('button[aria-haspopup]')) return;
        const move = (id?: string) => { if (id) focus(id); };
        if (event.key === 'ArrowDown') move(rows[index + 1]?.item.id);
        else if (event.key === 'ArrowUp') move(rows[index - 1]?.item.id);
        else if (event.key === 'Home') move(rows[0]?.item.id);
        else if (event.key === 'End') move(rows.at(-1)?.item.id);
        else if (event.key === 'ArrowRight' && row.folder) { if (!expanded) toggle(item.id); else if (rows[index + 1]?.parent === item.id) move(rows[index + 1].item.id); }
        else if (event.key === 'ArrowLeft') { if (expanded) toggle(item.id); else move(row.parent); }
        else if (event.key === 'Enter' || event.key === ' ') select();
        else return;
        event.preventDefault();
      }}>
      {!row.folder && <Icon name="tree-document" />}
      {row.folder && <button className="tree-toggle" tabIndex={-1} aria-label={`${expanded ? '折叠' : '展开'} ${item.name}`} aria-expanded={expanded} onClick={() => toggle(item.id)}><Icon name="tree-folder" /><span aria-hidden="true">{expanded ? '⌄' : '›'}</span></button>}
      <button className="item-name" tabIndex={-1} disabled={!row.folder && blocked} title={item.name} onClick={select} onDoubleClick={() => { if (row.folder) toggle(item.id); }}>{item.name}</button>
      <ActionMenu tabIndex={-1} label={`${item.name}的操作`} actions={row.folder ? folderActions(item) : actions(item)} />
    </div></ContextActions>;
  })}</div>;
}

/** Match Qt's splitter bounds; the narrow window always retains 300px of content. */
export function ResizableSidebar({ preferred, onCommit, children }: { preferred?: number | null; onCommit: (width: number) => Promise<unknown>; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null), [available, setAvailable] = useState(innerWidth);
  const [draft, setDraft] = useState<number | null>(null), drag = useRef<{ x: number; width: number } | null>(null);
  const maximum = Math.max(180, Math.min(420, available - 303));
  const clamp = (value: number) => Math.round(Math.max(180, Math.min(maximum, value)));
  const width = clamp(draft ?? preferred ?? Math.min(250, available * .2));
  useEffect(() => {
    const parent = ref.current?.parentElement;
    if (!parent) return;
    const observer = new ResizeObserver(() => setAvailable(parent.clientWidth)); observer.observe(parent);
    return () => observer.disconnect();
  }, []);
  useEffect(() => { setDraft(null); }, [preferred]);
  const save = (value: number) => { const next = clamp(value); setDraft(next); onCommit(next).catch(() => setDraft(null)); };
  return <><aside ref={ref} className="sidebar" style={{ width }}>{children}</aside><div className="sidebar-splitter" role="separator" aria-label="调整录音库宽度" aria-orientation="vertical"
    aria-valuemin={180} aria-valuemax={maximum} aria-valuenow={width} tabIndex={0}
    onPointerDown={event => { drag.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture(event.pointerId); }}
    onPointerMove={event => { if (drag.current) setDraft(clamp(drag.current.width + event.clientX - drag.current.x)); }}
    onPointerUp={event => { if (drag.current) { const next = drag.current.width + event.clientX - drag.current.x; drag.current = null; event.currentTarget.releasePointerCapture(event.pointerId); save(next); } }}
    onPointerCancel={() => { drag.current = null; setDraft(null); }}
    onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); save(event.key === 'Home' ? 180 : event.key === 'End' ? maximum : width + (event.key === 'ArrowLeft' ? -10 : 10)); } }} /></>;
}
