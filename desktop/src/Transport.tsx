import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { inOutCubic, useTween } from './motion';

export type TransportGeometry = { width: number; height: number; offset: number };
/** One geometry owner survives transitions between idle, recording and playback. */
export function Transport({ active, playback, children }: { active: boolean; playback: boolean; children: (geometry: TransportGeometry) => ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(() => innerWidth - Math.max(180, Math.min(250, innerWidth * .2)) - 35);
  const [gutter, setGutter] = useState(0);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const captions = node.parentElement?.querySelector<HTMLElement>('.caption-scroll');
    const observer = new ResizeObserver(() => {
      if (!node.clientWidth) return;
      setAvailable(node.clientWidth - 32);
      if (captions) setGutter(captions.offsetWidth - captions.clientWidth);
    });
    observer.observe(node);
    if (captions) observer.observe(captions);
    return () => observer.disconnect();
  }, []);
  const width = useTween(playback ? Math.min(640, available - 68) : active ? 288 : 210, 280, inOutCubic);
  const height = useTween(active ? 84 : 58, 280, inOutCubic);
  const offset = useTween(playback ? -34 : 0, 280, inOutCubic);
  return <div className="transport-area" ref={ref} style={{right:gutter}}>{children({ width, height, offset })}</div>;
}
