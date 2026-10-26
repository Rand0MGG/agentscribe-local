import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ActionMenu, Button, ContextActions, Icon, Tip, type MenuAction } from './components';
import { bridge, request, type Item, type Library } from './types';

const SidebarContext = createContext({ compact: false, toggle: () => {} });

export function SidebarToggle() {
  const { compact, toggle } = useContext(SidebarContext);
  const label = compact ? '展开侧边栏' : '收起侧边栏';
  return <Button className="navigation sidebar-action sidebar-toggle" variant="quiet" aria-label={label} title={label} aria-expanded={!compact} aria-controls="recording-sidebar" onClick={toggle}>
    <Icon name={compact ? 'sidebar-expand' : 'sidebar-collapse'} /><span className="sidebar-label">{label}</span>
  </Button>;
}

export function LibraryTree({ library, current, folder, blocked, onOpen, onFolder, actions, folderActions }: {
  library: Library; current?: string; folder: string; blocked: boolean; onOpen: (item: Item) => Promise<boolean>;
  onFolder: (id: string) => void; actions: (item: Item) => MenuAction[]; folderActions: (item: Item) => MenuAction[];
}) {
  const [collapsed, setCollapsed] = useState(new Set<string>()), [focused, setFocused] = useState(current || folder);
  const sidebar = useContext(SidebarContext);
  const tree = useRef<HTMLDivElement>(null);
  const rows: { item: Item; folder: boolean; depth: number; parent?: string }[] = [];
  function collect(parent: string | null = null, depth = 0, seen = new Set<string>()) {
    for (const item of library.folders.filter(item => (item.parent || null) === parent)) {
      if (seen.has(item.id)) continue;
      seen.add(item.id); rows.push({ item, folder: true, depth, parent: parent || undefined });
      if (!sidebar.compact && !collapsed.has(item.id)) {
        for (const recording of library.sessions.filter(row => row.folder === item.id)) rows.push({ item: recording, folder: false, depth: depth + 1, parent: item.id });
        collect(item.id, depth + 1, seen);
      }
    }
  }
  collect();
  let target: string | undefined = focused;
  const ancestors = new Set<string>();
  while (target && !rows.some(row => row.item.id === target) && !ancestors.has(target)) {
    ancestors.add(target);
    target = library.sessions.find(item => item.id === target)?.folder || library.folders.find(item => item.id === target)?.parent || undefined;
  }
  if (!rows.some(row => row.item.id === target)) target = rows[0]?.item.id;
  useEffect(() => { if (!tree.current?.contains(document.activeElement)) setFocused(current || folder); }, [current, folder]);
  function focus(id: string) {
    setFocused(id);
    requestAnimationFrame(() => tree.current?.querySelector<HTMLElement>(`[data-library-id="${CSS.escape(id)}"]`)?.focus());
  }
  function toggle(id: string) { if (sidebar.compact) return; setCollapsed(old => { const next = new Set(old); if (next.has(id)) next.delete(id); else next.add(id); return next; }); }
  return <div ref={tree} role="tree" aria-label="录音文件夹" className="library-tree">{rows.map((row, index) => {
    const { item } = row, expanded = row.folder && !sidebar.compact && !collapsed.has(item.id);
    const select = async () => {
      if (row.folder) { setFocused(item.id); onFolder(item.id); }
      else if (!blocked) { const opened = await onOpen(item); setFocused(opened ? item.id : current || folder); }
    };
    const name = <button className="item-name" tabIndex={-1} aria-label={item.name} disabled={!row.folder && blocked} title={row.folder ? undefined : item.name} onClick={select} onDoubleClick={() => { if (row.folder) toggle(item.id); }}>{row.folder && <span className="compact-folder-icon"><Icon name="tree-folder" /></span>}<span className="sidebar-label">{item.name}</span></button>;
    return <ContextActions key={item.id} actions={row.folder ? folderActions(item) : actions(item)}><div
      role="treeitem" aria-label={item.name} data-library-id={item.id} aria-level={row.depth + 1} aria-selected={target === item.id}
      aria-expanded={row.folder ? expanded : undefined} tabIndex={target === item.id ? 0 : -1}
      aria-disabled={!row.folder && blocked ? true : undefined}
      className={`library-row ${row.folder ? 'folder' : ''} ${target === item.id ? 'selected' : ''}`} style={{ paddingLeft: 8 + row.depth * 14 }}
      onMouseDown={event => { if (!row.folder && blocked && event.button === 0) event.preventDefault(); }}
      onClick={event => { if (!(event.target as HTMLElement).closest('button')) select(); }}
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
      {row.folder ? <Tip label={item.name} side="right">{name}</Tip> : name}
      <ActionMenu tabIndex={-1} label={`${item.name}的操作`} actions={row.folder ? folderActions(item) : actions(item)} />
    </div></ContextActions>;
  })}</div>;
}

/** Responsive presentation never overwrites the user's expanded width. */
export function ResizableSidebar({ preferred, onCommit, children }: { preferred?: number | null; onCommit: (width: number) => Promise<unknown>; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null), [available, setAvailable] = useState(innerWidth);
  const [folded, setFolded] = useState(false), splitLayout = useRef(false);
  const [draft, setDraft] = useState<number | null>(null), drag = useRef<{ x: number; width: number } | null>(null);
  const maximum = Math.max(180, Math.min(420, available - 303));
  const clamp = (value: number) => Math.round(Math.max(180, Math.min(maximum, value)));
  const width = clamp(draft ?? preferred ?? Math.min(250, available * .2));
  useEffect(() => {
    const parent = ref.current?.parentElement;
    if (!parent) return;
    const observer = new ResizeObserver(() => {
      const width = parent.clientWidth;
      if (!width) return; // Hidden settings/workspace pages must retain their mode.
      setAvailable(width);
    }); observer.observe(parent);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let live = true, received = false;
    const update = (split: boolean) => {
      if (!live) return;
      if (split && !splitLayout.current) setFolded(true);
      splitLayout.current = split;
    };
    const unsubscribe = bridge?.subscribe(({ event, data }) => {
      if (event === 'window-layout') { received = true; update(data.split); }
    });
    request<{ split: boolean }>('window.layout').then(value => { if (!received) update(value.split); }).catch(() => {});
    return () => { live = false; unsubscribe?.(); };
  }, []);
  useEffect(() => { setDraft(null); }, [preferred]);
  useEffect(() => { if (folded) { drag.current = null; setDraft(null); } }, [folded]);
  const save = (value: number) => { const next = clamp(value); setDraft(next); onCommit(next).catch(() => setDraft(null)); };
  return <><aside ref={ref} id="recording-sidebar" aria-label="录音库" className={`sidebar${folded ? ' compact' : ''}${drag.current ? ' resizing' : ''}`} style={{ width: folded ? 'var(--titlebar-height)' : width }}><SidebarContext.Provider value={{ compact: folded, toggle: () => setFolded(!folded) }}>{children}</SidebarContext.Provider></aside><div hidden={folded} className="sidebar-splitter" role="separator" aria-label="调整录音库宽度" aria-orientation="vertical"
    aria-valuemin={180} aria-valuemax={maximum} aria-valuenow={width} tabIndex={0}
    onPointerDown={event => { drag.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture(event.pointerId); }}
    onPointerMove={event => { if (drag.current) setDraft(clamp(drag.current.width + event.clientX - drag.current.x)); }}
    onPointerUp={event => { if (drag.current) { const next = drag.current.width + event.clientX - drag.current.x; drag.current = null; event.currentTarget.releasePointerCapture(event.pointerId); save(next); } }}
    onPointerCancel={() => { drag.current = null; setDraft(null); }}
    onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); save(event.key === 'Home' ? 180 : event.key === 'End' ? maximum : width + (event.key === 'ArrowLeft' ? -10 : 10)); } }} /></>;
}
