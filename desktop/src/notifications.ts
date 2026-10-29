import { useCallback, useEffect, useState } from 'react';

export type Notice = { text: string; error?: boolean; busy?: boolean; persistent?: boolean; key?: string; expires?: number };
/** Same lifetime and priority rules as the Qt NotificationCenter. */
export function useNotifications() {
  const [entries, setEntries] = useState<Map<string, Notice>>(new Map());
  const [, refresh] = useState(0);
  const now = Date.now();
  // Only wake at an actual expiry. A permanent task must not repaint the entire
  // caption workspace every 500 ms while its progress animation is running.
  useEffect(() => {
    const expiry = Math.min(...[...entries.values()].map(value => value.expires ?? Infinity).filter(value => value > Date.now()));
    if (!Number.isFinite(expiry)) return;
    const timer = setTimeout(() => refresh(value => value + 1), Math.max(0, expiry - Date.now()) + 1);
    return () => clearTimeout(timer);
  }, [entries, now]);
  const post = useCallback((value: Notice | null, key = value?.key || 'operation') => {
    setEntries(old => {
      const next = new Map(old), previous = old.get(key);
      if (!value) { next.delete(key); return next; }
      if (key === 'operation' && previous?.error && !value.error) return old;
      if (previous && previous.text === value.text && !!previous.busy === !!value.busy && !!previous.error === !!value.error && !!previous.persistent === !!value.persistent) return old;
      const persistent = value.persistent || value.busy || value.error && ['save', 'updates', 'session', 'knowledge', 'preparation-result'].includes(key);
      const expires = previous?.busy && value.busy ? previous.expires : persistent ? Infinity : Date.now() + (value.error ? 8000 : 5000);
      next.delete(key); next.set(key, { ...value, key, expires });
      return next;
    });
  }, []);
  const dismiss = useCallback((key: string) => setEntries(old => {
    const next = new Map(old), value = next.get(key);
    if (value) next.set(key, { ...value, expires: 0 });
    return next;
  }), []);
  const visible = [...entries.values()].reverse().filter(value => (value.expires ?? Infinity) > now);
  const priority = (value: Notice) => value.error ? 2 : value.busy ? 1 : 0;
  visible.sort((a, b) => priority(b) - priority(a));
  return { notice: visible[0], post, dismiss };
}
