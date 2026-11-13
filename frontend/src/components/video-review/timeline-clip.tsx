'use client';

/**
 * タイムラインのクリップ1つ分。React.memo なので、押した・選んだ・動かしたクリップだけが描き直される
 * （以前は1つ選ぶたびに600個のクリップ全部を描き直していて、遅いPCで0.2〜0.3秒止まっていた）。
 * 押した時の処理は fns（ref）から最新の物を呼ぶので、関数が変わっても描き直さない。
 *
 * 種類は色で分ける（2026-11-13 本人「テロップは紫と決めれば、1つずつ『テロップ』と書かなくていい」）:
 * 動画=灰＋その所の絵、画像=薄い赤＋絵、テロップ=紫、場面=水色、効果=琥珀、声=青、BGM=緑、効果音=黄。
 * 音のクリップには波形と音量の線を出し、線をつかんで上下に動かすと音量が変わる。
 */
import { memo, useEffect, useRef, useState } from 'react';

import { useSceneInfoFor } from './scene-store';

export type ClipBoxFns = {
  startDrag: (event: React.PointerEvent, clipId: string, mode: 'start' | 'end' | 'move') => void;
  openMenu: (event: React.MouseEvent, clipId: string) => void;
  focusClip: (clipId: string) => void;
  setVolume: (clipId: string, volume: number) => void;
};

export type ClipKind = 'video' | 'image' | 'caption' | 'scene' | 'effect' | 'voice' | 'bgm' | 'se';

export const CLIP_KIND_STYLE: Record<ClipKind, { cls: string; name: string; dark: boolean }> = {
  video: { cls: 'bg-zinc-500/85', name: '動画', dark: false },
  image: { cls: 'bg-rose-300/85 text-rose-950', name: '画像', dark: true },
  caption: { cls: 'bg-violet-500/75', name: 'テロップ', dark: false },
  scene: { cls: 'bg-sky-600/75', name: '場面', dark: false },
  effect: { cls: 'bg-amber-600/75', name: '効果', dark: false },
  voice: { cls: 'bg-blue-600/65', name: '声', dark: false },
  bgm: { cls: 'bg-emerald-600/75', name: 'BGM', dark: false },
  se: { cls: 'bg-yellow-400/85 text-yellow-950', name: '効果音', dark: true },
};

type Props = {
  clipId: string;
  left: number;   // % of the track
  width: number;  // % of the track
  widthPx: number; // 画面での幅（波形の細かさ）
  kind: ClipKind;
  label: string;
  thumb?: string;
  /** 動画: 素材の1分ぶんを2秒ごとに30コマ並べた帯と、そのうち何コマ目か（クリップの使っている所の絵） */
  strip?: string;
  stripIndex?: number;
  narrow: boolean;  // 画面で数ピクセルしかない時は、端のつまみと文字を描かない（部品を5分の1に）
  selected: boolean;
  linkedSelected: boolean;
  touch: boolean;
  appear: boolean;
  vanish: boolean;
  title: string;
  // 音: 波形（素材の peaks）と、その素材のどこからどこまでを使っているか、音量
  peaksUrl?: string;
  sourceStart?: number;
  sourceEnd?: number;
  volume?: number;
  fns: React.MutableRefObject<ClipBoxFns>;
};

/** An editable scene's texts as rows inside its clip: where each one is on screen. Pressing a row
 *  selects the clip (the press goes on to the clip) and tells the side panel which text to open. */
function SceneRows({ clipId, fns }: { clipId: string; fns: React.MutableRefObject<ClipBoxFns> }) {
  const info = useSceneInfoFor(clipId);
  if (!info || !info.items.length || !info.duration) return null;
  const rows = info.items.slice(0, 6);
  return (
    <div className="pointer-events-none absolute inset-x-2 bottom-[1px] top-[12px]">
      {rows.map((it, i) => (
        <div
          key={it.key}
          data-scene-item={it.key}
          className="pointer-events-auto absolute truncate rounded-[2px] bg-white/80 px-0.5 text-[8px] leading-[9px] text-violet-950"
          style={{
            left: `${Math.max(0, (it.start / info.duration) * 100)}%`,
            width: `${Math.max(2, ((Math.min(info.duration, it.end) - it.start) / info.duration) * 100)}%`,
            top: `${(i / rows.length) * 100}%`,
            height: `${100 / rows.length - 3}%`, minHeight: 6,
          }}
          title={`${it.label || it.key}: ${it.text}`}
          onPointerDown={(event) => {
            fns.current.startDrag(event, clipId, 'move'); // selects the clip like pressing its body
            const detail = { clipId, key: it.key };
            window.setTimeout(() => window.dispatchEvent(new CustomEvent('dan-scene-item', { detail })), 0);
            (window as unknown as { __danSceneItem?: unknown }).__danSceneItem = detail; // the panel may mount after this press
          }}
        >
          {it.text}
        </div>
      ))}
    </div>
  );
}

// --- 波形: 素材ごとに1回だけ読む（1秒に100個の山、0〜255） ---------------------------------------
const PEAKS_PER_SEC = 100;
const peaksCache = new Map<string, Promise<Uint8Array | null>>();
function loadPeaks(url: string): Promise<Uint8Array | null> {
  let p = peaksCache.get(url);
  if (!p) {
    p = fetch(url, { credentials: 'include' })
      .then((r) => (r.ok ? r.arrayBuffer() : null))
      .then((b) => (b ? new Uint8Array(b) : null))
      .catch(() => null);
    peaksCache.set(url, p);
    void p.then((v) => { if (!v) window.setTimeout(() => peaksCache.delete(url), 15000); }); // 作れなかった時は少し後にまた頼む
  }
  return p;
}

// --- 絵の帯: 帯ごとに1回だけ読み、1コマの縦横比を覚える --------------------------------------------
const STRIP_FRAMES = 30;
const stripAspect = new Map<string, number | Promise<number>>();
function useStripAspect(url: string | undefined): number | null {
  const known = url ? stripAspect.get(url) : undefined;
  const [aspect, setAspect] = useState<number | null>(typeof known === 'number' ? known : null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    let p = stripAspect.get(url);
    if (p === undefined) {
      p = new Promise<number>((resolve) => {
        const img = new Image();
        img.decoding = 'async';
        img.onload = () => { const a = img.naturalWidth / STRIP_FRAMES / Math.max(1, img.naturalHeight); stripAspect.set(url, a); resolve(a); };
        img.onerror = () => { stripAspect.delete(url); resolve(0); };
        img.src = url;
      });
      stripAspect.set(url, p);
    }
    void Promise.resolve(p).then((a) => { if (alive && a) setAspect(a); });
    return () => { alive = false; };
  }, [url]);
  return url ? aspect : null;
}

// 音量の線の位置: 下端=0%、真ん中=100%、上端=200%
const VOL_MAX = 2;
const volToFrac = (v: number) => 1 - Math.max(0, Math.min(VOL_MAX, v)) / VOL_MAX;

function Waveform({ url, sourceStart, sourceEnd, widthPx, volume, dark }: {
  url: string; sourceStart: number; sourceEnd: number; widthPx: number; volume: number; dark: boolean;
}) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const [peaks, setPeaks] = useState<Uint8Array | null>(null);
  useEffect(() => {
    let alive = true;
    void loadPeaks(url).then((p) => { if (alive) setPeaks(p); });
    return () => { alive = false; };
  }, [url]);
  useEffect(() => {
    const c = ref.current;
    if (!c || !peaks) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const cw = Math.max(1, Math.min(4096, Math.round(widthPx * dpr)));
    const ch = Math.max(1, Math.round((c.clientHeight || 30) * dpr));
    if (c.width !== cw) c.width = cw;
    if (c.height !== ch) c.height = ch;
    const g = c.getContext('2d');
    if (!g) return;
    g.clearRect(0, 0, cw, ch);
    g.fillStyle = dark ? 'rgba(40,30,0,0.55)' : 'rgba(255,255,255,0.62)';
    const a = sourceStart * PEAKS_PER_SEC;
    const span = Math.max(1, (sourceEnd - sourceStart) * PEAKS_PER_SEC);
    const mid = ch / 2;
    const gain = Math.min(VOL_MAX, Math.max(0, volume));
    for (let x = 0; x < cw; x += 1) {
      const i0 = Math.floor(a + (x / cw) * span);
      const i1 = Math.max(i0 + 1, Math.floor(a + ((x + 1) / cw) * span));
      let m = 0;
      for (let i = i0; i < i1 && i < peaks.length; i += 1) if (peaks[i] > m) m = peaks[i];
      if (!m) continue;
      // 小さい音も見えるように平方根で。音量を上げ下げすると波形も大きさが変わる
      const h = Math.min(mid, Math.sqrt(m / 255) * mid * gain * 0.95);
      g.fillRect(x, mid - h, 1, Math.max(1, h * 2));
    }
  }, [peaks, sourceStart, sourceEnd, widthPx, volume, dark]);
  return <canvas ref={ref} className="pointer-events-none absolute inset-0 h-full w-full" />;
}

/** 音量の線。つかんで上下に動かすと音量が変わる（離した時に決まる）。100% の近くは吸い付く */
function VolumeLine({ clipId, volume, fns, onLive }: {
  clipId: string; volume: number; fns: React.MutableRefObject<ClipBoxFns>; onLive: (v: number | null) => void;
}) {
  const drag = useRef<{ top: number; height: number; v: number } | null>(null);
  return (
    <div
      data-volume-line={clipId}
      className="absolute inset-x-2 z-[2] h-[9px] -translate-y-1/2 cursor-ns-resize"
      style={{ top: `${volToFrac(volume) * 100}%` }}
      title={`音量 ${Math.round(volume * 100)}%（線を上下に動かす・ダブルクリックで100%）`}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
        event.preventDefault();
        const box = (event.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
        drag.current = { top: box.top, height: box.height, v: volume };
        try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* ignore */ }
      }}
      onPointerMove={(event) => {
        const d = drag.current;
        if (!d) return;
        let v = (1 - (event.clientY - d.top) / Math.max(1, d.height)) * VOL_MAX;
        v = Math.max(0, Math.min(VOL_MAX, v));
        if (Math.abs(v - 1) < 0.05) v = 1;
        d.v = Math.round(v * 100) / 100;
        onLive(d.v);
      }}
      onPointerUp={() => {
        const d = drag.current;
        drag.current = null;
        if (d) fns.current.setVolume(clipId, d.v);
        onLive(null);
      }}
      onPointerCancel={() => { drag.current = null; onLive(null); }}
      onDoubleClick={(event) => { event.stopPropagation(); fns.current.setVolume(clipId, 1); }}
    >
      <div className="absolute inset-x-0 top-1/2 h-[1.5px] -translate-y-1/2 bg-amber-300 shadow-[0_0_2px_rgba(0,0,0,0.8)]" />
    </div>
  );
}

function ClipBoxInner({ clipId, left, width, widthPx, kind, label, thumb, strip, stripIndex = 0, narrow, selected, linkedSelected, touch, appear, vanish, title, peaksUrl, sourceStart = 0, sourceEnd = 0, volume = 1, fns }: Props) {
  const look = CLIP_KIND_STYLE[kind];
  const isAudio = kind === 'voice' || kind === 'bgm' || kind === 'se';
  const [liveVol, setLiveVol] = useState<number | null>(null);
  const aspect = useStripAspect(!narrow && widthPx >= 40 ? strip : undefined);
  const vol = liveVol ?? volume;
  const cls = `absolute flex cursor-grab items-center overflow-hidden rounded border text-[10px] shadow-sm active:cursor-grabbing ${look.dark ? '' : 'text-white'} ${look.cls} ${
    touch ? 'dan-touch' : ''} ${appear ? 'dan-appear' : ''} ${vanish ? 'dan-vanish' : ''} ${
    selected
      ? 'z-[5] border-2 border-yellow-300 ring-2 ring-yellow-300/80 brightness-125'
      : linkedSelected
        ? 'border-yellow-300/70 ring-2 ring-yellow-300/40 ring-dashed'
        : 'border-white/30'
  }`;
  const style: React.CSSProperties = {
    left: `${left}%`,
    width: `${width}%`,
    minWidth: '3px',
    top: 3,
    bottom: 3,
  };
  if (narrow) {
    return (
      <div
        data-clip-id={clipId}
        data-clip-kind={kind}
        className={cls}
        style={style}
        title={title}
        onPointerDown={(event) => fns.current.startDrag(event, clipId, 'move')}
        onDoubleClick={(event) => { event.stopPropagation(); fns.current.focusClip(clipId); }}
        onContextMenu={(event) => fns.current.openMenu(event, clipId)}
      />
    );
  }
  const showThumb = !!thumb && widthPx >= 40;
  return (
    <div data-clip-id={clipId} data-clip-kind={kind} className={cls} style={style} title={title} onContextMenu={(event) => fns.current.openMenu(event, clipId)}>
      {isAudio && peaksUrl && sourceEnd > sourceStart ? (
        <Waveform url={peaksUrl} sourceStart={sourceStart} sourceEnd={sourceEnd} widthPx={widthPx} volume={vol} dark={look.dark} />
      ) : null}
      <button
        type="button"
        className="relative z-[1] h-full w-2 shrink-0 cursor-ew-resize bg-black/30"
        onPointerDown={(event) => fns.current.startDrag(event, clipId, 'start')}
        aria-label="Resize clip start"
      />
      <div
        className="relative flex h-full min-w-0 flex-1 cursor-grab items-center gap-1 truncate active:cursor-grabbing"
        onPointerDown={(event) => fns.current.startDrag(event, clipId, 'move')}
        onDoubleClick={(event) => { event.stopPropagation(); fns.current.focusClip(clipId); }}
      >
        {strip && aspect && widthPx >= 40 ? (
          <div
            className="pointer-events-none h-full max-w-[60%] shrink-0 bg-no-repeat"
            style={{
              aspectRatio: String(aspect),
              backgroundImage: `url(${strip})`,
              backgroundSize: `${STRIP_FRAMES * 100}% 100%`,
              backgroundPosition: `${(Math.max(0, Math.min(STRIP_FRAMES - 1, stripIndex)) / (STRIP_FRAMES - 1)) * 100}% 0`,
            }}
          />
        ) : showThumb ? (
          <img
            src={thumb}
            alt=""
            loading="lazy"
            decoding="async"
            draggable={false}
            className="pointer-events-none h-full w-auto max-w-[60%] shrink-0 object-cover"
            style={{ aspectRatio: '16 / 9' }}
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
          />
        ) : null}
        <span className={`truncate px-1 ${isAudio ? 'self-start pt-[1px] text-[9px] leading-tight drop-shadow-[0_1px_1px_rgba(0,0,0,0.6)]' : ''} ${look.dark && isAudio ? 'drop-shadow-none' : ''}`}>{label}</span>
      </div>
      {kind === 'scene' ? <SceneRows clipId={clipId} fns={fns} /> : null}
      {isAudio ? <VolumeLine clipId={clipId} volume={vol} fns={fns} onLive={setLiveVol} /> : null}
      {liveVol != null ? (
        <span className="pointer-events-none absolute right-3 top-0 z-[3] rounded bg-black/75 px-1 text-[9px] text-white">{Math.round(liveVol * 100)}%</span>
      ) : null}
      <button
        type="button"
        className="relative z-[1] h-full w-2 shrink-0 cursor-ew-resize bg-black/30"
        onPointerDown={(event) => fns.current.startDrag(event, clipId, 'end')}
        aria-label="Resize clip end"
      />
    </div>
  );
}

export const ClipBox = memo(ClipBoxInner);
