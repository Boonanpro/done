'use client';

// スマホでエディターを見る時の、指でなぞって再生位置を動かす部品（2026-11-17 本人「YouTube やショート動画を
// 見ている感じで、左右に動かして移動したい」）。
// - PhoneTimeline: 真ん中の赤線は動かず、段の帯の方が指について左右に流れる細いタイムライン。2本指で拡大・縮小。
// - PhoneSwipeSurface: 映像の上に重ねる透明な面。左右になぞると帯と同じ速さで前後に動く。軽く押すと onTap。
// どちらも指を離した後は勢いのまま少し流れる。動かしている間は再生を止め、離して止まったら元の再生に戻す。
// 毎コマ描き直すのは帯の canvas だけで、エディター本体は seek を1コマに1回だけ呼ぶ。

import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react';

/** img: 絵（frame があれば 30コマの絵の帯のそのコマ。PC のタイムラインと同じ絵） */
/** strip: 動画の絵の帯の元（素材の住所と、使っている素材の始まり・終わりの秒）。クリップを端から端までその所のコマで埋める */
export type PhoneLaneItem = { s: number; e: number; color: string; img?: string; frame?: number; strip?: { base: string; ss: number; se: number } };

// 帯に描く絵。読み終わるたびに imgRev を進めて、次のコマで描き直す。
const STRIP_FRAMES = 30;
const imgCache = new Map<string, HTMLImageElement | null>();
let imgRev = 0;
function phoneImg(url: string): HTMLImageElement | null {
  const got = imgCache.get(url);
  if (got !== undefined) return got && got.complete && got.naturalWidth ? got : null;
  const im = new Image();
  im.decoding = 'async';
  im.onload = () => { imgRev += 1; };
  im.onerror = () => { imgCache.set(url, null); };
  im.src = url;
  imgCache.set(url, im);
  return null;
}
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
const SEEK_GAP_MS = 40;
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

  // 帯の絵は毎コマ動かし、映像の頭出し（エディター全体の描き直しを伴う）は 1秒に約25回までにする。
  // 毎コマ頭出しすると、クリップの多い作品で指についてこなくなる。
  let lastSeekAt = 0;
  const flushSeek = () => {
    seekRaf = 0;
    if (pending == null) return;
    const now = performance.now();
    if (now - lastSeekAt < SEEK_GAP_MS) { seekRaf = requestAnimationFrame(flushSeek); return; }
    lastSeekAt = now;
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
      samples = [{ x: ev.clientX, at: ev.timeStamp }];
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
    const now = ev.timeStamp;
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
      samples = [{ x: rest.x, at: ev.timeStamp }];
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
    let v = dt > 8 && ev.timeStamp - last.at < 100 ? (last.x - first.x) / dt : 0; // px/ms（指を止めてから離したら流さない）
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
  maxLane = 14,
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
  /** 1段の高さの上限（縦持ちは大きく） */
  maxLane?: number;
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
  const maxLaneRef = useRef(maxLane);
  useLayoutEffect(() => { maxLaneRef.current = maxLane; });
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
      const key = `${maxLaneRef.current}|${w}x${h}@${dpr}|${t.toFixed(4)}|${ctl.pps.toFixed(4)}|${lanesRev.current}|${durationRef.current}|${imgRev}`;
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
      const lh = clamp(Math.floor((avail - gap * (n - 1)) / n), 3, maxLaneRef.current);
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
          // 絵は段が 10px 以上・クリップが 14px 以上ある時だけ。クリップを端から端までコマで埋める（はみ出す分は切る）
          // 2026-11-24 本人「クリップも全部テキストで説明するんじゃなくてサムネを入れろ」
          if (it.img && lh >= 10 && cw >= 14) {
            const im = phoneImg(it.img);
            if (im) {
              const isStrip = it.frame != null;
              const fw = isStrip ? im.naturalWidth / STRIP_FRAMES : im.naturalWidth;
              const fh = im.naturalHeight;
              const dh = lh - 2;
              const tw = Math.max(8, dh * (fw / Math.max(1, fh)));
              const left = Math.max(x + 1, -tw);
              const right = Math.min(x + cw - 1, w + tw);
              g.save();
              g.beginPath(); g.rect(x + 1, y + 1, Math.max(0, cw - 2), dh); g.clip();
              // 見える所だけ描く（画面の外のコマは描かない）
              const startK = Math.max(0, Math.floor((left - (x + 1)) / tw));
              for (let k = startK, tx = x + 1 + startK * tw; tx < right && k < 400; k += 1, tx += tw) {
                let src = im;
                let fi = it.frame || 0;
                if (it.strip) {
                  const frac = Math.min(1, (tx + tw / 2 - x) / Math.max(1, cw));
                  const st = Math.max(0, Math.min(it.strip.ss + (it.strip.se - it.strip.ss) * frac, it.strip.se - 0.05));
                  const one = phoneImg(`${it.strip.base}&m=${Math.floor(st / 60)}`);
                  if (one) { src = one; fi = Math.floor((st % 60) / 2); }
                }
                const sw = isStrip ? src.naturalWidth / STRIP_FRAMES : src.naturalWidth;
                const sx = isStrip ? Math.max(0, Math.min(STRIP_FRAMES - 1, fi)) * sw : 0;
                g.drawImage(src, sx, 0, sw, src.naturalHeight, tx, y + 1, tw, dh);
              }
              g.restore();
            }
          }
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

/**
 * 作品の頭から終わりまでを横幅に並べたつまみ（YouTube の赤い線と同じ。2026-11-17 本人「左右に送るしか無く、
 * 一番最後の方へ一気に飛べない。スライドで動かせるシーケンスを足したい」）。
 * 押した所へ飛び、つかんだまま左右に動かすとその位置へ動く。動かしている間は再生を止め、離したら元に戻す。
 * thin: ボタンを隠している時の、映像の下の端の細い線（触れない）。
 */
export function PhoneSeekBar({
  ctl,
  liveTimeRef,
  duration,
  onSeek,
  playing,
  setPlaying,
  thin = false,
}: {
  ctl: PhoneScrub;
  liveTimeRef: RefObject<number>;
  duration: number;
  onSeek: (t: number) => void;
  playing: boolean;
  setPlaying: (p: boolean) => void;
  thin?: boolean;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const fillRef = useRef<HTMLDivElement | null>(null);
  const knobRef = useRef<HTMLDivElement | null>(null);
  const tipRef = useRef<HTMLDivElement | null>(null);
  const durationRef = useRef(duration);
  useLayoutEffect(() => { durationRef.current = duration; });
  const playingRef = useRef(playing);
  useLayoutEffect(() => { playingRef.current = playing; });
  const seekRef = useRef(onSeek);
  useLayoutEffect(() => { seekRef.current = onSeek; });
  const setPlayingRef = useRef(setPlaying);
  useLayoutEffect(() => { setPlayingRef.current = setPlaying; });
  const grabbing = useRef(false);

  // 位置の線とつまみは毎コマ動かす（React の描き直しをしない）
  useEffect(() => {
    let raf = 0;
    let last = '';
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const d = durationRef.current;
      const t = ctl.dragT ?? Number(liveTimeRef.current || 0);
      const p = d > 0 ? clamp(t / d, 0, 1) : 0;
      const key = `${p.toFixed(5)}|${grabbing.current ? 1 : 0}`;
      if (key === last) return;
      last = key;
      if (fillRef.current) fillRef.current.style.transform = `scaleX(${p})`;
      if (knobRef.current) knobRef.current.style.left = `${p * 100}%`;
      const tip = tipRef.current;
      if (tip) {
        tip.style.display = grabbing.current ? 'block' : 'none';
        if (grabbing.current) {
          tip.textContent = fmtPhoneTime(t);
          const w = hostRef.current?.clientWidth || 0;
          const tw = tip.offsetWidth || 0;
          tip.style.left = `${clamp(p * w - tw / 2, 0, Math.max(0, w - tw))}px`;
        }
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [ctl, liveTimeRef]);

  useEffect(() => {
    const el = hostRef.current;
    if (!el || thin) return;
    let pid: number | null = null;
    let raf = 0;
    let lastAt = 0;
    let pending: number | null = null;
    const flush = () => {
      raf = 0;
      if (pending == null) return;
      const now = performance.now();
      if (now - lastAt < SEEK_GAP_MS) { raf = requestAnimationFrame(flush); return; }
      lastAt = now;
      const t = pending;
      pending = null;
      seekRef.current(t);
    };
    const at = (x: number) => {
      const r = el.getBoundingClientRect();
      const d = durationRef.current;
      const t = r.width > 0 && d > 0 ? clamp((x - r.left) / r.width, 0, 1) * d : 0;
      ctl.dragT = t;
      pending = t;
      if (!raf) raf = requestAnimationFrame(flush);
    };
    const down = (ev: PointerEvent) => {
      if (ev.pointerType === 'mouse' && ev.button !== 0) return;
      if (pid != null) return;
      ev.preventDefault();
      ev.stopPropagation();
      pid = ev.pointerId;
      try { el.setPointerCapture(ev.pointerId); } catch {}
      grabbing.current = true;
      el.dataset.grab = '1';
      if (!ctl.active) {
        ctl.active = true;
        if (playingRef.current) { ctl.resume = true; setPlayingRef.current(false); }
      }
      at(ev.clientX);
    };
    const move = (ev: PointerEvent) => {
      if (ev.pointerId !== pid) return;
      at(ev.clientX);
    };
    const up = (ev: PointerEvent) => {
      if (ev.pointerId !== pid) return;
      pid = null;
      try { el.releasePointerCapture(ev.pointerId); } catch {}
      if (ev.type !== 'pointercancel') at(ev.clientX);
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      if (pending != null) { const t = pending; pending = null; seekRef.current(t); }
      grabbing.current = false;
      delete el.dataset.grab;
      ctl.active = false;
      ctl.dragT = null;
      if (ctl.resume) { ctl.resume = false; setPlayingRef.current(true); }
    };
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
    };
  }, [ctl, thin]);

  if (thin) {
    return (
      <div ref={hostRef} data-phone-seek-thin className="pointer-events-none absolute inset-x-0 bottom-0 z-[26] h-[3px] bg-white/25">
        <div ref={fillRef} className="absolute inset-0 origin-left bg-red-500" style={{ transform: 'scaleX(0)' }} />
      </div>
    );
  }
  return (
    <div
      ref={hostRef}
      data-phone-seek
      role="slider"
      aria-label="再生位置"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      className="group relative h-7 w-full select-none"
      style={{ touchAction: 'none' }}
    >
      <div ref={tipRef} className="pointer-events-none absolute -top-7 hidden rounded bg-black/80 px-1.5 py-0.5 font-mono text-xs tabular-nums text-white" />
      <div className="pointer-events-none absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-white/30 transition-[height] group-data-[grab]:h-[5px]">
        <div ref={fillRef} className="absolute inset-0 origin-left rounded-full bg-red-500" style={{ transform: 'scaleX(0)' }} />
      </div>
      <div
        ref={knobRef}
        className="pointer-events-none absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-red-500 shadow transition-[width,height] group-data-[grab]:h-5 group-data-[grab]:w-5"
        style={{ left: '0%' }}
      />
    </div>
  );
}
