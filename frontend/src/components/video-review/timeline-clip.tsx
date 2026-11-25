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
import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react';

import { useSceneInfoFor } from './scene-store';

export type ClipBoxFns = {
  startDrag: (event: React.PointerEvent, clipId: string, mode: 'start' | 'end' | 'move') => void;
  openMenu: (event: React.MouseEvent, clipId: string) => void;
  focusClip: (clipId: string) => void;
  setVolume: (clipId: string, volume: number) => void;
  /** 直し終わったコメントのチェックを押した時: そのクリップのコメントを解決済みにして印を消す */
  resolveComment: (clipId: string) => void;
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
  /** このクリップに送ったコメント（直しの指示）の進み具合。右上の吹き出しの色になる */
  comment?: ClipCommentState;
  fns: React.MutableRefObject<ClipBoxFns>;
};

export type ClipCommentState = 'active' | 'done' | 'failed';

/** クリップの右上の印。コメントを送ったクリップに出る（作業中=黄の点滅・止まった=赤）。直し終わると緑のチェックになり、
 *  押すと解決済みになって消える（2026-11-25 本人「緑はチェックマークにしてクリックしたら解決済みになって消えるように」） */
function CommentDot({ state, clipId, fns }: { state: ClipCommentState; clipId: string; fns: React.MutableRefObject<ClipBoxFns> }) {
  if (state === 'done') {
    return (
      <button type="button" data-clip-comment="done" title="ダンが直しました。押すと解決済みにして印を消します"
        className="absolute right-0.5 top-0.5 z-[3] flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-[10px] font-bold leading-none text-white shadow ring-1 ring-white/70 hover:bg-emerald-400"
        onPointerDown={(event) => event.stopPropagation()}
        onDoubleClick={(event) => event.stopPropagation()}
        onClick={(event) => { event.stopPropagation(); fns.current.resolveComment(clipId); }}>
        ✓
      </button>
    );
  }
  const cls = state === 'active' ? 'animate-pulse bg-amber-400 text-black' : 'bg-red-500 text-white';
  const tip = state === 'active' ? 'コメントをダンが直しています' : 'コメントの作業が止まりました';
  return (
    <span data-clip-comment={state} title={tip}
      className={`pointer-events-none absolute right-0.5 top-0.5 z-[2] flex h-3.5 min-w-3.5 items-center justify-center rounded-full px-0.5 text-[8px] leading-none shadow ${cls}`}>
      ✎
    </span>
  );
}

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

// 絵の帯と波形の読み込みは同時に2つまで。ブラウザが1つの住所に張れる接続は6本しかなく、
// 絵を一度に何十も頼むと、プレビューの映像の読み込みが順番待ちになって再生が始まらなかった（2026-11-13 試し）
let sideLoads = 0;
const sideQueue: Array<() => void> = [];
function sideLoad<T>(run: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve) => {
    const go = () => {
      sideLoads += 1;
      void run().then(resolve, () => resolve(undefined as T)).finally(() => {
        sideLoads -= 1;
        const next = sideQueue.shift();
        if (next) next();
      });
    };
    if (sideLoads < 2) go(); else sideQueue.push(go);
  });
}

// --- 波形: 素材ごとに1回だけ読む（1秒に100個の山、0〜255） ---------------------------------------
const PEAKS_PER_SEC = 100;
const peaksCache = new Map<string, Promise<Uint8Array | null>>();
function loadPeaks(url: string): Promise<Uint8Array | null> {
  let p = peaksCache.get(url);
  if (!p) {
    p = sideLoad(() => fetch(url, { credentials: 'include' })
      .then((r) => (r.ok ? r.arrayBuffer() : null))
      .then((b) => (b ? new Uint8Array(b) : null))
      .catch(() => null));
    peaksCache.set(url, p);
    void p.then((v) => { if (!v) window.setTimeout(() => peaksCache.delete(url), 15000); }); // 作れなかった時は少し後にまた頼む
  }
  return p;
}

// 山を2つずつ最大でまとめた段（段 k は 2^k 個ずつ）。素材ごとに1回だけ作る
const PEAK_LEVELS = 16;
const peakLevels = new WeakMap<Uint8Array, Uint8Array[]>();
function peakLevel(peaks: Uint8Array, level: number): Uint8Array {
  let levels = peakLevels.get(peaks);
  if (!levels) { levels = [peaks]; peakLevels.set(peaks, levels); }
  while (levels.length <= level) {
    const prev = levels[levels.length - 1];
    const next = new Uint8Array(Math.ceil(prev.length / 2));
    for (let i = 0; i < next.length; i += 1) {
      const p = prev[2 * i];
      const q = 2 * i + 1 < prev.length ? prev[2 * i + 1] : 0;
      next[i] = p > q ? p : q;
    }
    levels.push(next);
  }
  return levels[level];
}

// --- 絵の帯: 帯ごとに1回だけ読み、1コマの縦横比を覚える --------------------------------------------
const STRIP_FRAMES = 30;

/** 動画のクリップの中を、端から端までその所のコマで埋める（編集ソフトのフィルムの帯と同じ）。
 *  コマ1つ1つが、クリップのその位置で使っている素材の時刻の絵。名前の文字は出さない
 *  （2026-11-24 本人「クリップも全部テキストで説明するんじゃなくてサムネを入れろ。実物で見せられるものは全部実物で」）。 */
function FilmTiles({ strip, aspect, widthPx, sourceStart, sourceEnd }: {
  strip: string; aspect: number; widthPx: number; sourceStart: number; sourceEnd: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [h, setH] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setH(el.clientHeight);
    const ro = new ResizeObserver(() => setH(el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const base = strip.replace(/&m=\d+$/, '');
  const tileW = Math.max(16, (h || 24) * aspect);
  const n = Math.max(1, Math.min(24, Math.ceil(widthPx / tileW)));
  const dur = Math.max(0, sourceEnd - sourceStart);
  const tiles = Array.from({ length: n }, (_, i) => {
    const frac = Math.min(1, ((i + 0.5) * tileW) / Math.max(1, widthPx));
    const t = Math.max(0, Math.min(sourceStart + dur * frac, sourceEnd - 0.05));
    const m = Math.floor(t / 60);
    const k = Math.max(0, Math.min(STRIP_FRAMES - 1, Math.floor((t % 60) / 2)));
    return { m, k };
  });
  return (
    <div ref={ref} className="pointer-events-none absolute inset-0 flex overflow-hidden" data-film-tiles={n}>
      {tiles.map(({ m, k }, i) => (
        <div key={i} className="h-full shrink-0 bg-no-repeat"
          style={{
            width: tileW,
            backgroundImage: `url(${base}&m=${m})`,
            backgroundSize: `${STRIP_FRAMES * 100}% 100%`,
            backgroundPosition: `${(k / (STRIP_FRAMES - 1)) * 100}% 0`,
          }} />
      ))}
    </div>
  );
}
const stripAspect = new Map<string, number | Promise<number>>();
function useStripAspect(url: string | undefined): number | null {
  const known = url ? stripAspect.get(url) : undefined;
  const [aspect, setAspect] = useState<number | null>(typeof known === 'number' ? known : null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    let p = stripAspect.get(url);
    if (p === undefined) {
      p = sideLoad(() => new Promise<number>((resolve) => {
        const img = new Image();
        img.decoding = 'async';
        img.onload = () => { const a = img.naturalWidth / STRIP_FRAMES / Math.max(1, img.naturalHeight); stripAspect.set(url, a); resolve(a); };
        img.onerror = () => { window.setTimeout(() => stripAspect.delete(url), 15000); resolve(0); };
        img.src = url;
      }));
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
    // 波形は細かさが要らないので、画面の倍率は1.5倍まで・横は2048点までで描く。Windows（倍率2.2倍）では
    // ズームのたびに長い音のクリップで数千本の線を描き直して、画面が止まっていた（2026-11-19）
    const dpr = Math.min(1.5, window.devicePixelRatio || 1);
    const cw = Math.max(1, Math.min(2048, Math.round(widthPx * dpr)));
    const ch = Math.max(1, Math.round((c.clientHeight || 30) * dpr));
    if (c.width !== cw) c.width = cw;
    if (c.height !== ch) c.height = ch;
    const g = c.getContext('2d');
    if (!g) return;
    g.clearRect(0, 0, cw, ch);
    // 音量0（消してある音）でも波形は薄く出す。平らにすると、音が無いのか消してあるのか分からない（2026-11-25）
    const muted = volume <= 0.02;
    g.fillStyle = muted ? (dark ? 'rgba(40,30,0,0.22)' : 'rgba(255,255,255,0.28)') : dark ? 'rgba(40,30,0,0.55)' : 'rgba(255,255,255,0.62)';
    const a = sourceStart * PEAKS_PER_SEC;
    const span = Math.max(1, (sourceEnd - sourceStart) * PEAKS_PER_SEC);
    const mid = ch / 2;
    const gain = muted ? 1 : Math.min(VOL_MAX, Math.max(0, volume));
    // 1本の線に入る山の数に合わせて、山を2つずつまとめた段から読む（長い音でも線の数だけの手間）
    const per = span / cw;
    const level = Math.max(0, Math.min(PEAK_LEVELS - 1, Math.floor(Math.log2(Math.max(1, per)))));
    const lv = peakLevel(peaks, level);
    const scale = 2 ** level;
    const path = new Path2D();
    for (let x = 0; x < cw; x += 1) {
      const i0 = Math.floor((a + (x / cw) * span) / scale);
      const i1 = Math.max(i0 + 1, Math.floor((a + ((x + 1) / cw) * span) / scale));
      let m = 0;
      for (let i = i0; i < i1 && i < lv.length; i += 1) if (lv[i] > m) m = lv[i];
      if (!m) continue;
      // 小さい音も見えるように平方根で。音量を上げ下げすると波形も大きさが変わる
      const h = Math.min(mid, Math.sqrt(m / 255) * mid * gain * 0.95);
      path.rect(x, mid - h, 1, Math.max(1, h * 2));
    }
    g.fill(path);
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

function ClipBoxInner({ clipId, left, width, widthPx, kind, label, thumb, strip, narrow, selected, linkedSelected, touch, appear, vanish, title, peaksUrl, sourceStart = 0, sourceEnd = 0, volume = 1, comment, fns }: Props) {
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
      >
        {comment ? <CommentDot state={comment} clipId={clipId} fns={fns} /> : null}
      </div>
    );
  }
  const showThumb = !!thumb && widthPx >= 40;
  return (
    <div data-clip-id={clipId} data-clip-kind={kind} className={cls} style={style} title={title} onContextMenu={(event) => fns.current.openMenu(event, clipId)}>
      {comment ? <CommentDot state={comment} clipId={clipId} fns={fns} /> : null}
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
          <FilmTiles strip={strip} aspect={aspect} widthPx={widthPx} sourceStart={sourceStart} sourceEnd={sourceEnd > sourceStart ? sourceEnd : sourceStart + 2} />
        ) : showThumb ? (
          // 画像は、その画像を端から端まで並べる
          <div className="pointer-events-none absolute inset-0 bg-repeat-x" data-image-tiles
            style={{ backgroundImage: `url(${thumb})`, backgroundSize: 'auto 100%' }} />
        ) : null}
        {/* 絵が出ている時は名前の文字を出さない（名前はマウスを乗せた時の札に）。声は波形がその中身なので名前を出さない。
            BGM・効果音は何の音かが絵で分からないので名前を残す */}
        {(strip && aspect && widthPx >= 40) || showThumb || (kind === 'voice' && peaksUrl) ? null : (
          <span className={`truncate px-1 ${isAudio ? 'self-start pt-[1px] text-[9px] leading-tight drop-shadow-[0_1px_1px_rgba(0,0,0,0.6)]' : ''} ${look.dark && isAudio ? 'drop-shadow-none' : ''}`}>{label}</span>
        )}
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
