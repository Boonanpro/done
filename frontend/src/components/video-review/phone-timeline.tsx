'use client';

// スマホでエディターを見る時の、指でなぞって再生位置を動かす部品（2026-11-17 本人「YouTube やショート動画を
// 見ている感じで、左右に動かして移動したい」）。
// - PhoneTimeline: 真ん中の赤線は動かず、段の帯の方が指について左右に流れる細いタイムライン。2本指で拡大・縮小。
// - PhoneSwipeSurface: 映像の上に重ねる透明な面。左右になぞると帯と同じ速さで前後に動く。軽く押すと onTap。
// どちらも指を離した後は勢いのまま少し流れる。動かしている間は再生を止め、離して止まったら元の再生に戻す。
// 毎コマ描き直すのは帯の canvas だけで、エディター本体は seek を1コマに1回だけ呼ぶ。

import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react';

export type PhoneLaneItem = { s: number; e: number; color: string };
export type PhoneLane = { key: string; zone: 'visual' | 'audio'; items: PhoneLaneItem[]; maxLen: number };

/** 帯と映像の面が分け合う状態: 1秒が何px か、なぞっている間の時刻、なぞっているか */
export type PhoneScrub = {
  pps: number;
  dragT: number | null;
  active: boolean;
  resume: boolean;
};

export function createPhoneScrub(): PhoneScrub {
  return { pps: 20, dragT: null, active: false, resume: false };
}

type ScrubOpts = {
  ctl: PhoneScrub;
  liveTimeRef: RefObject<number>;
  duration: () => number;
  onSeek: (t: number) => void;
  playing: () => boolean;
  setPlaying: (p: boolean) => void;
  onTap?: (x: number, y: number) => void;
  pinch?: boolean;
};

const MIN_PPS = 0.05;
const MAX_PPS = 400;
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

function bindScrub(el: HTMLElement, get: () => ScrubOpts) {
  const pts = new Map<number, { x: number; y: number }>();
  let x0 = 0;
  let y0 = 0;
  let t0 = 0;
  let downAt = 0;
  let moved = false;
  let pinchD0 = 0;
  let pinchPps0 = 0;
  let samples: { x: number; at: number }[] = [];
  let seekRaf = 0;
  let inertiaRaf = 0;
  let pending: number | null = null;

  const flushSeek = () => {
    seekRaf = 0;
    if (pending == null) return;
    const t = pending;
    pending = null;
    get().onSeek(t);
  };
  const setT = (t: number) => {
    const o = get();
    const d = o.duration();
    const v = clamp(t, 0, d > 0 ? d : 0);
    o.ctl.dragT = v;
    pending = v;
    if (!seekRaf) seekRaf = requestAnimationFrame(flushSeek);
  };
  const begin = () => {
    const o = get();
    if (o.ctl.active) return;
    o.ctl.active = true;
    if (o.playing()) {
      o.ctl.resume = true;
      o.setPlaying(false);
    }
  };
  const end = () => {
    const o = get();
    if (seekRaf) { cancelAnimationFrame(seekRaf); seekRaf = 0; }
    if (pending != null) { const t = pending; pending = null; o.onSeek(t); }
    o.ctl.active = false;
    o.ctl.dragT = null;
    if (o.ctl.resume) {
      o.ctl.resume = false;
      o.setPlaying(true);
    }
  };
  const stopInertia = () => {
    if (inertiaRaf) { cancelAnimationFrame(inertiaRaf); inertiaRaf = 0; }
  };
  const anchor = (x: number) => {
    const o = get();
    x0 = x;
    t0 = o.ctl.dragT ?? Number(o.liveTimeRef.current || 0);
  };

  const down = (ev: PointerEvent) => {
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    ev.preventDefault();
    try { el.setPointerCapture(ev.pointerId); } catch {}
    const wasCoasting = !!inertiaRaf;
    stopInertia();
    pts.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pts.size === 1) {
      anchor(ev.clientX);
      y0 = ev.clientY;
      downAt = performance.now();
      moved = wasCoasting; // 流れている途中に押したら、止めるだけ（押した扱いにしない）
      samples = [{ x: ev.clientX, at: downAt }];
    } else if (pts.size === 2 && get().pinch) {
      const [a, b] = Array.from(pts.values());
      pinchD0 = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      pinchPps0 = get().ctl.pps;
      moved = true;
    }
  };
  const move = (ev: PointerEvent) => {
    if (!pts.has(ev.pointerId)) return;
    pts.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    const o = get();
    if (pts.size >= 2) {
      if (!o.pinch) return;
      const [a, b] = Array.from(pts.values());
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      o.ctl.pps = clamp(pinchPps0 * (d / pinchD0), MIN_PPS, MAX_PPS);
      return;
    }
    const dx = ev.clientX - x0;
    if (!moved) {
      if (Math.abs(dx) < 6 && Math.abs(ev.clientY - y0) < 6) return;
      moved = true;
      begin();
      anchor(ev.clientX); // 遊びの6pxで飛ばない
      return;
    }
    if (!o.ctl.active) begin();
    setT(t0 - (ev.clientX - x0) / o.ctl.pps);
    const now = performance.now();
    samples.push({ x: ev.clientX, at: now });
    while (samples.length > 2 && now - samples[0].at > 90) samples.shift();
  };
  const up = (ev: PointerEvent) => {
    if (!pts.has(ev.pointerId)) return;
    pts.delete(ev.pointerId);
    try { el.releasePointerCapture(ev.pointerId); } catch {}
    const o = get();
    if (pts.size === 1) {
      // 2本指の片方を離した: 残った指で続きをなぞれるように付け直す
      const [rest] = Array.from(pts.values());
      anchor(rest.x);
      samples = [{ x: rest.x, at: performance.now() }];
      return;
    }
    if (pts.size > 0) return;
    if (!moved) {
      if (performance.now() - downAt < 400) o.onTap?.(ev.clientX, ev.clientY);
      return;
    }
    // 指を離した時の速さで少し流す
    const last = samples[samples.length - 1];
    const first = samples[0];
    const dt = last && first ? last.at - first.at : 0;
    let v = dt > 8 && performance.now() - last.at < 80 ? (last.x - first.x) / dt : 0; // px/ms
    if (Math.abs(v) < 0.25 || ev.type === 'pointercancel') { end(); return; }
    v = clamp(v, -6, 6);
    let t = o.ctl.dragT ?? Number(o.liveTimeRef.current || 0);
    let prev = performance.now();
    const step = () => {
      const now = performance.now();
      const ms = now - prev;
      prev = now;
      const g = get();
      t -= (v * ms) / g.ctl.pps;
      v *= Math.pow(0.94, ms / 16);
      const d = g.duration();
      if (t <= 0 || (d > 0 && t >= d)) v = 0;
      setT(t);
      if (Math.abs(v) < 0.03) { inertiaRaf = 0; end(); return; }
      inertiaRaf = requestAnimationFrame(step);
    };
    inertiaRaf = requestAnimationFrame(step);
  };

  el.addEventListener('pointerdown', down);
  el.addEventListener('pointermove', move);
  el.addEventListener('pointerup', up);
  el.addEventListener('pointercancel', up);
  return () => {
    stopInertia();
    if (seekRaf) cancelAnimationFrame(seekRaf);
    el.removeEventListener('pointerdown', down);
    el.removeEventListener('pointermove', move);
    el.removeEventListener('pointerup', up);
    el.removeEventListener('pointercancel', up);
  };
}

function useScrub(ref: RefObject<HTMLElement | null>, opts: ScrubOpts) {
  const optsRef = useRef(opts);
  useLayoutEffect(() => { optsRef.current = opts; });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    return bindScrub(el, () => optsRef.current);
  }, [ref]);
}

export function fmtPhoneTime(t: number): string {
  const s = Math.max(0, t);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`;
}

const TICKS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600];

/** 真ん中の赤線は動かさず、段の帯が指について流れる細いタイムライン */
export function PhoneTimeline({
  lanes,
  ctl,
  liveTimeRef,
  duration,
  onSeek,
  playing,
  setPlaying,
  height = 96,
  dark = false,
}: {
  lanes: PhoneLane[];
  ctl: PhoneScrub;
  liveTimeRef: RefObject<number>;
  duration: number;
  onSeek: (t: number) => void;
  playing: boolean;
  setPlaying: (p: boolean) => void;
  height?: number;
  dark?: boolean;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const lanesRef = useRef(lanes);
  useLayoutEffect(() => { lanesRef.current = lanes; });
  const playingRef = useRef(playing);
  useLayoutEffect(() => { playingRef.current = playing; });
  const durationRef = useRef(duration);
  useLayoutEffect(() => { durationRef.current = duration; });
  const lanesRev = useRef(0);
  useEffect(() => { lanesRev.current += 1; }, [lanes]);

  useScrub(hostRef, {
    ctl,
    liveTimeRef,
    duration: () => durationRef.current,
    onSeek,
    playing: () => playingRef.current,
    setPlaying,
    pinch: true,
  });

  useEffect(() => {
    let raf = 0;
    let last = '';
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const host = hostRef.current;
      const cv = canvasRef.current;
      if (!host || !cv) return;
      const w = host.clientWidth;
      const h = host.clientHeight;
      const dpr = Math.min(3, window.devicePixelRatio || 1);
      const t = ctl.dragT ?? Number(liveTimeRef.current || 0);
      const key = `${w}x${h}@${dpr}|${t.toFixed(4)}|${ctl.pps.toFixed(4)}|${lanesRev.current}|${durationRef.current}`;
      if (key === last) return;
      last = key;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
        cv.width = Math.round(w * dpr);
        cv.height = Math.round(h * dpr);
        cv.style.width = `${w}px`;
        cv.style.height = `${h}px`;
      }
      const g = cv.getContext('2d');
      if (!g) return;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      const pps = ctl.pps;
      const cx = w / 2;
      const t0 = t - cx / pps;
      const t1 = t + cx / pps;
      const xOf = (s: number) => cx + (s - t) * pps;
      const dur = durationRef.current;
      // 作品の外（頭より前・終わりより後）は暗くする
      g.fillStyle = dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)';
      const a = Math.max(0, xOf(0));
      const b = Math.min(w, xOf(dur || 0));
      if (b > a) g.fillRect(a, 0, b - a, h);
      // 目盛り
      const RULER = 16;
      let step = TICKS[TICKS.length - 1];
      for (const s of TICKS) { if (s * pps >= 64) { step = s; break; } }
      g.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
      g.textBaseline = 'top';
      g.fillStyle = dark ? 'rgba(255,255,255,0.65)' : 'rgba(60,60,70,0.8)';
      const first = Math.max(0, Math.floor(t0 / step) * step);
      for (let s = first; s <= Math.min(t1, dur || t1); s += step) {
        const x = xOf(s);
        g.fillRect(Math.round(x), RULER - 5, 1, 5);
        g.fillText(step < 1 ? `${fmtPhoneTime(s)}.${Math.round((s % 1) * 10)}` : fmtPhoneTime(s), Math.round(x) + 3, 1);
      }
      // 段
      const ls = lanesRef.current;
      const n = ls.length || 1;
      const avail = h - RULER - 4;
      const gap = 2;
      const lh = clamp(Math.floor((avail - gap * (n - 1)) / n), 3, 14);
      let y = RULER + 3;
      for (const lane of ls) {
        const items = lane.items;
        // 始まりで並んでいるので、見える範囲の少し前から探し始める
        let lo = 0;
        let hi = items.length;
        const from = t0 - lane.maxLen;
        while (lo < hi) { const mid = (lo + hi) >> 1; if (items[mid].s < from) lo = mid + 1; else hi = mid; }
        for (let i = lo; i < items.length; i += 1) {
          const it = items[i];
          if (it.s > t1) break;
          if (it.e < t0) continue;
          const x = xOf(it.s);
          const x2 = xOf(it.e);
          const cw = Math.max(1, x2 - x - (x2 - x > 3 ? 1 : 0));
          g.fillStyle = it.color;
          g.fillRect(x, y, cw, lh);
        }
        y += lh + gap;
        if (y > h) break;
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [ctl, liveTimeRef, dark]);

  return (
    <div
      ref={hostRef}
      data-phone-timeline
      className="relative w-full select-none overflow-hidden"
      style={{ height, touchAction: 'none' }}
      aria-label="タイムライン（指で左右に送る・2本指で拡大）"
    >
      <canvas ref={canvasRef} className="pointer-events-none absolute inset-0" />
      <div className="pointer-events-none absolute bottom-0 left-1/2 top-0 w-0.5 -translate-x-1/2 bg-red-500" />
      <div className="pointer-events-none absolute left-1/2 top-0 h-0 w-0 -translate-x-1/2 border-x-[5px] border-t-[6px] border-x-transparent border-t-red-500" />
    </div>
  );
}

/** 映像の上に重ねる透明な面: 左右になぞると前後に動く。軽く押すと onTap */
export function PhoneSwipeSurface({
  ctl,
  liveTimeRef,
  duration,
  onSeek,
  playing,
  setPlaying,
  onTap,
}: {
  ctl: PhoneScrub;
  liveTimeRef: RefObject<number>;
  duration: number;
  onSeek: (t: number) => void;
  playing: boolean;
  setPlaying: (p: boolean) => void;
  onTap: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const playingRef = useRef(playing);
  useLayoutEffect(() => { playingRef.current = playing; });
  const durationRef = useRef(duration);
  useLayoutEffect(() => { durationRef.current = duration; });
  useScrub(ref, {
    ctl,
    liveTimeRef,
    duration: () => durationRef.current,
    onSeek,
    playing: () => playingRef.current,
    setPlaying,
    onTap: () => onTap(),
  });
  return <div ref={ref} data-phone-swipe className="absolute inset-0 z-[25]" style={{ touchAction: 'none' }} />;
}

/** 再生位置の時刻（毎コマ文字だけ書き換える） */
export function PhoneTime({ ctl, liveTimeRef, duration, className }: { ctl: PhoneScrub; liveTimeRef: RefObject<number>; duration: number; className?: string }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const t = ctl.dragT ?? Number(liveTimeRef.current || 0);
      const s = `${fmtPhoneTime(t)} / ${fmtPhoneTime(duration)}`;
      if (ref.current && ref.current.textContent !== s) ref.current.textContent = s;
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [ctl, liveTimeRef, duration]);
  return <span ref={ref} data-phone-time className={className}>0:00 / {fmtPhoneTime(duration)}</span>;
}
