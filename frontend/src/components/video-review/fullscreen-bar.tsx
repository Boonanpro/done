'use client';

import { useEffect, useRef, useState, type RefObject } from 'react';

/** プレビューの全画面（P）の下に出す再生の帯: 再生・停止、つまみで再生位置を動かす、時刻。
 *  マウスを動かすと出て、再生中に2.5秒動かさなければ消える（前のエディターと同じ）。
 *  つまみは毎コマ描き直すので、エディター本体は描き直さない（時刻は liveTimeRef を直接読む）。 */
function fmt(t: number): string {
  const s = Math.max(0, t);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`;
}

export function FullscreenBar({
  hostRef,
  playing,
  duration,
  liveTimeRef,
  onTogglePlay,
  onSeek,
  onSetPlaying,
}: {
  hostRef: RefObject<HTMLDivElement | null>;
  playing: boolean;
  duration: number;
  liveTimeRef: RefObject<number>;
  onTogglePlay: () => void;
  onSeek: (t: number) => void;
  onSetPlaying: (p: boolean) => void;
}) {
  const [shown, setShown] = useState(true);
  const hoverRef = useRef(false);
  const draggingRef = useRef(false);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const fillRef = useRef<HTMLDivElement | null>(null);
  const knobRef = useRef<HTMLDivElement | null>(null);
  const timeRef = useRef<HTMLSpanElement | null>(null);
  const playingRef = useRef(playing);
  useEffect(() => { playingRef.current = playing; }, [playing]);

  // マウスを動かすと出す。再生中に止まったら消す
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let timer = 0;
    const poke = () => {
      setShown(true);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (playingRef.current && !hoverRef.current && !draggingRef.current) setShown(false);
      }, 2500);
    };
    poke();
    host.addEventListener('pointermove', poke);
    host.addEventListener('pointerdown', poke);
    return () => {
      window.clearTimeout(timer);
      host.removeEventListener('pointermove', poke);
      host.removeEventListener('pointerdown', poke);
    };
  }, [hostRef, playing]);

  // つまみと時刻を毎コマ合わせる
  useEffect(() => {
    let raf = 0;
    let last = -1;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const t = Number(liveTimeRef.current || 0);
      if (t === last) return;
      last = t;
      const f = duration > 0 ? Math.max(0, Math.min(1, t / duration)) : 0;
      if (fillRef.current) fillRef.current.style.transform = `scaleX(${f})`;
      if (knobRef.current) knobRef.current.style.left = `${f * 100}%`;
      if (timeRef.current) timeRef.current.textContent = `${fmt(t)} / ${fmt(duration)}`;
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [duration, liveTimeRef]);

  const timeAt = (clientX: number) => {
    const r = trackRef.current?.getBoundingClientRect();
    if (!r || !r.width || !(duration > 0)) return 0;
    return Number((Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * duration).toFixed(3));
  };

  const startDrag = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    draggingRef.current = true;
    // つかんでいる間は止め、離すとその位置から再生を続ける（タイムラインの目盛りと同じ）
    const resume = playingRef.current;
    if (resume) onSetPlaying(false);
    onSeek(timeAt(e.clientX));
    let lastT = -1;
    const move = (ev: PointerEvent) => {
      const t = timeAt(ev.clientX);
      if (t !== lastT) { lastT = t; onSeek(t); }
    };
    const up = () => {
      draggingRef.current = false;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      if (resume) onSetPlaying(true);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
  };

  return (
    <div
      data-fullscreen-bar
      className={`absolute inset-x-0 bottom-0 z-30 bg-gradient-to-t from-black/80 to-transparent px-6 pb-4 pt-10 transition-opacity duration-200 ${shown ? 'opacity-100' : 'pointer-events-none opacity-0'}`}
      style={{ cursor: shown ? 'default' : 'none' }}
      onPointerEnter={() => { hoverRef.current = true; }}
      onPointerLeave={() => { hoverRef.current = false; }}
      onPointerDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      <div
        ref={trackRef}
        data-fullscreen-seek
        className="group relative h-5 cursor-pointer"
        style={{ touchAction: 'none' }}
        onPointerDown={startDrag}
      >
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/30 group-hover:h-1.5" />
        <div ref={fillRef} className="absolute inset-x-0 top-1/2 h-1 origin-left -translate-y-1/2 rounded-full bg-red-500 group-hover:h-1.5" style={{ transform: 'scaleX(0)' }} />
        <div ref={knobRef} className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-red-500 shadow" style={{ left: 0 }} />
      </div>
      <div className="mt-1 flex items-center gap-4 text-sm text-white">
        <button
          type="button"
          data-fullscreen-play
          className="flex h-9 w-9 items-center justify-center rounded-full hover:bg-white/15"
          title={playing ? '停止（スペース）' : '再生（スペース）'}
          onClick={(e) => { e.stopPropagation(); onTogglePlay(); }}
        >
          {playing ? (
            <svg viewBox="0 0 24 24" className="h-6 w-6 fill-current"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
          ) : (
            <svg viewBox="0 0 24 24" className="h-6 w-6 fill-current"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" /></svg>
          )}
        </button>
        <span ref={timeRef} className="font-mono tabular-nums text-white/90">0:00 / {fmt(duration)}</span>
        <span className="ml-auto text-xs text-white/50">P か Esc で戻る</span>
      </div>
    </div>
  );
}
