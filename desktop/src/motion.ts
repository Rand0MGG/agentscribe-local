import { useEffect, useLayoutEffect, useRef, useState } from 'react';

export const outCubic = (t: number) => 1 - (1 - t) ** 3;
export const inOutCubic = (t: number) => t < .5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;
export const outCubicCSS = `linear(${Array.from({ length: 41 }, (_, i) => outCubic(i / 40).toFixed(6)).join(',')})`;
export function motionEnabled() {
  return document.documentElement.dataset.reducedMotion !== 'true' && !matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Qt QVariantAnimation semantics: interrupt at the current value, never queue. */
export function useTween(target: number, duration: number, curve = outCubic) {
  const [value, setValue] = useState(target), current = useRef(target);
  useLayoutEffect(() => {
    let frame = 0;
    const start = current.current, began = performance.now();
    if (start === target) return;
    const advance = (now: number) => {
      const fraction = motionEnabled() ? Math.min(1, (now - began) / duration) : 1;
      current.current = start + (target - start) * curve(fraction);
      setValue(current.current);
      if (fraction < 1) frame = requestAnimationFrame(advance);
    };
    advance(began);
    return () => cancelAnimationFrame(frame);
  }, [target, duration, curve]);
  return value;
}

/** Reuse a single effect; rapid page changes cancel the old fade. */
export function usePageTransition(key: string) {
  const ref = useRef<HTMLDivElement>(null), first = useRef(true);
  useLayoutEffect(() => {
    if (first.current) { first.current = false; return; }
    if (!motionEnabled()) return;
    const effect = ref.current?.animate([{ opacity: .35 }, { opacity: 1 }], { duration: 150, easing: outCubicCSS });
    const observer = new MutationObserver(() => { if (!motionEnabled()) effect?.cancel(); });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduced-motion'] });
    return () => { effect?.cancel(); observer.disconnect(); };
  }, [key]);
  return ref;
}

export function useMaterial(appearance: string) {
  const [material, setMaterial] = useState<{ appearance: string; image: string; width: number; height: number; x: number; y: number } | null>(null);
  useEffect(() => {
    const bridge = window.agentScribe;
    bridge?.request('material.get').then(setMaterial).catch(() => {});
    return bridge?.subscribe(({ event, data }) => { if (event === 'material') setMaterial(data); });
  }, []);
  return material?.appearance === appearance ? { backgroundImage: `url("${material.image}")`, backgroundSize: `${material.width}px ${material.height}px`, backgroundPosition: `${material.x}px ${material.y}px` } : {};
}
