import { useRef, type ReactNode } from 'react';
import type { TransportGeometry } from './Transport';
import { inOutCubic, useTween } from './motion';

/** Same bottom anchor, target geometry and clipped row reveal as FloatingIsland. */
export function RecordingIsland({ active, status, children, geometry }: { geometry?: TransportGeometry; active: boolean; status: ReactNode; children: ReactNode }) {
  const progress = useTween(Number(active), 280, inOutCubic);
  const width = geometry?.width ?? 210 + 78 * progress, height = geometry?.height ?? 58 + 26 * progress;
  return <div className={`control-island ${active ? 'active' : ''}`} style={{ width, height, transform: `translateX(${geometry?.offset || 0}px)` }}>
    <div className="island-inner" style={{ width: active ? 286 : 208 }}>
      {active && <div className="capture-status" style={{ visibility: height >= 79 ? 'visible' : 'hidden' }}>{status}</div>}
      <div className="island-controls">{children}</div>
    </div>
  </div>;
}

export function LevelMeter({ rms }: { rms: number }) {
  const target = Number.isFinite(rms) && rms > 0 ? Math.round(Math.max(0, Math.min(100, (20 * Math.log10(rms) + 72) / 72 * 100))) : 0;
  const transition = useRef({ target, duration: 80 });
  if (target !== transition.current.target) transition.current = { target, duration: target > transition.current.target ? 80 : 180 };
  const animated = useTween(target, transition.current.duration);
  const value = target === 0 ? 0 : animated;
  return <span className="input-meter" role="meter" aria-label="输入电平" aria-valuemin={0} aria-valuemax={100} aria-valuenow={target}>
    <span style={{ width: `${value}%`, background: `var(--${target > 96 ? 'warning' : 'focus'})` }} />
  </span>;
}
