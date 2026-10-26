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
export function usePageTransition(key: string, navigation = false) {
  const ref = useRef<HTMLDivElement>(null), first = useRef(true), navigationWidth = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (first.current) { first.current = false; return; }
    const root = ref.current;
    if (!root) return;
    const settings = root.querySelector<HTMLElement>('.settings-nav');
    const sidebar = root.querySelector<HTMLElement>('.sidebar');
    const target = settings ?? sidebar;
    // The recording tree stays mounted while settings is shown, preserving its
    // compact state. Read the stored CSS width even while its page is hidden.
    const start = settings && sidebar ? parseFloat(getComputedStyle(sidebar).width) : navigationWidth.current;
    const end = target?.getBoundingClientRect().width;
    navigationWidth.current = end ?? null;
    if (!motionEnabled()) return;
    const effects: Animation[] = [];
    let widthEffect: Animation | undefined;
    if (navigation && sidebar?.classList.contains('compact') && target && start && end) {
      widthEffect = target.animate([{ width: `${start}px` }, { width: `${end}px` }], { duration: 220, easing: outCubicCSS });
      effects.push(widthEffect);
      const content = root.querySelector(settings ? '.settings-content' : '.workspace');
      if (content) effects.push(content.animate([{ opacity: .35 }, { opacity: 1 }], { duration: 220, easing: outCubicCSS }));
    } else effects.push(root.animate([{ opacity: .35 }, { opacity: 1 }], { duration: 150, easing: outCubicCSS }));
    const observer = new MutationObserver(() => { if (!motionEnabled()) effects.forEach(effect => effect.cancel()); });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduced-motion'] });
    return () => {
      if (navigation && target) {
        const progress = widthEffect ? Math.min(1, Number(widthEffect.currentTime ?? 220) / 220) : 1;
        navigationWidth.current = target.getBoundingClientRect().width || (start && end ? start + (end - start) * outCubic(progress) : end ?? null);
      }
      effects.forEach(effect => effect.cancel()); observer.disconnect();
    };
  }, [key, navigation]);
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
