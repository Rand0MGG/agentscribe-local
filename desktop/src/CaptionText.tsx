import { useLayoutEffect, useRef, useState } from 'react';

/** Preserve complete selectable text/layout while revealing appended graphemes. */
export function CaptionText({ text, animate }: { text: string; animate: boolean }) {
  const previous = useRef(''), current = useRef(text), started = useRef(0), deadline = useRef(0), from = useRef(0), frame = useRef(0);
  const [visible, setVisible] = useState(text.length);
  const count = useRef(text.length);
  current.current = text;
  function finish() {
    cancelAnimationFrame(frame.current); frame.current = 0; deadline.current = 0;
    count.current = current.current.length; setVisible(count.current);
  }
  useLayoutEffect(() => {
    const old = previous.current; previous.current = text;
    const reduced = () => document.documentElement.dataset.reducedMotion === 'true' || matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!animate || reduced() || !text.startsWith(old)) { finish(); return; }
    if (text === old) return;
    const now = performance.now();
    if (!deadline.current || now >= deadline.current) {
      from.current = old.length; count.current = old.length; setVisible(old.length);
      started.current = now; deadline.current = now + Math.min(320, Math.max(80, (text.length - old.length) * 16));
    }
    cancelAnimationFrame(frame.current);
    const boundaries = [0, ...Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text), row => row.index + row.segment.length)];
    // An appended combining mark or joiner can extend the previously visible
    // grapheme. Never split it at the old UTF-16 text length.
    let previousBoundary = 0;
    for (const value of boundaries) { if (value > count.current) break; previousBoundary = value; }
    count.current = previousBoundary; setVisible(previousBoundary);
    function tick(now: number) {
      if (now >= deadline.current || reduced() || document.hidden) { finish(); return; }
      const target = from.current + (text.length - from.current) * (now - started.current) / (deadline.current - started.current);
      let boundary = 0;
      for (const value of boundaries) { if (value > target) break; boundary = value; }
      count.current = Math.max(count.current, boundary); setVisible(count.current);
      frame.current = requestAnimationFrame(tick);
    }
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [text, animate]);
  return <span onMouseDownCapture={finish}>{text.slice(0, visible)}<span style={{ opacity: 0 }}>{text.slice(visible)}</span></span>;
}
