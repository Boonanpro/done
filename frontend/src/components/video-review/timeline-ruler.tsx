'use client';

import { memo, useEffect, useState, type RefObject } from 'react';

/** タイムラインの上の目盛り。押す・引きずると再生位置が動く（他の編集ソフトの時間の物差しと同じ）。
 *  スクロールやズームで描き直すのはこの部品だけ。見えている範囲の目盛りだけを作る。 */
function label(t: number, step: number): string {
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  const ss = step < 1 ? sec.toFixed(1).padStart(4, '0') : String(Math.floor(sec)).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

const STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];

export const TimelineRuler = memo(function TimelineRuler({
  scrollRef,
  trackRef,
  headRef,
  duration,
  zoom,
  onScrubStart,
}: {
  scrollRef: RefObject<HTMLDivElement | null>;
  trackRef: RefObject<HTMLDivElement | null>;
  headRef: RefObject<HTMLDivElement | null>;
  duration: number;
  zoom: number;
  onScrubStart: (clientX: number) => void;
}) {
  const [view, setView] = useState({ left: 0, width: 0, trackW: 0, trackX: 0 });
  useEffect(() => {
    const sc = scrollRef.current;
    const tr = trackRef.current;
    if (!sc || !tr) return;
    let raf = 0;
    const update = () => {
      raf = 0;
      const trackX = tr.getBoundingClientRect().left - sc.getBoundingClientRect().left + sc.scrollLeft;
      setView((v) => {
        const next = { left: sc.scrollLeft, width: sc.clientWidth, trackW: tr.offsetWidth, trackX };
        return v.left === next.left && v.width === next.width && v.trackW === next.trackW && v.trackX === next.trackX ? v : next;
      });
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(update); };
    update();
    sc.addEventListener('scroll', schedule, { passive: true });
    const ro = new ResizeObserver(schedule);
    ro.observe(sc);
    ro.observe(tr);
    return () => {
      sc.removeEventListener('scroll', schedule);
      ro.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [scrollRef, trackRef, zoom, duration]);

  const pps = duration > 0 && view.trackW > 0 ? view.trackW / duration : 0;
  const step = pps ? STEPS.find((s) => s * pps >= 72) || 3600 : 0;
  const ticks: number[] = [];
  if (step) {
    const from = Math.max(0, Math.floor((view.left - view.trackX) / pps / step) * step);
    const to = Math.min(duration, (view.left - view.trackX + view.width) / pps + step);
    for (let t = from; t <= to + 1e-6 && ticks.length < 400; t += step) ticks.push(Number(t.toFixed(3)));
  }
  const minor = step && pps ? (step * pps) / 5 : 0;

  return (
    <div
      data-timeline-ruler
      className="relative h-5 cursor-ew-resize select-none overflow-hidden rounded-sm border-b border-white/15 bg-neutral-900/90"
      style={{
        width: `${zoom * 100}%`,
        minWidth: '100%',
        backgroundImage: minor >= 6 ? 'linear-gradient(90deg, rgba(255,255,255,0.18) 1px, transparent 1px)' : undefined,
        backgroundSize: minor >= 6 ? `${minor}px 5px` : undefined,
        backgroundRepeat: 'repeat-x',
        backgroundPosition: 'left bottom',
      }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        onScrubStart(event.clientX);
      }}
      title="押す・引きずると再生位置が動きます"
    >
      {ticks.map((t) => (
        <div
          key={t}
          className="pointer-events-none absolute top-0 h-full border-l border-white/40 pl-1 text-[9px] leading-[18px] tabular-nums text-neutral-300"
          style={{ left: t * pps }}
        >
          {label(t, step)}
        </div>
      ))}
      <div
        ref={headRef}
        data-playhead-head
        className="pointer-events-none absolute left-0 top-0 h-full"
        style={{ willChange: 'transform' }}
      >
        <div
          className="absolute -left-[6px] top-0 h-[13px] w-[13px] bg-destructive"
          style={{ clipPath: 'polygon(0 0, 100% 0, 100% 55%, 50% 100%, 0 55%)' }}
        />
        <div className="absolute left-0 top-0 h-full w-px bg-destructive" />
      </div>
    </div>
  );
});
