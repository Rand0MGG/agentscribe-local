import { useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode, type ButtonHTMLAttributes } from 'react';
import { Dialog, DropdownMenu, ContextMenu, Select, Switch, Tooltip, Slider, Popover } from 'radix-ui';
import { bridge } from './types';
import { useTween } from './motion';

export function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    new: <><rect x="3" y="3" width="14" height="14" rx="3" /><path d="M10 6v8M6 10h8" /></>,
    folder: <path d="M3 5h5l2 2h7v10H3zM3 9h14" />,
    source: <><rect x="3" y="3" width="14" height="10" rx="2" /><path d="M10 13v4M7 17h6" /></>,
    microphone: <><rect x="7" y="2" width="6" height="11" rx="3" /><path d="M4 9v1a6 6 0 0 0 12 0V9M10 16v3M7 19h6" /></>,
    language: <><circle cx="10" cy="10" r="7" /><ellipse cx="10" cy="10" rx="3" ry="7" /><path d="M3 10h14" /></>,
    play: <path d="m7 4 9 6-9 6z" fill="currentColor" stroke="none" />,
    pause: <path d="M7 5v10M13 5v10" strokeWidth="3" />,
    stop: <rect x="5" y="5" width="10" height="10" rx="1" fill="currentColor" stroke="none" />,
    volume: <><path d="M3 8h3l4-3v10l-4-3H3zM13 7q4 3 0 6M15 4q7 6 0 12" /></>,
    'tree-folder': <><rect x="0" y="5" width="15" height="11" rx="2" /><path d="M1 3h6" /></>,
    'tree-document': <><rect x="0" y="3" width="11" height="14" rx="2" /><path d="M3 8h5M3 12h5" /></>,
    document: <><rect x="5" y="3" width="10" height="14" rx="2" /><path d="M8 7h4M8 10h4M8 13h4" /></>,
    download: <path d="M10 3v10m-4-4 4 4 4-4M3 14v3h14v-3" />,
    trash: <><path d="M3 5h14M8 3h4M5 5l1 12h8l1-12M8 8v6M12 8v6" /></>,
    settings: <><path d="M3 5h14M3 10h14M3 15h14" /><circle cx="7" cy="5" r="2" /><circle cx="13" cy="10" r="2" /><circle cx="8" cy="15" r="2" /></>,
  };
  return <svg aria-hidden="true" width="20" height="20" viewBox={name.startsWith('tree-') ? '0 0 16 20' : '0 0 20 20'} fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

// Sibling toolbar menus share one owner; nested Select controls stay within their popover.
let popupOwner: string | null = null;
const popupListeners = new Set<() => void>();
function publishPopup(owner: string | null) {
  if (popupOwner === owner) return;
  popupOwner = owner; popupListeners.forEach(listener => listener());
}
function usePopup() {
  const id = useId();
  const owner = useSyncExternalStore(listener => { popupListeners.add(listener); return () => { popupListeners.delete(listener); }; }, () => popupOwner);
  useEffect(() => () => { if (popupOwner === id) publishPopup(null); }, [id]);
  return { open: owner === id, onOpenChange: (open: boolean) => { if (open) publishPopup(id); else if (popupOwner === id) publishPopup(null); },
    onCloseAutoFocus: (event: Event) => { if (popupOwner !== null && popupOwner !== id) event.preventDefault(); } };
}

export function ControlPopover({ label, icon, children, disabled = false }: { label: string; icon: string; children: ReactNode; disabled?: boolean }) {
  const { onCloseAutoFocus, ...popup } = usePopup();
  return <Popover.Root {...popup}><Tip label={label}><Popover.Trigger asChild><Button variant="quiet" className="icon-button" aria-label={label} disabled={disabled}><Icon name={icon} /></Button></Popover.Trigger></Tip>
    <Popover.Portal><Popover.Content onCloseAutoFocus={onCloseAutoFocus} className="popup control-popup" side="top" sideOffset={10} collisionPadding={8} aria-label={label}>
      {children}
    </Popover.Content></Popover.Portal></Popover.Root>;
}

export function Button({ variant = 'secondary', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'secondary' | 'primary' | 'quiet' | 'danger';
}) { return <button type="button" {...((props.className || '').match(/icon-button|transport-button/) ? { tabIndex: -1 } : {})} {...props} className={`button ${variant} ${props.className || ''}`} />; }

export function Tip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => { if (open) { const timer = setTimeout(() => setOpen(false), 8000); return () => clearTimeout(timer); } }, [open]);
  return <Tooltip.Root open={open} onOpenChange={setOpen}><Tooltip.Trigger asChild>{children}</Tooltip.Trigger><Tooltip.Portal>
    <Tooltip.Content className="tooltip" sideOffset={6}>{label}</Tooltip.Content>
  </Tooltip.Portal></Tooltip.Root>;
}

/** The island opens the choice list directly, as in the Qt ChoiceBox. */
export function IconMenu({ label, icon, value, options, onChange, disabled, refresh, refreshing = false, refreshStatus = '' }: {
  label: string; icon: string; value: string; options: { value: string; label: string }[];
  onChange: (value: string) => void; disabled?: boolean; refresh?: () => void; refreshing?: boolean; refreshStatus?: string;
}) {
  const { onCloseAutoFocus, ...popup } = usePopup();
  return <DropdownMenu.Root {...popup} modal={false}><Tip label={label}><DropdownMenu.Trigger asChild><Button variant="quiet" className="icon-button" aria-label={label} disabled={disabled}><Icon name={icon} /></Button></DropdownMenu.Trigger></Tip>
    <DropdownMenu.Portal><DropdownMenu.Content onCloseAutoFocus={onCloseAutoFocus} className="popup action-menu source-menu" side="top" sideOffset={10} collisionPadding={8}>
      <DropdownMenu.RadioGroup value={value} onValueChange={onChange}>{options.map(option => <DropdownMenu.RadioItem key={option.value} value={option.value} className="menu-item">{option.label}<DropdownMenu.ItemIndicator>✓</DropdownMenu.ItemIndicator></DropdownMenu.RadioItem>)}</DropdownMenu.RadioGroup>
      {refresh && <><DropdownMenu.Separator className="menu-separator" />{refreshStatus && <p className="source-status" role="status">{refreshStatus}</p>}<DropdownMenu.Item className="menu-item" disabled={refreshing} onSelect={refresh}>{refreshing ? '正在刷新…' : '刷新音频来源'}</DropdownMenu.Item></>}
    </DropdownMenu.Content></DropdownMenu.Portal>
  </DropdownMenu.Root>;
}

export function Choice({ label, value, options, onChange, disabled = false, className = '' }: {
  className?: string; label: string; value: string; options: { value: string; label: string; disabled?: boolean }[];
  onChange: (value: string) => void; disabled?: boolean;
}) {
  return <Select.Root value={value || undefined} onValueChange={onChange} disabled={disabled}>
    <Select.Trigger className={`choice ${className}`} aria-label={label}><Select.Value placeholder={label} /><Select.Icon>⌄</Select.Icon></Select.Trigger>
    <Select.Portal><Select.Content className="popup choice-popup" position="popper" sideOffset={5} collisionPadding={8}>
      <Select.ScrollUpButton className="scroll-option">⌃</Select.ScrollUpButton><Select.Viewport>
        {options.map(option => <Select.Item key={option.value} value={option.value} disabled={option.disabled} className="choice-item">
          <Select.ItemText>{option.label}</Select.ItemText><Select.ItemIndicator>✓</Select.ItemIndicator>
        </Select.Item>)}
      </Select.Viewport><Select.ScrollDownButton className="scroll-option">⌄</Select.ScrollDownButton>
    </Select.Content></Select.Portal>
  </Select.Root>;
}

export function Toggle({ label, value, onChange, disabled }: {
  label: string; value: boolean; onChange: (value: boolean) => void; disabled?: boolean;
}) { const progress = useTween(Number(value), 150); return <Switch.Root className="switch" aria-label={label} checked={value} disabled={disabled} onCheckedChange={onChange} style={{ background: `color-mix(in srgb,var(--primary) ${progress * 100}%,var(--disabled))` }}>
  <Switch.Thumb className="switch-thumb" style={{ transform: `translateX(${16 * progress}px)` }} />
</Switch.Root>; }

export type MenuAction = { label: string; run: () => void; disabled?: boolean; danger?: boolean };
export function ContextActions({ children, actions }: { children: ReactNode; actions: MenuAction[] }) {
  return <ContextMenu.Root><ContextMenu.Trigger asChild>{children}</ContextMenu.Trigger><ContextMenu.Portal><ContextMenu.Content className="popup action-menu" collisionPadding={8}>{actions.map(action => <ContextMenu.Item key={action.label} className={`menu-item ${action.danger ? 'danger' : ''}`} disabled={action.disabled} onSelect={action.run}>{action.label}</ContextMenu.Item>)}</ContextMenu.Content></ContextMenu.Portal></ContextMenu.Root>;
}
export function ActionMenu({ label = '更多操作', actions, tabIndex }: { label?: string; actions: MenuAction[]; tabIndex?: number }) {
  const { onCloseAutoFocus, ...popup } = usePopup();
  return <DropdownMenu.Root {...popup} modal={false}><DropdownMenu.Trigger asChild><Button variant="quiet" tabIndex={tabIndex} aria-label={label}>···</Button></DropdownMenu.Trigger>
    <DropdownMenu.Portal><DropdownMenu.Content onCloseAutoFocus={onCloseAutoFocus} className="popup action-menu" sideOffset={5} collisionPadding={8}>
      {actions.map(action => <DropdownMenu.Item key={action.label} className={`menu-item ${action.danger ? 'danger' : ''}`}
        onSelect={action.run} disabled={action.disabled}>{action.label}</DropdownMenu.Item>)}
    </DropdownMenu.Content></DropdownMenu.Portal>
  </DropdownMenu.Root>;
}

export function Modal({ title, description, open, onClose, children, actions, width = 428, height, modal = true }: {
  height?: number; modal?: boolean; width?: number; title: string; description?: string; open: boolean; onClose: () => void; children: ReactNode; actions?: ReactNode;
}) {
  const returnTarget = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null);
  const composing = useRef(false);
  return <Dialog.Root modal={modal} open={open} onOpenChange={value => { if (!value) onClose(); }}><Dialog.Portal>
    <Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog" style={{width: `min(${width}px,calc(100vw - 32px))`, height: height ? `min(${height}px,calc(100dvh - 40px))` : undefined}} {...(!description ? { 'aria-describedby': undefined } : {})}
      onCompositionStartCapture={() => { composing.current = true; }} onCompositionEndCapture={() => { composing.current = false; }}
      onCloseAutoFocus={event => { event.preventDefault(); const active = document.activeElement; if (active instanceof HTMLElement && active !== document.body && active.isConnected) return; if (returnTarget.current?.isConnected) returnTarget.current.focus(); }}
      onPointerDownOutside={event => event.preventDefault()} onInteractOutside={event => event.preventDefault()}
      onEscapeKeyDown={event => { if (event.isComposing || composing.current) event.preventDefault(); }}>
      <div className="dialog-heading"><div><Dialog.Title>{title}</Dialog.Title>{description && <Dialog.Description>{description}</Dialog.Description>}</div><Dialog.Close asChild><Button variant="quiet" className="dialog-close" aria-label={`关闭${title}`}>×</Button></Dialog.Close></div>
      <div className="dialog-body" style={height ? {flex:1} : undefined}>{children}</div><div className="dialog-actions">{actions || <Button onClick={onClose}>关闭</Button>}</div>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>;
}

export function EditDialog({ title, initial = '', confirm = '保存', onClose, onSave, trackEdit = true }: {
  title: string; initial?: string; confirm?: string; trackEdit?: boolean; onClose: () => void; onSave: (text: string) => Promise<unknown>;
}) {
  const [text, setText] = useState(initial), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!trackEdit) return;
    bridge?.request('window.edited', { owner: 'name', dirty: text !== initial }).catch(() => {});
    return () => { bridge?.request('window.edited', { owner: 'name', dirty: false }).catch(() => {}); };
  }, [text, initial, trackEdit]);
  const id = useId();
  async function save() {
    if (!text.trim()) { setError('请输入名称。'); return; }
    setBusy(true); setError('');
    try { await onSave(text.trim()); onClose(); } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  }
  return <Modal title={title} open onClose={() => { if (!busy) onClose(); }} actions={<>
    <Button disabled={busy} onClick={onClose}>取消</Button><Button variant="primary" disabled={busy} onClick={save}>{busy ? '正在保存…' : confirm}</Button>
  </>}><label className="sr-only" htmlFor={id}>名称</label><input id={id} value={text} maxLength={64} autoFocus
    onChange={event => setText(event.target.value)} aria-invalid={!!error} aria-describedby={error ? `${id}-error` : undefined} />
    {error && <p id={`${id}-error`} className="error" role="alert">{error}</p>}
  </Modal>;
}

export function InlineTitle({ value, disabled, onSave }: { value: string; disabled: boolean; onSave: (value: string) => Promise<unknown> }) {
  const [editing, setEditing] = useState(false), [text, setText] = useState(value), [error, setError] = useState('');
  const submitting = useRef(false), cancelled = useRef(false), composing = useRef(false);
  useEffect(() => {
    bridge?.request('window.edited', { owner: 'name', dirty: editing && text !== value }).catch(() => {});
    return () => { bridge?.request('window.edited', { owner: 'name', dirty: false }).catch(() => {}); };
  }, [editing, text, value]);
  async function save() {
    if (submitting.current || cancelled.current || composing.current) return;
    if (!text.trim()) { setError('请输入名称。'); return; }
    submitting.current = true;
    try { if (text.trim() !== value) await onSave(text.trim()); setEditing(false); }
    catch (error) { setError((error as Error).message); }
    finally { submitting.current = false; }
  }
  return <div className="title-editor">{editing ? <input aria-label="录音名称" autoFocus maxLength={64} value={text} onChange={event => setText(event.target.value)}
    onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onBlur={save}
    onKeyDown={event => { if (composing.current || event.nativeEvent.isComposing) return; if (event.key === 'Enter') { event.preventDefault(); save(); } if (event.key === 'Escape') { cancelled.current = true; setEditing(false); setError(''); } }} /> :
    <button className="recording-title" title={value} disabled={disabled} onClick={() => { cancelled.current = false; setText(value); setError(''); setEditing(true); }}>{value}</button>}{error && <p role="alert" className="error">{error}</p>}</div>;
}

export function ConfirmDialog({ title, description, confirm, onClose, onConfirm }: {
  title: string; description: string; confirm: string; onClose: () => void; onConfirm: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  return <Modal title={title} description={description} open onClose={() => { if (!busy) onClose(); }} actions={<>
    <Button disabled={busy} onClick={onClose}>取消</Button><Button variant="danger" disabled={busy} onClick={async () => {
      setBusy(true); try { await onConfirm(); onClose(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
    }}>{busy ? '正在处理…' : confirm}</Button></>}><p role="alert" className="error">{error}</p></Modal>;
}

export function Range({ label, value, max, min = 0, step = 1, orientation = 'horizontal', onChange, onCommit }: {
  label: string; value: number; max: number; min?: number; step?: number; onChange: (value: number) => void; onCommit?: (value: number) => void;
  orientation?: 'horizontal' | 'vertical';
}) { return <Slider.Root className="slider" orientation={orientation} aria-label={label} value={[value]} min={min} max={Math.max(min+1, max)} step={step}
  onValueChange={values => onChange(values[0])} onValueCommit={values => onCommit?.(values[0])}>
  <Slider.Track className="slider-track"><Slider.Range className="slider-range" /></Slider.Track><Slider.Thumb className="slider-thumb" aria-label={label} />
</Slider.Root>; }

export function SettingsRow({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return <div className="settings-row"><div><div className="settings-label">{title}</div>{hint && <p>{hint}</p>}</div><div className="settings-control">{children}</div></div>;
}

/** Keep the edited text separate from the last acknowledged setting. */
export function NumberField({ id, label, value, min, max, step, help, onCommit }: {
  id?: string; label: string; value: number; min: number; max: number; step: number; help?: string;
  onCommit: (value: number) => void | Promise<unknown>;
}) {
  const generated = useId(), fieldId = id || generated;
  const [text, setText] = useState(String(value)), [error, setError] = useState(''), [saving, setSaving] = useState(false);
  const editing = useRef(false);
  useEffect(() => { if (!editing.current) setText(String(value)); }, [value]);
  async function save() {
    editing.current = false;
    const number = Number(text);
    // Qt's singleStep controls the arrows, not which in-range values can be typed.
    if (!text.trim() || !Number.isFinite(number) || number < min || number > max) {
      setText(String(value)); setError(`请输入 ${min}–${max} 秒。已恢复原值。`); return;
    }
    if (number === value) { setError(''); return; }
    setSaving(true);
    try { await onCommit(number); setError(''); }
    catch (error) { setText(String(value)); setError(`未保存：${(error as Error).message}`); }
    finally { setSaving(false); }
  }
  return <div className="numeric-control"><div className="number-field"><input id={fieldId} aria-label={label} type="number" min={min} max={max} step={step} value={text} disabled={saving}
    title={help} aria-invalid={!!error} aria-describedby={error ? `${fieldId}-error` : help ? `${fieldId}-help` : undefined}
    onFocus={() => { editing.current = true; }} onChange={event => { setText(event.target.value); setError(''); }} onBlur={save}
    onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') { setText(String(value)); setError(''); editing.current = false; } }} /><span>秒</span></div>
    {help && <span className="sr-only" id={`${fieldId}-help`}>{help}</span>}{error && <p className="error" role="alert" id={`${fieldId}-error`}>{error}</p>}
  </div>;
}
