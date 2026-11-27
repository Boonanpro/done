'use client';

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import type { EditSequence, SequenceAsset, SequenceClip } from './video-review-editor';
import { useContext } from 'react';
import { CaptionEditContext } from './caption-word-edit';
import { CaptionLayer, type RenderCaption } from './caption-layer';
import type { CaptionDesign } from './caption-design';
import { FrameSourceManager, webCodecsSupported } from './frame-source';
import { SceneLayer, isSceneClip, type SceneClip } from './scene-layer';
import { byLane, stackBands, visualLane } from './lane-order';
import { gradeFilter } from './grade-filter';
import { ALPHA_ASSET_IDS, alphaSolidAt, unpackStacked } from './alpha-unpack';
import { AudioSourceManager, STRETCH_BLOCK_SEC, audioOnlyUrl, webAudioSupported } from './audio-source';
import { localMedia, localMediaEnabled, localPlaySrc, type LocalMediaProgress } from './local-media';
import { setMediaElementSrc, startMediaRoute } from './media-route';
import { feelDrawn, feelFrozen, feelSeek, feelStall, feelStart } from './editor-feel';
import { isOneForm, motionAt, pictureRect, visibleRect, cropOf, setKeyAt, sortedKeys, type Motion } from './placement';
import { drawRegionEffect, isRegionEffect } from './region-effect';

// Live timeline compositor. Draws the current edit (base video + overlay/PiP layers +
// captions + blur) onto a <canvas> for the playhead time, so manual edits reflect
// immediately. The full-quality export stays in the server-side renderer.
//
// VIDEO frames come from a WebCodecs decode cache (frame-source.ts): one decoder per ASSET,
// frames kept decoded in RAM. Edits only reshuffle which cached frame draws where — media is
// never reloaded, so there's no black/stall on edit and scrubbing is frame-accurate (the old
// <video>-element-per-clip pool reloaded on every edit = the instability we replaced).
// AUDIO still rides on hidden <video> elements (WebCodecs is video-only and audio re-seek
// glitches are far less jarring than black video).

type Props = {
  sequence: EditSequence | null;
  assets: SequenceAsset[];
  // Resolve the active blur boxes AT a given time (normalized output coords, tracked position
  // already resolved). Called inside drawFrame with the playback clock so the box is evaluated
  // at the same instant as the video frame (no lag = no peeking).
  blurRegionsAt?: (t: number) => Array<{ x: number; y: number; width: number; height: number }>;
  currentTime: number;
  /** 利用者が再生位置を動かすたびに増える。再生中に増えたら、その位置から再生を続ける。 */
  seekRev?: number;
  playing: boolean;
  format: string;
  onTimeChange: (t: number) => void;
  onEnded: () => void;
  className?: string;
  // Direct-manipulation of a clip's position/transform in the preview.
  selectedClipId?: string | null;
  selectedClipIds?: string[];
  onGroupMove?: (patches: Map<string, Partial<SequenceClip>>) => void;
  onPositionChange?: (clipId: string, position: { x: number; y: number; width: number; height: number }) => void;
  onTransformChange?: (clipId: string, transform: { scale: number; x: number; y: number }) => void;
  /** プレビューの上で押した物（テロップ・重ねた絵・映像）を選ぶ。何も無い所なら null */
  onPick?: (clipId: string | null) => void;
  /** プレビューの上でマウスを置いた・押した所（画面の幅・高さに対する割合と、そこにある物。上の物から）。
   *  外れたら null。通話で「ここ」と言った時にダンが指した所を分かるため（2026-11-17） */
  onPoint?: (point: { x: number; y: number; ids: string[]; pressed: boolean } | null) => void;
  /** 選んだテロップをプレビューの上で引きずって動かした（x・y は画面の幅・高さに対する割合のずれ） */
  onCaptionMove?: (clipId: string, nudge: { x: number; y: number }) => void;
  /** 再生の速さ（1 = 等倍。L キーで 2・3…）。音は声の高さを変えずに速くする */
  rate?: number;
  /** この速さ以上は鍵のコマだけを拾って見せる（スマホは4、PC は5） */
  skimFrom?: number;
};

type VisualClip = {
  clip: SequenceClip;
  kind: 'base' | 'overlay';
  layer: number;
  position: { x: number; y: number; width: number; height: number } | null;
};

function assetSrc(a: SequenceAsset): string {
  if (a.url) return a.url;
  if (a.path) return `/api/v1/video-review/media?path=${encodeURIComponent(a.path)}`;
  return '';
}

function canvasDims(format: string): { w: number; h: number } {
  const [a, b] = (format || '9:16').split(':').map(Number);
  const ratio = a && b ? a / b : 9 / 16;
  const MAX = 900; // longest side of the preview canvas
  return ratio >= 1 ? { w: MAX, h: Math.round(MAX / ratio) } : { w: Math.round(MAX * ratio), h: MAX };
}

function isOverlayClip(clip: SequenceClip, trackType: string | undefined): boolean {
  return trackType === 'overlay' || clip.composition === 'pip' || clip.composition === 'overlay';
}

// cover-draw a decoded frame into a destination rect (object-fit: cover).
function drawCover(
  ctx: CanvasRenderingContext2D,
  src: CanvasImageSource,
  vw: number,
  vh: number,
  dx: number,
  dy: number,
  dw: number,
  dh: number,
) {
  if (!vw || !vh) return;
  const scale = Math.max(dw / vw, dh / vh);
  const sw = dw / scale;
  const sh = dh / scale;
  const sx = (vw - sw) / 2;
  const sy = (vh - sh) / 2;
  ctx.drawImage(src, sx, sy, sw, sh, dx, dy, dw, dh);
}

// Non-destructive placement: draw the FULL source frame (no crop) into the box, scaled to
// cover the box by default (identical to drawCover when transform is identity), then
// zoomed/panned by `transform`. Overflow is CLIPPED by the box window, so source pixels
// outside the frame are preserved and revealed when scale<1 or when panned.
function drawSource(
  ctx: CanvasRenderingContext2D,
  src: CanvasImageSource,
  vw: number, vh: number,
  dx: number, dy: number, dw: number, dh: number,
  transform: { scale: number; x: number; y: number } | null | undefined,
  outW: number, outH: number,
  crop?: { top: number; bottom: number; left: number; right: number } | null,
) {
  if (!vw || !vh) return;
  const s = transform?.scale ?? 1;
  const tx = transform?.x ?? 0;
  const ty = transform?.y ?? 0;
  const cover = Math.max(dw / vw, dh / vh);
  const destW = vw * cover * s;
  const destH = vh * cover * s;
  const destX = dx + (dw - destW) / 2 + tx * outW;
  const destY = dy + (dh - destH) / 2 + ty * outH;
  // crop = a MASK: keep only the inner region of the placed frame; trimmed edges aren't
  // painted, so whatever is underneath shows there. Visible content stays at the same place
  // and size — no zoom.
  const cl = Math.max(0, Math.min(0.95, crop?.left ?? 0));
  const cr = Math.max(0, Math.min(0.95, crop?.right ?? 0));
  const ctp = Math.max(0, Math.min(0.95, crop?.top ?? 0));
  const cb = Math.max(0, Math.min(0.95, crop?.bottom ?? 0));
  const sx = vw * cl;
  const sy = vh * ctp;
  const sw = Math.max(1, vw * (1 - cl - cr));
  const sh = Math.max(1, vh * (1 - ctp - cb));
  const dkX = destX + destW * cl;
  const dkY = destY + destH * ctp;
  const dkW = destW * (1 - cl - cr);
  const dkH = destH * (1 - ctp - cb);
  ctx.save();
  ctx.beginPath();
  ctx.rect(dx, dy, dw, dh);
  ctx.clip();
  ctx.drawImage(src, sx, sy, sw, sh, dkX, dkY, dkW, dkH);
  ctx.restore();
}

// Box motion at a clip-relative time: linear between keys, held before/after.
function boxKeyAt(keys: unknown, rel: number): { x: number; y: number; w: number; h: number } | null {
  if (!Array.isArray(keys) || keys.length === 0) return null;
  const ks = keys as Array<{ t: number; x: number; y: number; w: number; h: number }>;
  if (rel <= ks[0].t) return ks[0];
  for (let i = 1; i < ks.length; i += 1) {
    const a = ks[i - 1];
    const b = ks[i];
    if (rel < b.t) {
      const f = (rel - a.t) / Math.max(1e-6, b.t - a.t);
      return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, w: a.w + (b.w - a.w) * f, h: a.h + (b.h - a.h) * f };
    }
  }
  return ks[ks.length - 1];
}

function isFrozen(clip: SequenceClip): boolean {
  return clip.source_end != null && Number(clip.source_end) <= Number(clip.source_start || 0);
}
// クリップの速さ（1.08 なら元の素材を1.08倍で流す。タイムラインの1秒＝素材の1.08秒）
function clipSpeed(clip: SequenceClip): number {
  const s = Number(clip.speed);
  return Number.isFinite(s) && s > 0 ? s : 1;
}
// 素材の映像の長さ（読み込んだ目次から。素材の住所ごと）と、素材→住所。
// 範囲が素材の終わりより先を指すクリップ（壊れた切り方の跡など）は、最後の絵で止めて見せる。
// 素材に無い時刻の絵を待つと、再生を押すたびに6秒止まっていた（2026-11-25 X固定ポスト 1:36）。
const MEDIA_END_BY_SRC = new Map<string, number>();
const SRC_BY_ASSET = new Map<string, string>();
function clipSourceTime(clip: SequenceClip, t: number): number {
  const raw = Number(clip.source_start || 0) + (isFrozen(clip) ? 0 : (t - clip.timeline_start) * clipSpeed(clip));
  const src = SRC_BY_ASSET.get(String(clip.asset_id || ''));
  const end = src ? MEDIA_END_BY_SRC.get(src) : undefined;
  if (end && end > 0.1 && raw > end - 0.05) return end - 0.05;
  return raw < 0 ? 0 : raw;
}

// この段の映像が画面を全部ふさぐか（ふさぐなら、それより下の段は見えない）。
// 絵（画像）は透けている所があるかもしれないので、ふさがない扱い。迷う物はふさがない扱いにする
// （その時は下の段もそろうまで待つだけで、間違った絵は出ない）。
// A transparent video's watching copy is stacked (colour over alpha): join it back into one
// picture with real transparency before it is placed (alpha-unpack.ts).
function joinAlpha(clip: SequenceClip, got: { src: CanvasImageSource; vw: number; vh: number }): { src: CanvasImageSource; vw: number; vh: number } {
  const id = String(clip.asset_id || '');
  if (!ALPHA_ASSET_IDS.has(id)) return got;
  return unpackStacked(id, got.src, got.vw, got.vh) || { ...got, vh: got.vh / 2 };
}

function coversFrame(vc: VisualClip, imageAssets: Map<string, string>): boolean {
  const c = vc.clip;
  if (imageAssets.has(String(c.asset_id || ''))) return false;
  if (ALPHA_ASSET_IDS.has(String(c.asset_id || ''))) return false; // 透明な映像は下の段を隠さない
  if (c.opacity != null && Number(c.opacity) < 0.999) return false;
  const shape = (c as { shape?: string }).shape;
  if (shape === 'circle' || shape === 'rounded') return false;
  if (Array.isArray(c.transform_keys) && c.transform_keys.length) return false;
  if (Array.isArray(c.motion_keys) && c.motion_keys.length) return false;
  if (c.fit === 'contain') return false;
  const p = vc.position;
  if (p && !(p.x <= 0.001 && p.y <= 0.001 && p.x + p.width >= 0.999 && p.y + p.height >= 0.999)) return false;
  const cr = c.crop;
  if (cr && (Number(cr.top) > 0.001 || Number(cr.bottom) > 0.001 || Number(cr.left) > 0.001 || Number(cr.right) > 0.001)) return false;
  const tf = c.transform;
  if (tf && (Number(tf.scale) < 0.999 || Math.abs(Number(tf.x)) > 0.001 || Math.abs(Number(tf.y)) > 0.001)) return false;
  return true;
}

// 確かめ用の数（?previewdiag=1 の試しの道具が読む）
type PreviewStats = { stalls?: number; seqChanges?: number; startWaits?: number[]; frozenMs?: number; avN?: number; avSum?: number; avMax?: number; avOver?: number; draws: number; holds: number; wrongDraws: number; lastWrong: number; audioGapMs: number; audioLateStarts: number; audioScheduled: number; audioMode: string };
function previewStats(): PreviewStats {
  const w = window as unknown as { __previewStats?: PreviewStats };
  if (!w.__previewStats) w.__previewStats = { draws: 0, holds: 0, wrongDraws: 0, lastWrong: -1, audioGapMs: 0, audioLateStarts: 0, audioScheduled: 0, audioMode: '' };
  return w.__previewStats;
}

let pumpCanvas: CanvasRenderingContext2D | null = null;
function pumpCtx(): CanvasRenderingContext2D | null {
  if (!pumpCanvas && typeof document !== 'undefined') {
    const c = document.createElement('canvas');
    c.width = 1; c.height = 1;
    pumpCanvas = c.getContext('2d');
  }
  return pumpCanvas;
}

function urlFlag(name: string): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get(name);
}

// 字幕だけを毎コマ動かす（再生中、エディター本体は 8回/秒しか時刻を受け取らないため）。
function LiveCaptionLayer({ playing, currentTime, clockRef, outW, outH, captions }: {
  playing: boolean;
  currentTime: number;
  clockRef: React.MutableRefObject<{ wall: number; t: number } | null>;
  outW: number;
  outH: number;
  captions: RenderCaption[];
}) {
  const [liveT, setLiveT] = useState(currentTime);
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const loop = () => {
      const c = clockRef.current;
      if (c) setLiveT((prev) => (Math.abs(prev - c.t) > 0.008 ? c.t : prev));
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, clockRef]);
  return <CaptionLayer outW={outW} outH={outH} captions={captions} time={playing ? liveT : currentTime} />;
}

const BLEND_OPS: Record<string, GlobalCompositeOperation> = {
  screen: 'screen', add: 'lighter', lighten: 'lighten', multiply: 'multiply', overlay: 'overlay', softlight: 'soft-light',
};

// プレビューを描く画素の倍率の上限: 長い辺 1920px まで（書き出しの 1080p と同じ細かさ）
const MAX_CANVAS_LONG_SIDE = 1920;

export function TimelinePreview({ sequence, assets, blurRegionsAt, currentTime, seekRev = 0, playing, format, onTimeChange, onEnded, className, selectedClipId, selectedClipIds, onGroupMove, onPositionChange, onTransformChange, onPick, onPoint, onCaptionMove, rate: rateProp = 1, skimFrom = 5 }: Props) {
  const rate = Number.isFinite(rateProp) && rateProp > 0 ? rateProp : 1;
  const rateRef = useRef(rate);
  rateRef.current = rate;
  // skimFrom 倍以上は、動画の要素を速回しせず、鍵のコマ（画面用の写しで0.5秒おき）だけを拾って見せる。
  // 要素を5倍・10倍で回すと解読が追いつかず、絵がほとんど止まったままになった（2026-11-19 スマホの幅で測った）。
  // スマホは4倍から（S24 で要素を4〜4.9倍で回すと、映像が声から最大0.8秒遅れ、12秒に1.4秒止まった）。
  // PC の L（4倍まで）は今までどおり要素を回す。
  const SKIM_KEYS_RATE = skimFrom;
  const skimKeysRef = useRef(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  // WebCodecs frame decoders, one per asset URL (shared across all clips of that asset). Used
  // for the PAUSED / SCRUB / EDIT state — frame-accurate, never reloads on edit (no black).
  const framesRef = useRef<FrameSourceManager>(null as unknown as FrameSourceManager);
  if (!framesRef.current) framesRef.current = new FrameSourceManager();
  // Muted <video> elements for VIDEO clips — drawn to the canvas ONLY during PLAYBACK. Hardware
  // decode + real-time playback keeps them naturally in sync with the audio <video> elements,
  // exactly like a native NLE's playback pipeline. They're never drawn while paused, so their
  // reconcile churn on edits is invisible (the paused canvas draws from WebCodecs).
  const videosRef = useRef<Map<string, HTMLVideoElement>>(new Map());
  // Hidden <video> elements for AUDIO — one per audio clip (recycled by asset).
  const audiosRef = useRef<Map<string, HTMLVideoElement>>(new Map());
  const rafRef = useRef<number | null>(null);
  const playClockRef = useRef<{ wall: number; t: number } | null>(null);
  const prevActiveAudioRef = useRef<Set<string>>(new Set());
  const prevActiveVideoRef = useRef<Set<string>>(new Set());
  // drawFrame reads this to pick its source: <video> elements during playback, WebCodecs when paused.
  const playingRef = useRef(playing);
  playingRef.current = playing;

  const supported = useMemo(() => webCodecsSupported(), []);
  // 比べる時だけ前の作りに戻せる: ?previewfix=0（段のそろえ）・?webaudio=0（音を前の <video> で鳴らす）
  const fixLayers = useMemo(() => urlFlag('previewfix') !== '0', []);
  // ?syncstart=0 で前の作り: 映像の準備を待たずに時計と音を走らせていた
  const gateRef = useRef(urlFlag('syncstart') !== '0');
  // 再生中に位置を動かした時、再生の輪に「その位置でそろえ直して」と伝える
  const prepRequestRef = useRef(false);
  // 再生が流れている最中か（準備中ではない）。段の中身が変わって再生の輪を作り直した時に、止めずに続けるため
  const runningRef = useRef(false);
  const useWebAudio = useMemo(() => urlFlag('webaudio') !== '0' && webAudioSupported() && supported, [supported]);
  // Web Audio が作れなかった時だけ、前の <video> で音を鳴らす
  const [webAudioBroken, setWebAudioBroken] = useState(false);
  const dims = useMemo(() => canvasDims(format), [format]);
  // キャンバスは画面に出ている大きさ×画面の細かさで描く（前は長い辺 900px 固定を引き伸ばしていて、ぼやけていた）。
  // 座標は今までどおり dims（900 基準）で計算し、描く時だけ倍率をかける。
  const [pxScale, setPxScale] = useState(1);
  const pxScaleRef = useRef(1);
  pxScaleRef.current = pxScale;
  // Opt-in on-screen diagnostic (append ?previewdiag=1 to the URL). Shows the playhead time, whether
  // the last paint was LIVE (drew a fresh frame) or HOLD (kept the previous frame because the new one
  // wasn't decoded yet), and the source time on screen — so playback/scrub can be judged on real
  // hardware via a screenshot instead of relying on headless tests.
  const showDiag = useMemo(() => typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('previewdiag') === '1', []);
  const diagRef = useRef<HTMLDivElement | null>(null);
  // Bumped when an asset's decoder finishes loading, so the scrub effect re-runs and paints the
  // first frame the moment it's decodable (the initial decode resolves async after the canvas
  // has already mounted — without this, the opening frame stayed black until you scrubbed).
  const [readyTick, setReadyTick] = useState(0);
  // Media load progress for the "preparing…" overlay: how many of the assets used by this
  // timeline have their decoder ready. Lets the user see "loading", not "broken", during the
  // few-second media load on open (like a native NLE's loading bar).
  const [loadProgress, setLoadProgress] = useState({ ready: 0, total: 0 });
  const readyUrlsRef = useRef<Set<string>>(new Set());

  const videoAssets = useMemo(() => (assets || []).filter((a) => assetSrc(a) && a.kind !== 'image'), [assets]);
  // Still pictures (generated art, imported logos, Dan-made caption plates) are drawn from an
  // <img>, loaded on first use; the canvas repaints when one arrives.
  const imageSrcByAssetId = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of assets || []) { const s = assetSrc(a); if (s && a.kind === 'image') m.set(a.id, s); }
    return m;
  }, [assets]);
  const imagesRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const imageFor = useCallback((url: string): HTMLImageElement | null => {
    let img = imagesRef.current.get(url);
    if (!img) {
      img = new Image();
      img.decoding = 'async';
      img.onload = () => setReadyTick((v) => v + 1);
      img.src = url;
      imagesRef.current.set(url, img);
    }
    return img.complete && img.naturalWidth ? img : null;
  }, []);

  const assetById = useMemo(() => {
    const m = new Map<string, SequenceAsset>();
    for (const a of videoAssets) m.set(a.id, a);
    return m;
  }, [videoAssets]);

  // asset_id -> decode source URL (the proxy). Memoised so frame lookups are cheap per draw.
  const srcByAssetId = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of videoAssets) {
      const s = assetSrc(a);
      if (s) { m.set(a.id, s); SRC_BY_ASSET.set(a.id, s); }
      if (a.alpha === 'stacked') ALPHA_ASSET_IDS.add(a.id); else ALPHA_ASSET_IDS.delete(a.id);
    }
    return m;
  }, [videoAssets]);

  // 作品の中身が何回入れ替わったか（確かめの道具が、再生中にダンの直しが届いた時の入れ替わりの回数を見る）
  useEffect(() => { const st = previewStats(); st.seqChanges = (st.seqChanges || 0) + 1; }, [sequence]);
  const sequenceDuration = useMemo(() => {
    const tracks = sequence?.tracks || [];
    return Math.max(0, ...tracks.flatMap((t) => (t.clips || []).map((c) => c.timeline_end || 0)), Number(sequence?.duration || 0));
  }, [sequence]);

  // flat visual clips (base + overlay), with layer + position
  const visualClips = useMemo<VisualClip[]>(() => {
    const out: VisualClip[] = [];
    let visualIndex = -1;
    for (const track of sequence?.tracks || []) {
      if (track.type !== 'audio') visualIndex += 1;
      // A picture placed on a caption lane (a designed caption plate) draws like an overlay.
      if (track.type === 'caption') {
        for (const clip of track.clips || []) {
          if (!clip.asset_id || isSceneClip(clip)) continue;
          out.push({ clip, kind: 'overlay', layer: visualLane(track.type, clip, visualIndex), position: (clip.position as VisualClip['position']) || null });
        }
        continue;
      }
      if (track.type !== 'video' && track.type !== 'overlay') continue;
      for (const clip of track.clips || []) {
        // a caption Dan put on a picture lane is drawn by the caption layer, not as a picture
        if (clip.track === 'caption' && !clip.asset_id) continue;
        if (isSceneClip(clip)) continue; // drawn by <SceneLayer>, not the canvas
        // a region effect (mosaic / blur / frame…) is not a picture: it processes what is below it (regionFx)
        if (isRegionEffect(clip)) continue;
        const overlay = isOverlayClip(clip, track.type);
        // A pop-out clip is drawn by the editor's canvas overlay (matted person breaking out of a
        // rounded card); skip its plain-wipe rendering here so no sharp-cornered rectangle peeks
        // out behind the rounded card.
        if (overlay && (clip.effects || []).some((e) => e.type === 'popout')) continue;
        out.push({
          clip,
          kind: overlay ? 'overlay' : 'base',
          // the lane the timeline shows it on (lane-order.ts: the same rule as the timeline and the export)
          layer: visualLane(track.type, clip, visualIndex),
          position: (clip.position as VisualClip['position']) || null,
        });
      }
    }
    return out.sort((a, b) => a.layer - b.layer); // draw bottom (low layer) first
  }, [sequence]);

  // 段（前後）: 上の段ほど前。テロップ・場面・絵と映像のどれも、作品に入った順ではなく段で重ねる（lane-order.ts）
  const laneById = useMemo(() => {
    const m = new Map<string, number>();
    let visualIndex = -1;
    for (const track of sequence?.tracks || []) {
      if (track.type === 'audio') continue;
      visualIndex += 1;
      for (const clip of track.clips || []) if (clip.id != null) m.set(String(clip.id), visualLane(track.type, clip, visualIndex));
    }
    return m;
  }, [sequence]);
  const captionClips = useMemo(
    // what a clip IS comes from its fields, not its lane (timeline_commands): captions on any lane
    () => byLane(
      (sequence?.tracks || []).flatMap((t) => (t.clips || []).filter((c) => t.type === 'caption' || c.track === 'caption')),
      (c) => laneById.get(String(c.id)) ?? 0,
    ),
    [sequence, laneById],
  );

  const renderCaptions = useMemo<RenderCaption[]>(
    () =>
      captionClips
        .filter((c) => typeof c.text === 'string')
        .map((c) => ({
          id: String(c.id),
          text: String(c.text),
          start: Number(c.timeline_start || 0),
          end: Number(c.timeline_end || 0),
          design: (c.style || {}) as CaptionDesign,
          words: c.words || undefined,
          transform_keys: c.transform_keys,
          opacity: c.opacity,
        })),
    [captionClips],
  );

  // Editable scenes (HTML + one GSAP timeline), drawn over the canvas by the same frame the export uses.
  const sceneClips = useMemo<SceneClip[]>(
    () => byLane(
      (sequence?.tracks || []).filter((t) => t.type !== 'audio' && !(t as { hidden?: boolean }).hidden)
        .flatMap((t) => (t.clips || []).filter(isSceneClip)),
      (c) => laneById.get(String(c.id)) ?? 0,
    ),
    [sequence, laneById],
  );

  // 重ねる層: 下から順に「絵と映像（canvas）」「場面」「テロップ」の層を、段の上下どおりに積む。
  // 絵と映像がテロップより上の段にあれば、その絵はテロップの上の別の canvas に描く。同じ段の物は重ならない
  // （1つの段に同じ時刻の物は置けない）ので、層の数が増えないよう絵→場面→テロップの順にまとめる。
  const stack = useMemo(() => stackBands([
    ...visualClips.map((vc) => ({ kind: 'pic' as const, layer: vc.layer, id: String(vc.clip.id) })),
    ...sceneClips.map((c) => ({ kind: 'scene' as const, layer: laneById.get(String(c.id)) ?? 0, id: String(c.id) })),
    ...renderCaptions.map((c) => ({ kind: 'cap' as const, layer: laneById.get(String(c.id)) ?? 0, id: String(c.id) })),
  ]), [visualClips, sceneClips, renderCaptions, laneById]);
  const stackRef = useRef(stack);
  stackRef.current = stack;
  // 上の段の絵を描く canvas（1枚目は canvasRef）。描いた物が残っている canvas だけ消す。
  const upperCanvasRefs = useRef<Array<HTMLCanvasElement | null>>([]);
  const upperDirty = useRef<boolean[]>([]);

  // 範囲の効果（モザイク・ぼかし・枠…）と、その段。effect の段の物も、add_region が映像の段に置いた物も同じ。
  // 書き出しと同じく、その段より下に重なった絵を加工する（region-effect.ts）。
  const regionFx = useMemo(() => {
    const out: Array<{ clip: SequenceClip; layer: number }> = [];
    let visualIndex = -1;
    for (const track of sequence?.tracks || []) {
      if (track.type === 'audio') continue;
      visualIndex += 1;
      if ((track as { hidden?: boolean }).hidden) continue;
      for (const clip of track.clips || []) {
        if (!isRegionEffect(clip)) continue;
        out.push({ clip, layer: visualLane(track.type, clip, visualIndex) });
      }
    }
    return out.sort((a, b) => a.layer - b.layer);
  }, [sequence]);

  const audioClips = useMemo(
    () => (sequence?.tracks || []).filter((t) => t.type === 'audio').flatMap((t) => t.clips || []),
    [sequence],
  );

  // 鳴らす音のクリップと音量（書き出しと同じ決め方: 段の消音・ソロ、クリップの volume）
  const audibleAudio = useMemo(() => {
    type T = { id: string; type: string; muted?: boolean; solo?: boolean; clips?: SequenceClip[] };
    const tracks = (sequence?.tracks || []) as T[];
    const linkOwner = new Map<string, T>();
    for (const t of tracks) if (t.type !== 'audio') for (const c of t.clips || []) if (c.link_id && !linkOwner.has(c.link_id)) linkOwner.set(c.link_id, t);
    const anySolo = tracks.some((t) => t.solo);
    const out: Array<{ clip: SequenceClip; gain: number }> = [];
    for (const t of tracks) {
      if (t.type !== 'audio') continue;
      for (const c of t.clips || []) {
        if (!c.asset_id) continue;
        const gov = (c.link_id && linkOwner.get(c.link_id)) || t;
        if (gov.muted || (anySolo && !gov.solo)) continue;
        const gain = c.volume == null ? 1 : Math.max(0, Math.min(2, Number(c.volume)));
        out.push({ clip: c, gain: Number.isFinite(gain) ? gain : 1 });
      }
    }
    return out.sort((a, b) => a.clip.timeline_start - b.clip.timeline_start);
  }, [sequence]);

  // Caption overlay rect (CSS-scaled to sit exactly over the contained video). Measured via RO.
  const [contentRect, setContentRect] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => {
      const cw = el.clientWidth;
      const ch = el.clientHeight;
      if (!cw || !ch) return;
      const aspect = dims.w / dims.h;
      let w = cw;
      let h = cw / aspect;
      if (h > ch) { h = ch; w = ch * aspect; }
      setContentRect({ left: (cw - w) / 2, top: (ch - h) / 2, width: w, height: h });
      const dpr = window.devicePixelRatio || 1;
      const cap = MAX_CANVAS_LONG_SIDE / Math.max(dims.w, dims.h);
      const want = Math.min(cap, Math.max(1, (w * dpr) / dims.w));
      setPxScale(Math.round(want * 4) / 4 || 1);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [dims.w, dims.h]);

  // Keep a decoder alive for each asset URL currently used by a visual clip; drop the rest.
  // readyTick must bump ONCE per source (when it first decodes), NOT on every render — the chat
  // panel re-renders constantly, and re-attaching .ready.then() each time (it resolves instantly
  // for an already-loaded source) would fire readyTick on every render and re-seek the paused
  // preview forever (= juddering). attachedReadyRef tracks which sources we've already hooked.
  const attachedReadyRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const wanted = new Set<string>();
    for (const vc of visualClips) {
      const src = srcByAssetId.get(String(vc.clip.asset_id || ''));
      if (src) wanted.add(src);
    }
    framesRef.current.retain(wanted);
    const countReady = () => setLoadProgress({ ready: [...wanted].filter((u) => readyUrlsRef.current.has(u)).length, total: wanted.size });
    countReady();
    for (const src of wanted) {
      const fs = framesRef.current.get(src); // kick off decoder init
      if (fs && !attachedReadyRef.current.has(src)) {
        attachedReadyRef.current.add(src);
        fs.ready.then(() => { if (fs.duration > 0) MEDIA_END_BY_SRC.set(src, fs.duration); readyUrlsRef.current.add(src); setReadyTick((v) => v + 1); countReady(); }).catch(() => { readyUrlsRef.current.add(src); countReady(); });
      }
    }
    for (const u of [...attachedReadyRef.current]) if (!wanted.has(u)) attachedReadyRef.current.delete(u);
  }, [visualClips, srcByAssetId]);

  // Audio elements — ONE PER AUDIO CLIP (keyed by clip id), recycled by asset to avoid reloads.
  const PRELOAD_BEHIND = 6;
  const PRELOAD_AHEAD = 16;
  const WINDOW_STEP = 3;
  const loadBucket = Math.floor((currentTime || 0) / WINDOW_STEP);
  // 映像の要素は、今と、この先数秒に始まるクリップの分だけ持つ。前は前後22秒ぶん（スヤさん1本目で約8本）を
  // 全部読み込ませていて、同じ録画を8本が奪い合い、今のクリップの要素が読み込めずに映像が止まっていた
  // （家の外の回線で、再生を押しても3秒間ずっと絵が止まったまま。2026-11-13）。
  const VIDEO_BEHIND = 0.5;
  const VIDEO_AHEAD = 4;
  const videoBucket = Math.floor((currentTime || 0) / 1);
  useEffect(() => {
    const map = audiosRef.current;
    if (useWebAudio && !webAudioBroken) { for (const [, el] of map) el.remove(); map.clear(); return; }
    const lo = (currentTime || 0) - PRELOAD_BEHIND;
    const hi = (currentTime || 0) + PRELOAD_AHEAD;
    const wanted = new Map<string, string>();
    for (const c of audioClips) {
      const aid = String(c.asset_id || '');
      if (!aid) continue;
      if (c.timeline_end >= lo && c.timeline_start <= hi) wanted.set(String(c.id), aid);
    }
    const orphansByAsset = new Map<string, HTMLVideoElement[]>();
    for (const [cid, el] of map) {
      if (!wanted.has(cid)) {
        const aid = el.dataset.assetId || '';
        (orphansByAsset.get(aid) || orphansByAsset.set(aid, []).get(aid)!).push(el);
        map.delete(cid);
      }
    }
    for (const [cid, aid] of wanted) {
      if (map.has(cid)) continue;
      const recycled = orphansByAsset.get(aid)?.pop();
      if (recycled) { map.set(cid, recycled); continue; }
      const a = assetById.get(aid);
      if (!a) continue;
      const v = document.createElement('video');
      setMediaElementSrc(v, localPlaySrc(assetSrc(a)));
      v.dataset.assetId = aid;
      v.muted = true;
      v.playsInline = true;
      v.preload = 'auto';
      v.style.display = 'none';
      document.body.appendChild(v);
      map.set(cid, v);
    }
    for (const list of orphansByAsset.values()) for (const el of list) el.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioClips, assetById, loadBucket, useWebAudio, webAudioBroken]);

  // Muted VIDEO <video> elements — one per visual clip near the playhead, recycled by asset so a
  // split/ripple reuses an already-decoded element (no reload). These are only drawn during
  // playback; while paused the canvas comes from WebCodecs, so this reconcile is never visible.
  useEffect(() => {
    const map = videosRef.current;
    const lo = (currentTime || 0) - VIDEO_BEHIND;
    const hi = (currentTime || 0) + VIDEO_AHEAD;
    const wanted = new Map<string, string>();
    for (const vc of visualClips) {
      const aid = String(vc.clip.asset_id || '');
      if (!aid || !assetById.has(aid)) continue;
      if (vc.clip.timeline_end >= lo && vc.clip.timeline_start <= hi) wanted.set(String(vc.clip.id), aid);
    }
    const orphansByAsset = new Map<string, HTMLVideoElement[]>();
    for (const [cid, el] of map) {
      if (!wanted.has(cid)) {
        const aid = el.dataset.assetId || '';
        (orphansByAsset.get(aid) || orphansByAsset.set(aid, []).get(aid)!).push(el);
        map.delete(cid);
      }
    }
    for (const [cid, aid] of wanted) {
      if (map.has(cid)) continue;
      const recycled = orphansByAsset.get(aid)?.pop();
      if (recycled) { map.set(cid, recycled); continue; }
      const a = assetById.get(aid);
      if (!a) continue;
      const v = document.createElement('video');
      setMediaElementSrc(v, localPlaySrc(assetSrc(a)));
      v.dataset.assetId = aid;
      v.muted = true; // audio comes from the dedicated audio elements
      v.playsInline = true;
      v.preload = 'auto';
      v.style.display = 'none';
      document.body.appendChild(v);
      map.set(cid, v);
    }
    // 使わなくなった要素は読み込みも止める（DOM から外すだけでは読み込みが続いて回線を取る）
    for (const list of orphansByAsset.values()) for (const el of list) { el.pause(); el.removeAttribute('src'); try { el.load(); } catch { /* noop */ } el.remove(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visualClips, assetById, videoBucket]);

  // full unmount cleanup
  useEffect(() => {
    const amap = audiosRef.current;
    const vmap = videosRef.current;
    const frames = framesRef.current;
    return () => {
      for (const [, el] of amap) el.remove();
      for (const [, el] of vmap) el.remove();
      amap.clear();
      vmap.clear();
      frames.closeAll();
    };
  }, []);

  // --- 音（Web Audio）: 前もって解読し、Web Audio の時計でクリップの境目ぴったりに鳴らす ---------------
  const audioMgrRef = useRef<AudioSourceManager | null>(null);
  // 鳴らし中の音の部品（クリップ×解読の区切りごと）。null = 鳴らす物が無いと決まった所
  const audioNodesRef = useRef<Map<string, { node: AudioBufferSourceNode; gain: GainNode; t0: number; t1: number } | null>>(new Map());
  // 再生の時刻と Web Audio の時計の対応: ctxT0（Web Audio の時刻）に、タイムラインの t0 が聞こえる
  // rate: その対応を作った時の再生の速さ（ctx の1秒にタイムラインが rate 秒進む）
  const audioAnchorRef = useRef<{ ctxT0: number; t0: number; rate: number } | null>(null);
  useEffect(() => {
    if (!useWebAudio) return;
    let mgr: AudioSourceManager;
    try { mgr = new AudioSourceManager(); } catch { queueMicrotask(() => setWebAudioBroken(true)); return; }
    audioMgrRef.current = mgr;
    if (showDiag) (window as unknown as { __previewAudio?: AudioSourceManager }).__previewAudio = mgr; // 確かめの道具が出口の音を録る
    // ブラウザは、人が操作するまで音を出させない。最初に押した・キーを打った時に動かす
    const wake = () => { if (mgr.ctx.state !== 'running') void mgr.ctx.resume().catch(() => {}); };
    window.addEventListener('pointerdown', wake, true);
    window.addEventListener('keydown', wake, true);
    wake();
    return () => {
      window.removeEventListener('pointerdown', wake, true);
      window.removeEventListener('keydown', wake, true);
      for (const v of audioNodesRef.current.values()) if (v) { try { v.node.stop(); } catch { /* noop */ } v.gain.disconnect(); }
      audioNodesRef.current.clear();
      audioMgrRef.current = null;
      mgr.close();
    };
  }, [useWebAudio, showDiag]);

  const stopAudioNodes = useCallback(() => {
    for (const v of audioNodesRef.current.values()) if (v) { try { v.node.stop(); } catch { /* noop */ } v.gain.disconnect(); }
    audioNodesRef.current.clear();
    audioNodeSigRef.current.clear();
  }, []);
  // 予約した音の部品が、どのクリップの形（素材・位置・範囲・速さ・大きさ）で作った物か。
  // 再生中に作品が変わった時（ダンの直し・本人の直し）、形の変わったクリップ・消えたクリップの予約だけ止めて
  // 今の形で予約し直す。前は古い予約が鳴り続け、切ったクリップの後ろ半分と元の音が重なって二重に聞こえた（2026-11-25）。
  const audioNodeSigRef = useRef<Map<string, string>>(new Map());
  const audioClipSig = (c: SequenceClip, gain: number) =>
    `${c.asset_id}|${c.timeline_start}|${c.timeline_end}|${c.source_start}|${c.source_end}|${clipSpeed(c)}|${gain}`;
  useEffect(() => {
    const nodes = audioNodesRef.current;
    const sigs = audioNodeSigRef.current;
    if (!nodes.size) return;
    const now = new Map<string, string>();
    for (const { clip, gain } of audibleAudio) now.set(String(clip.id), audioClipSig(clip, gain));
    for (const [k, v] of [...nodes]) {
      const id = k.slice(0, k.lastIndexOf('|'));
      if (now.get(id) === sigs.get(k)) continue;
      if (v) { try { v.node.stop(); } catch { /* noop */ } try { v.gain.disconnect(); } catch { /* noop */ } }
      nodes.delete(k);
      sigs.delete(k);
    }
  }, [audibleAudio]);

  // 使っている素材だけ持つ
  useEffect(() => {
    const mgr = audioMgrRef.current;
    if (!mgr) return;
    const urls = new Set<string>();
    for (const { clip } of audibleAudio) { const u = srcByAssetId.get(String(clip.asset_id || '')); if (u) urls.add(u); }
    mgr.retain(urls);
    // 開いた時に全部の音の素材の目次（短い音は中身ごと）を読み始める: 再生がそこへ来てから読むと間に合わない
    for (const u of urls) mgr.get(u);
  }, [audibleAudio, srcByAssetId, useWebAudio]);

  // --- 素材をこのパソコンの保存場所へ取り込む（家の外から開いた時の、切れ目ごとの取りに行く待ちを無くす） ---
  // 先に要る順: 音だけの写し（小さい）→ 映像の写し。どちらも作品の頭から使われる順。
  const [localProg, setLocalProg] = useState<LocalMediaProgress | null>(null);
  const localUrlsKey = useMemo(() => {
    const first = new Map<string, number>();
    const note = (u: string | undefined, t: number) => { if (u && !(first.get(u)! <= t)) first.set(u, t); };
    for (const { clip } of audibleAudio) {
      const u = srcByAssetId.get(String(clip.asset_id || ''));
      if (u) note(useWebAudio ? (audioOnlyUrl(u) || u) : u, clip.timeline_start || 0);
    }
    const audio = [...first.entries()].sort((a, b) => a[1] - b[1]).map(([u]) => u);
    first.clear();
    for (const vc of visualClips) note(srcByAssetId.get(String(vc.clip.asset_id || '')), vc.clip.timeline_start || 0);
    const video = [...first.entries()].sort((a, b) => a[1] - b[1]).map(([u]) => u);
    return JSON.stringify([...audio, ...video]);
  }, [audibleAudio, visualClips, srcByAssetId, useWebAudio]);
  useEffect(() => {
    if (!localMediaEnabled()) return;
    const store = localMedia();
    const off = store.subscribe(setLocalProg);
    const t = window.setTimeout(() => { void store.ensure(JSON.parse(localUrlsKey) as string[]); }, 1500);
    return () => { window.clearTimeout(t); off(); };
  }, [localUrlsKey]);
  useEffect(() => () => { if (localMediaEnabled()) localMedia().stop(); }, []);
  // 家の中なら映像を Mac mini から直接読む（media-route.ts）。開いてすぐ確かめ始める
  useEffect(() => { startMediaRoute(); }, []);
  // 開いてすぐ（取り込みの途中）に位置を飛ばした: 飛んだ先の絵と音は Mac から読むので、その間は取り込みを休ませて
  // 回線を譲る。あわせて、飛んだ先の近くで使う素材を先に取り込む（2026-11-16 本人「開いてすぐいろんな秒数に飛ぶとかくつく」）。
  const seekSeenRef = useRef({ rev: seekRev, t: currentTime });
  useEffect(() => {
    const prev = seekSeenRef.current;
    seekSeenRef.current = { rev: seekRev, t: currentTime };
    // 体感の記録: 止まっている時に飛んだ → その位置の絵が出るまでを測る（editor-feel.ts）
    if (!playingRef.current && (seekRev !== prev.rev || Math.abs(currentTime - prev.t) > 0.05)) feelSeek(currentTime);
    if (!localMediaEnabled()) return;
    const jumped = seekRev !== prev.rev || (!playingRef.current && Math.abs(currentTime - prev.t) > 0.05);
    if (!jumped) return;
    const store = localMedia();
    if (!store.status().active) return;
    store.yieldToForeground();
    const from = currentTime - 1;
    const to = currentTime + 20;
    const near = new Map<string, number>();
    const note = (u: string | undefined, start: number, end: number) => {
      if (!u || end < from || start > to) return;
      const k = Math.max(start, currentTime);
      if (!(near.get(u)! <= k)) near.set(u, k);
    };
    for (const { clip } of audibleAudio) {
      const u = srcByAssetId.get(String(clip.asset_id || ''));
      note(u && useWebAudio ? (audioOnlyUrl(u) || u) : u, clip.timeline_start || 0, clip.timeline_end || 0);
    }
    for (const vc of visualClips) note(srcByAssetId.get(String(vc.clip.asset_id || '')), vc.clip.timeline_start || 0, vc.clip.timeline_end || 0);
    store.prioritize([...near.entries()].sort((a, b) => a[1] - b[1]).map(([u]) => u));
  }, [currentTime, seekRev, audibleAudio, visualClips, srcByAssetId, useWebAudio]);

  // 止まっている間も、再生位置の先の音を解読しておく（再生を押した瞬間から鳴る）
  const ensureAudioAhead = useCallback((t: number, aheadReal: number) => {
    const mgr = audioMgrRef.current;
    if (!mgr) return;
    const R = rateRef.current;
    const ahead = aheadReal * R;
    // 倍速の時は、すぐ鳴る区切りを1つずつ前もって縮めておく（鳴らす瞬間に縮めると、その分だけ画面が引っかかる）
    // クリップに速さが付いている時（1.08 など）も同じ（速さ＝再生の速さ×クリップの速さ）
    let warmed = false;
    for (const { clip: c } of audibleAudio) {
      if (warmed) break;
      if (c.timeline_end <= t) continue;
      if (c.timeline_start > t + 3 * R) break;
      const sp = clipSpeed(c);
      const Rc = R * sp;
      if (Rc === 1) continue;
      const src = mgr.get(srcByAssetId.get(String(c.asset_id || '')) || '');
      if (!src || src.mute) continue;
      const ss = Number(c.source_start || 0);
      const s0 = ss + Math.max(0, t - c.timeline_start) * sp;
      const s1 = Math.min(ss + (c.timeline_end - c.timeline_start) * sp, s0 + 3 * Rc);
      for (let b = Math.floor(s0 / STRETCH_BLOCK_SEC); b * STRETCH_BLOCK_SEC < s1; b += 1) {
        if (src.hasStretched(b, Rc)) continue;
        if (src.stretchedBlock(b, Rc)) warmed = true;
        break;
      }
    }
    for (const { clip: c } of audibleAudio) {
      if (c.timeline_end <= t) continue;
      if (c.timeline_start > t + ahead) break;
      const src = mgr.get(srcByAssetId.get(String(c.asset_id || '')) || '');
      if (!src) continue;
      const sp = clipSpeed(c);
      const ss = Number(c.source_start || 0);
      const from = ss + Math.max(0, t - c.timeline_start) * sp;
      const to = Math.min(ss + (c.timeline_end - c.timeline_start) * sp, from + ahead * sp);
      void src.ensure(from, to);
    }
  }, [audibleAudio, srcByAssetId]);
  useEffect(() => {
    if (playing) return;
    const id = window.setTimeout(() => ensureAudioAhead(currentTime || 0, 6), 150);
    return () => window.clearTimeout(id);
  }, [playing, currentTime, ensureAudioAhead]);

  // 再生中に毎コマ呼ぶ: これから LOOK 秒に始まる音を予約する。済んだ物はそのまま
  const scheduleAudio = useCallback((t: number, dtMs: number) => {
    const mgr = audioMgrRef.current;
    const anchor = audioAnchorRef.current;
    if (!mgr || !anchor) return false;
    const ctx = mgr.ctx;
    const R = anchor.rate || 1;
    const LOOK = 0.5 * R; // タイムラインの秒（実時間で0.5秒先まで）
    const stats = previewStats();
    const nodes = audioNodesRef.current;
    const sigs = audioNodeSigRef.current;
    let gap = false;
    for (const { clip: c, gain } of audibleAudio) {
      const ts = c.timeline_start, te = c.timeline_end;
      if (te <= t) continue;
      if (ts > t + LOOK) break;
      const src = mgr.get(srcByAssetId.get(String(c.asset_id || '')) || '');
      if (!src || gain <= 0) continue;
      const sig = audioClipSig(c, gain);
      // クリップの速さ sp: タイムラインの1秒＝素材の sp 秒。鳴らす速さは Rc = R × sp
      const sp = clipSpeed(c);
      const Rc = R * sp;
      const ss = Number(c.source_start || 0);
      const srcEnd = ss + (te - ts) * sp;
      const srcNow = ss + Math.max(0, t - ts) * sp;
      void src.ensure(srcNow, Math.min(srcEnd, srcNow + 8 * Rc));
      if (src.mute) continue;
      // 倍速の時は、4秒ずつ声の高さを保ったまま縮めた音を鳴らす（buffer の1秒 = 素材の Rc 秒）
      const BL = Rc !== 1 ? STRETCH_BLOCK_SEC : src.blockLen();
      const srcLook = ss + (Math.min(te, t + LOOK) - ts) * sp;
      for (let b = Math.floor(srcNow / BL); b * BL < srcLook; b += 1) {
        const key = `${c.id}|${b}`;
        if (nodes.has(key)) continue;
        let buf: AudioBuffer | null;
        let srcDur: number;
        if (Rc !== 1) {
          const st = src.stretchedBlock(b, Rc);
          buf = st ? st.buffer : null;
          srcDur = st ? st.srcDur : 0;
        } else {
          buf = src.blockBuffer(b);
          srcDur = buf ? buf.duration : 0;
        }
        if (!buf) { if (t >= ts && b === Math.floor(srcNow / BL)) gap = true; break; }
        const a = Math.max(b * BL, ss);
        const z = Math.min((b + 1) * BL, srcEnd, b * BL + srcDur);
        if (z <= a + 1e-4) { sigs.set(key, sig); nodes.set(key, null); continue; }
        const tl = ts + (a - ss) / sp;
        const nominal = anchor.ctxT0 + (tl - anchor.t0) / R;
        let when = nominal;
        let off = a - b * BL;   // 素材の秒
        let dur = z - a;        // 素材の秒
        const earliest = ctx.currentTime + 0.005;
        if (when < earliest) {
          const late = (earliest - when) * Rc;
          if (late >= dur) { sigs.set(key, sig); nodes.set(key, null); continue; }
          if (late > 0.04 && tl > anchor.t0 + 0.05) stats.audioLateStarts += 1;
          when = earliest; off += late; dur -= late;
        }
        const node = ctx.createBufferSource();
        node.buffer = buf;
        const g = ctx.createGain();
        g.gain.value = gain;
        node.connect(g);
        g.connect(mgr.master);
        node.start(when, off / Rc, dur / Rc);
        node.onended = () => { try { g.disconnect(); } catch { /* noop */ } };
        sigs.set(key, sig); nodes.set(key, { node, gain: g, t0: tl + (when - nominal) * R, t1: tl + (z - a) / sp });
        stats.audioScheduled += 1;
      }
    }
    if (gap) stats.audioGapMs += dtMs;
    // 終わった物は片付ける（同じクリップを2回鳴らさないための印は、再生を止めるまで残す）
    for (const [k, v] of nodes) if (v && v.t1 < t - 1) { v.gain.disconnect(); nodes.set(k, null); }
    return gap;
  }, [audibleAudio, srcByAssetId]);

  // この時刻から鳴らす音が、もう解読してあるか（鳴らす物が無い・壊れた素材は待たない）
  const audioReadyAt = useCallback((t: number): boolean => {
    const mgr = audioMgrRef.current;
    if (!mgr) return true;
    for (const { clip: c, gain } of audibleAudio) {
      if (c.timeline_end <= t) continue;
      if (c.timeline_start > t + 0.3) break;
      if (gain <= 0) continue;
      const src = mgr.get(srcByAssetId.get(String(c.asset_id || '')) || '');
      if (!src) continue;
      const sp = clipSpeed(c);
      const ss = Number(c.source_start || 0);
      const from = ss + Math.max(0, t - c.timeline_start) * sp;
      const to = Math.min(ss + (c.timeline_end - c.timeline_start) * sp - 0.01, from + 0.6 * sp);
      if (!src.hasAt(from) || !src.hasAt(Math.max(from, to))) return false;
    }
    return true;
  }, [audibleAudio, srcByAssetId]);

  // Resolve a clip's frame at time t. During playback we draw the hardware <video> element
  // (real-time, synced to audio); when paused/scrubbing we draw the WebCodecs cache (frame-
  // accurate). The <video> path falls through to WebCodecs while the element is still loading
  // (play-start transition) and for frozen clips (a single held frame is cheap to cache).
  const frameFor = useCallback(
    (clip: SequenceClip, t: number): { src: CanvasImageSource; vw: number; vh: number } | null => {
      const imageUrl = imageSrcByAssetId.get(String(clip.asset_id || ''));
      if (imageUrl) {
        const img = imageFor(imageUrl);
        return img ? { src: img, vw: img.naturalWidth, vh: img.naturalHeight } : null;
      }
      const url = srcByAssetId.get(String(clip.asset_id || ''));
      if (!url) return null;
      // Prefer the hardware <video> element when it's available AND already sitting on the
      // requested source time: that covers playback (the element tracks the clock) and the
      // play→pause handoff (the element is parked on the last frame), so neither flashes black
      // waiting for WebCodecs to re-decode. Once scrubbing moves the playhead away from where the
      // element is parked, the |currentTime - expected| check fails and we use WebCodecs, which
      // seeks frame-accurately. When WebCodecs is unavailable the element is the only source.
      if (!isFrozen(clip)) {
        const vel = videosRef.current.get(String(clip.id));
        if (vel && vel.readyState >= 2 && vel.videoWidth) {
          const expected = clipSourceTime(clip, t);
          // 再生中でも、頭出し中や時刻が離れた要素の絵は使わない（古い絵のまま時計だけ進むのを防ぐ）
          const near = Math.abs(vel.currentTime - expected) < (playingRef.current ? 0.15 : 0.12);
          if (!supported || (near && !(playingRef.current && vel.seeking && gateRef.current))) {
            return joinAlpha(clip, { src: vel, vw: vel.videoWidth, vh: vel.videoHeight });
          }
        }
      }
      const fs = framesRef.current.get(url);
      if (!fs) return null;
      // Clip's source bounds: the fallback frame must stay within these (cut-frame guard). For a
      // frozen clip the bound is the single held source frame.
      const ss = Number(clip.source_start || 0);
      const frozen = isFrozen(clip);
      const lo = ss;
      const hi = frozen ? ss : Number(clip.source_end ?? ss);
      // 鍵のコマだけ拾う早送りでは、少し前の鍵のコマを出してよい（素材の1.5秒＝10倍で実時間0.15秒）
      const frame = fs.peek(clipSourceTime(clip, t), lo, hi, skimKeysRef.current && playingRef.current ? 1.5 : 0.18);
      if (!frame) return null;
      return joinAlpha(clip, { src: frame, vw: frame.width || fs.width, vh: frame.height || fs.height });
    },
    [srcByAssetId, imageSrcByAssetId, imageFor, supported],
  );

  // この段の絵は待てば出てくるか（読み込み中・解読待ち）。壊れた素材や、素材の長さの外は待たない
  // （待つと、その場所で絵がずっと止まってしまう）。
  const willProvide = useCallback(
    (clip: SequenceClip, t: number): boolean => {
      const imageUrl = imageSrcByAssetId.get(String(clip.asset_id || ''));
      if (imageUrl) {
        const img = imagesRef.current.get(imageUrl);
        return !img || !(img.complete && img.naturalWidth === 0); // 読み込み中は待つ、壊れた絵は待たない
      }
      const url = srcByAssetId.get(String(clip.asset_id || ''));
      if (!url) return false;
      const fs = framesRef.current.get(url);
      if (!fs) return false;
      if (!supported) return true;
      return fs.canProvide(clipSourceTime(clip, t));
    },
    [srcByAssetId, imageSrcByAssetId, supported],
  );

  // 今の時刻の映像が、本当にその時刻の絵で出せるか。
  // start: 再生を始める前。映像の要素がその位置で止まって、先の絵まで読み込めている（押せばすぐ流れる）。
  // run: 再生中。映っている絵が時計と0.15秒以内（要素）か、ほぼその時刻の解読済みの絵。
  const visualReadyAt = useCallback(
    (t: number, mode: 'start' | 'run', patient = false): boolean => {
      const active = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      let from = 0;
      for (let i = active.length - 1; i >= 0; i -= 1) if (coversFrame(active[i], imageSrcByAssetId)) { from = i; break; }
      for (const vc of active.slice(from)) {
        const clip = vc.clip;
        const imageUrl = imageSrcByAssetId.get(String(clip.asset_id || ''));
        if (imageUrl) {
          const img = imagesRef.current.get(imageUrl);
          if (img && img.complete) continue;   // 出ている（壊れた絵は待たない）
          return false;
        }
        const url = srcByAssetId.get(String(clip.asset_id || ''));
        if (!url) continue;
        const fs = framesRef.current.get(url);
        const expected = clipSourceTime(clip, t);
        if (!isFrozen(clip)) {
          const v = videosRef.current.get(String(clip.id));
          if (v && v.error) continue;          // 壊れた素材は待たない
          if (v && v.readyState >= 2 && v.videoWidth && !v.seeking) {
            const d = Math.abs(v.currentTime - expected);
            // 止まった要素は先の絵を読まないことがある（readyState 2 のまま）。少し待っても3にならなければ始める
            if (mode === 'start' ? d < 0.05 && (v.readyState >= 3 || patient) : d < 0.15) continue;
          }
          if (mode === 'start' && v && supported) return false; // 要素がその位置で流れ出せるまで待つ
        }
        if (!fs || !supported) { if (!supported) return false; continue; }
        if (!fs.canProvide(expected)) continue;  // 素材の外・壊れた素材
        const ss = Number(clip.source_start || 0);
        const frozen = isFrozen(clip);
        const skim = mode === 'run' && skimKeysRef.current;
        const got = fs.peek(expected, ss, frozen ? ss : Number(clip.source_end ?? ss), skim ? 1.5 : 0.18);
        if (got && Math.abs(fs.lastShownTime - expected) < (skim ? 1.5 : 0.07)) continue;
        return false;
      }
      return true;
    },
    [visualClips, imageSrcByAssetId, srcByAssetId, supported],
  );

  const drawFrame = useCallback(
    (t: number): boolean => {
      const canvas = canvasRef.current;
      if (!canvas) return false;
      const ctx = canvas.getContext('2d');
      if (!ctx) return false;
      const { w, h } = dims;
      const ps = pxScaleRef.current;

      const active = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      // 上から見て、画面を全部ふさぐ一番上の映像より下は描かない（見えないので）。
      // そこから上の段は全部そろうまで絵を変えない: 上の段の絵がまだ届いていない一瞬に下の段だけで描くと、
      // 「上に映像があるのに下の映像が一瞬見える」になる（2026-11-13 本人）。編集ソフトと同じく前の絵のまま待つ。
      let from = 0;
      if (fixLayers) {
        for (let i = active.length - 1; i >= 0; i -= 1) {
          if (coversFrame(active[i], imageSrcByAssetId)) { from = i; break; }
        }
      }
      const needed = active.slice(from);
      const layers: Array<{ vc: VisualClip; got: { src: CanvasImageSource; vw: number; vh: number } }> = [];
      let pending = 0;
      for (const vc of needed) {
        const got = frameFor(vc.clip, t);
        if (got) layers.push({ vc, got });
        else if (willProvide(vc.clip, t)) pending += 1;
      }
      const stats = previewStats();
      let hold: boolean;
      if (fixLayers) {
        hold = pending > 0;
      } else {
        // 前の決め方（比べる時だけ ?previewfix=0）: 下の段の映像さえ出れば描いていた
        const hasBase = active.some((vc) => vc.kind === 'base');
        const baseReady = layers.some((l) => l.vc.kind === 'base');
        hold = active.length > 0 && ((hasBase && !baseReady) || (!hasBase && layers.length === 0));
      }
      if (hold) {
        stats.holds += 1;
        if (showDiag && diagRef.current) {
          const baseClip = active.find((vc) => vc.kind === 'base') || active[0];
          const url = baseClip ? srcByAssetId.get(String(baseClip.clip.asset_id || '')) : null;
          const fs = url ? framesRef.current.get(url) : null;
          diagRef.current.textContent = `t=${t.toFixed(2)}  HOLD  want-src=${baseClip ? clipSourceTime(baseClip.clip, t).toFixed(2) : '-'}  wc[${fs ? fs.status() : 'none'}]`;
        }
        return false; // keep the last good frame on screen
      }
      stats.draws += 1;
      feelDrawn(t);
      // 確かめ用: 画面をふさぐ一番上の映像より上に、描けなかった段があったか（あれば下が透けて見えた）
      {
        let top = 0;
        for (let i = active.length - 1; i >= 0; i -= 1) if (coversFrame(active[i], imageSrcByAssetId)) { top = i; break; }
        const drawn = new Set(layers.map((l) => l.vc));
        const missing = active.slice(top).filter((vc) => !drawn.has(vc) && willProvide(vc.clip, t));
        if (missing.length) { stats.wrongDraws += 1; stats.lastWrong = t; }
      }

      const baseCtx = ctx;
      baseCtx.setTransform(ps, 0, 0, ps, 0, 0);
      baseCtx.imageSmoothingEnabled = true;
      baseCtx.imageSmoothingQuality = 'high';
      baseCtx.fillStyle = '#000';
      baseCtx.fillRect(0, 0, w, h);
      // テロップ・場面より上の段の絵は、その上の canvas に描く（段の上下 = 前後）
      const { canvasOf } = stackRef.current;
      const upperCtx: Array<CanvasRenderingContext2D | null> = [];
      const usedUpper = new Set<number>();
      for (const l of layers) { const ci = canvasOf.get(String(l.vc.clip.id)) || 0; if (ci > 0) usedUpper.add(ci); }
      upperCanvasRefs.current.forEach((cv, ci) => {
        if (!cv || ci === 0) return;
        if (!usedUpper.has(ci) && !upperDirty.current[ci]) return;
        const c2 = cv.getContext('2d');
        if (!c2) return;
        c2.setTransform(ps, 0, 0, ps, 0, 0);
        c2.clearRect(0, 0, w, h);
        c2.imageSmoothingEnabled = true;
        c2.imageSmoothingQuality = 'high';
        upperCtx[ci] = c2;
        upperDirty.current[ci] = usedUpper.has(ci);
      });

      // 範囲の効果（モザイク・ぼかし・枠…）は、その段より下に描いた絵を加工する（書き出しと同じ順番）。
      // 描く先は、効果のすぐ下の絵が乗った canvas。
      const fxNow = regionFx.filter((f) => t >= Number(f.clip.timeline_start || 0) && t < Number(f.clip.timeline_end || 0));
      let fxDone = 0;
      let fxCtx: CanvasRenderingContext2D = baseCtx;
      const applyFxBelow = (layer: number) => {
        while (fxDone < fxNow.length && fxNow[fxDone].layer < layer) {
          drawRegionEffect(fxCtx, fxNow[fxDone].clip, t, w, h);
          fxDone += 1;
        }
      };
      for (const { vc, got } of layers) {
        applyFxBelow(vc.layer);
        const ci = canvasOf.get(String(vc.clip.id)) || 0;
        const ctx = (ci > 0 && upperCtx[ci]) || baseCtx;
        fxCtx = ctx;
        // colour grade: the same matrix the export applies (clip.grade)
        ctx.filter = gradeFilter((vc.clip as { grade?: unknown }).grade);
        // blend mode (light leaks etc. on black): the export mixes the same way (clip.blend)
        ctx.globalCompositeOperation = BLEND_OPS[String((vc.clip as { blend?: string }).blend || '')] || 'source-over';
        // 不透明度 (the export mixes the same: an overlay's alpha, a bottom-lane picture over black)
        ctx.globalAlpha = vc.clip.opacity != null ? Math.max(0, Math.min(1, Number(vc.clip.opacity))) : 1;
        const shape = (vc.clip as { shape?: string }).shape;
        if (isOneForm(vc.clip)) {
          // the one form (サイズ・左右・上下・キーフレーム): the picture rect at this time, the crop
          // mask on it, the cut on what shows — the export draws the same (clip_placement.render_fields)
          const P = pictureRect(vc.clip, motionAt(vc.clip, t - vc.clip.timeline_start), got.vw, got.vh, w, h);
          if (shape === 'circle' || shape === 'rounded') {
            const V = visibleRect(vc.clip, P);
            ctx.save();
            ctx.beginPath();
            if (shape === 'circle') ctx.ellipse(V.x + V.w / 2, V.y + V.h / 2, V.w / 2, V.h / 2, 0, 0, Math.PI * 2);
            else ctx.roundRect(V.x, V.y, V.w, V.h, Math.min(V.w, V.h) * 0.12);
            ctx.clip();
            drawSource(ctx, got.src, got.vw, got.vh, P.x, P.y, P.w, P.h, null, w, h, cropOf(vc.clip));
            ctx.restore();
          } else {
            drawSource(ctx, got.src, got.vw, got.vh, P.x, P.y, P.w, P.h, null, w, h, cropOf(vc.clip));
          }
          continue;
        }
        const tf = vc.clip.transform;
        const cr = vc.clip.crop;
        let px = vc.position ? vc.position.x * w : 0;
        let py = vc.position ? vc.position.y * h : 0;
        let pw = vc.position ? vc.position.width * w : w;
        let ph = vc.position ? vc.position.height * h : h;
        // Motion (transform_keys): the clip's box moves/scales over time, relative to its box.
        const k = boxKeyAt(vc.clip.transform_keys, t - vc.clip.timeline_start);
        if (k) { px += k.x * pw; py += k.y * ph; pw *= k.w; ph *= k.h; }
        // Wipe shape (circle / rounded "photo") clips ANY video clip to that box.
        if (shape === 'circle' || shape === 'rounded') {
          ctx.save();
          ctx.beginPath();
          if (shape === 'circle') ctx.ellipse(px + pw / 2, py + ph / 2, pw / 2, ph / 2, 0, 0, Math.PI * 2);
          else ctx.roundRect(px, py, pw, ph, Math.min(pw, ph) * 0.12);
          ctx.clip();
          drawSource(ctx, got.src, got.vw, got.vh, px, py, pw, ph, tf, w, h, cr);
          ctx.restore();
        } else {
          drawSource(ctx, got.src, got.vw, got.vh, px, py, pw, ph, tf, w, h, cr);
        }
      }

      for (const c2 of [ctx, ...upperCtx]) {
        if (!c2) continue;
        c2.filter = 'none';
        c2.globalCompositeOperation = 'source-over';
        c2.globalAlpha = 1;
      }
      applyFxBelow(Number.POSITIVE_INFINITY);
      // 再生中に絵を使わなかった映像の要素（上の映像にふさがれた段など）も、1画素だけ描いて絵を受け取り続ける。
      // ブラウザは誰も絵を受け取らない映像の要素を0.25秒おきにしか進めず、その要素だけ再生が遅れて、
      // ふさいでいた映像が終わって見えた瞬間にずれていた（音を時計にした時に、映像が平均0.1秒以上遅れていた）。
      if (playingRef.current) {
        const drawnSrc = new Set(layers.map((l) => l.got.src));
        for (const vc of active) {
          const vel = videosRef.current.get(String(vc.clip.id));
          if (!vel || vel.paused || vel.readyState < 2 || drawnSrc.has(vel)) continue;
          const pump = pumpCtx();
          if (pump) { try { pump.drawImage(vel, 0, 0, 1, 1); } catch { /* not ready */ } }
        }
      }

      const baseGot = (layers.find((l) => l.vc.kind === 'base') || layers[0])?.got || null;

      // Manual blur boxes, resolved at THIS frame's time t (not a lagging prop).
      for (const r of (blurRegionsAt ? blurRegionsAt(t) : [])) {
        if (!baseGot) break;
        const rx = r.x * w;
        const ry = r.y * h;
        const rw = Math.max(2, r.width * w);
        const rh = Math.max(2, r.height * h);
        ctx.save();
        ctx.beginPath();
        ctx.rect(rx, ry, rw, rh);
        ctx.clip();
        ctx.filter = `blur(${14 * ps}px)`;
        drawCover(ctx, baseGot.src, baseGot.vw, baseGot.vh, 0, 0, w, h);
        ctx.restore();
      }
      // Captions render as an HTML <CaptionLayer> overlay (below), not on the canvas.
      if (showDiag && diagRef.current) {
        const baseLayer = layers.find((l) => l.vc.kind === 'base') || layers[0];
        const wantSrc = baseLayer ? clipSourceTime(baseLayer.vc.clip, t).toFixed(2) : '—';
        const usingVideoEl = baseLayer && (baseLayer.got.src as HTMLVideoElement).tagName === 'VIDEO';
        const url = baseLayer ? srcByAssetId.get(String(baseLayer.vc.clip.asset_id || '')) : null;
        const fs = !usingVideoEl && url ? framesRef.current.get(url) : null;
        diagRef.current.textContent = `t=${t.toFixed(2)}  LIVE  want=${wantSrc}  via=${usingVideoEl ? 'video' : 'webcodecs'}${fs ? ` [${fs.status()}]` : ''}  ${playingRef.current ? 'PLAY' : 'PAUSE'}`;
      }
      return true;
    },
    [dims, visualClips, regionFx, blurRegionsAt, frameFor, willProvide, fixLayers, imageSrcByAssetId, showDiag],
  );

  // SCRUB: when not playing, paint the exact frame for currentTime. With WebCodecs we decode it
  // frame-accurately (no <video> seek latency); without it we seek the <video> elements instead.
  useEffect(() => {
    if (playing) return;
    let cancelled = false;
    const active = visualClips.filter((vc) => currentTime >= vc.clip.timeline_start && currentTime < vc.clip.timeline_end);
    drawFrame(currentTime); // paint best-available immediately (previous frame, no black flash)
    // PARK: once the head settles, seek the paused playback elements (muted video + audio) to the
    // head too, so pressing Play just resumes them instead of starting a fresh seek (that seek was
    // the ~0.3s local / ~1s+ remote delay before sound and picture moved, 2026-11-12).
    const park = window.setTimeout(() => {
      if (cancelled) return;
      for (const vc of active) {
        if (isFrozen(vc.clip)) continue;
        const v = videosRef.current.get(String(vc.clip.id));
        const want = clipSourceTime(vc.clip, currentTime);
        if (v && v.paused && Math.abs(v.currentTime - want) > 0.04) { try { v.currentTime = want; } catch { /* not ready */ } }
      }
      for (const c of audioClips) {
        if (!(currentTime >= c.timeline_start && currentTime < c.timeline_end)) continue;
        const a = audiosRef.current.get(String(c.id));
        const want = Number(c.source_start || 0) + (currentTime - c.timeline_start) * clipSpeed(c);
        if (a && a.paused && Math.abs(a.currentTime - want) > 0.04) { try { a.currentTime = want; } catch { /* not ready */ } }
      }
    }, 120);
    if (supported) {
      // 見えない（上の映像にふさがれた）段は解読しない: その分だけ早く絵が出る
      let from = 0;
      if (fixLayers) for (let i = active.length - 1; i >= 0; i -= 1) if (coversFrame(active[i], imageSrcByAssetId)) { from = i; break; }
      const seeks = active.slice(from).map((vc) => {
        const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
        if (!url) return Promise.resolve();
        const fs = framesRef.current.get(url);
        if (!fs) return Promise.resolve();
        return fs.ready.then(() => fs.seekTo(clipSourceTime(vc.clip, currentTime)));
      });
      void Promise.all(seeks).then(() => { if (!cancelled) drawFrame(currentTime); });
      return () => { cancelled = true; window.clearTimeout(park); };
    }
    // Fallback (no WebCodecs): seek the muted <video> elements and redraw once they land.
    for (const vc of active) {
      if (isFrozen(vc.clip)) continue;
      const v = videosRef.current.get(String(vc.clip.id));
      if (v) { if (!v.paused) v.pause(); try { v.currentTime = clipSourceTime(vc.clip, currentTime); } catch { /* not ready */ } }
    }
    const timer = window.setTimeout(() => { if (!cancelled) drawFrame(currentTime); }, 140);
    return () => { cancelled = true; window.clearTimeout(timer); window.clearTimeout(park); };
  }, [currentTime, playing, supported, visualClips, audioClips, drawFrame, srcByAssetId, readyTick, pxScale, fixLayers, imageSrcByAssetId]);

  // PLAYBACK: a wall-clock timeline drives muted VIDEO <video> elements and unmuted AUDIO <video>
  // elements, all playing in real time at rate 1, each seeked to its source offset when its clip
  // becomes active (and re-synced only on large drift). Because video and audio are BOTH hardware
  // <video> elements on the same clock, they stay in sync without per-frame correction — this is
  // the proven native-NLE playback path. drawFrame() composites the video elements onto the canvas.
  useEffect(() => {
    if (!playing) {
      runningRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      playClockRef.current = null;
      prevActiveAudioRef.current = new Set();
      prevActiveVideoRef.current = new Set();
      for (const [, v] of videosRef.current) { v.pause(); v.defaultPlaybackRate = 1; v.playbackRate = 1; }
      for (const [, a] of audiosRef.current) a.pause();
      stopAudioNodes();
      audioAnchorRef.current = null;
      return;
    }
    if (!playClockRef.current) playClockRef.current = { wall: performance.now(), t: currentTime };
    const R = rateRef.current; // 速さが変わるとこの輪は作り直される（deps の rate）
    const skimKeys = R >= SKIM_KEYS_RATE;
    skimKeysRef.current = skimKeys;
    // 音を Web Audio で鳴らす時は、その時計を再生の時計にする（聞こえている時刻＝映っている時刻）。
    // ここに来るのは再生を始めた時と、再生中に段の中身が変わった時。どちらも今の時刻から予約し直す。
    const mgr = audioMgrRef.current;
    const webAudio = !!mgr;
    previewStats().audioMode = webAudio ? 'webaudio' : 'element';
    stopAudioNodes();
    audioAnchorRef.current = null;
    if (mgr && mgr.ctx.state !== 'running') void mgr.ctx.resume().catch(() => {});
    const anchorNow = (t: number) => {
      if (!mgr || mgr.ctx.state !== 'running') return;
      audioAnchorRef.current = { ctxT0: mgr.ctx.currentTime + 0.04, t0: t, rate: R };
    };
    {
      const c = playClockRef.current;
      anchorNow(c.t + (R * (performance.now() - c.wall)) / 1000);
    }
    const heardTime = (): number | null => {
      const an = audioAnchorRef.current;
      if (!mgr || !an) return null;
      const ctx = mgr.ctx;
      let now = ctx.currentTime - (ctx.outputLatency || ctx.baseLatency || 0);
      const ot = typeof ctx.getOutputTimestamp === 'function' ? ctx.getOutputTimestamp() : null;
      // 出口の時刻が古い（音の仕組みが止められていた・裏から戻った直後）時は使わない。古い時刻に
      // 経った時間を足すと、聞こえている所より何秒も先を指してしまう
      if (ot && ot.contextTime && ot.performanceTime && performance.now() - ot.performanceTime < 500) now = ot.contextTime + (performance.now() - ot.performanceTime) / 1000;
      return an.t0 + an.rate * Math.max(0, now - an.ctxT0);
    };
    let lastWall = performance.now();
    let lastT = playClockRef.current.t; // 最後に映した時刻（裏へ行って戻った時はここから続ける）
    let lastAheadWall = 0;
    // 上の段が画面を全部ふさいでいる間、その下の段の映像は再生しない（2026-11-15 本人「まともに再生できん
    // くらい重い」: X固定ポストの冒頭は1920×1080の動画が5段重なり、見えない4本まで同時に解読していた）。
    // ふさいでいる段が HIDE_MARGIN 秒以内に終わる時は、その下を前もって走らせておく（終わった瞬間に絵が出るように）。
    const HIDE_MARGIN = 1.0;
    // ふさいでいるのがいつまで続くか: 同じ高さ以上の、画面をふさぐ次のクリップが切れ目なく続く分も足す
    // （冒頭の段7のように場面ごとに切ったクリップが並んでいる時、切れ目ごとに下の段を走らせない）
    const coveredUntil = (vc: VisualClip): number => {
      let end = vc.clip.timeline_end;
      for (let guard = 0; guard < 50; guard += 1) {
        const next = visualClips.find((o) => o.layer >= vc.layer && o.clip.timeline_start <= end + 0.02 && o.clip.timeline_end > end + 0.02 && coversFrame(o, imageSrcByAssetId));
        if (!next) break;
        end = next.clip.timeline_end;
      }
      return end;
    };
    const visibleFrom = (active: VisualClip[], t: number): number => {
      if (!fixLayers) return 0;
      for (let i = active.length - 1; i >= 0; i -= 1) {
        if (coversFrame(active[i], imageSrcByAssetId) && coveredUntil(active[i]) - t > HIDE_MARGIN * R) return i;
      }
      return 0;
    };
    // 映像の要素ごとの再生の速さ（再生の速さ × クリップの速さ）
    const speedById = new Map(visualClips.map((vc) => [String(vc.clip.id), clipSpeed(vc.clip)]));
    // 映像の要素の速さは16倍までしか付けられない（それより上は Chrome が例外を投げる）
    const rateOf = (id: string) => Math.min(16, R * (speedById.get(id) ?? 1));
    const PREROLL = 1.5; // pre-seek a clip about to start so its first frame is ready at the cut
    const LEAD = 0.4;    // 映像の要素を境目より前から走らせておく長さ
    // 映像と音がそろって流れ出せるまで、再生ヘッド・音・映像を全部止めて待つ（2026-11-13 本人
    // 「再生ヘッドと音声だけ走って映像が止まっているより、揃って一斉に流れ出すことが大事」）。
    // prep = 止めて準備中、run = 流れている。流れている途中で映像か音が0.15秒追いつかなければ prep に戻る。
    const gate = gateRef.current;
    // 再生中に段の中身が変わってここへ来た時（流れている最中）は、止めずにそのまま続ける
    const resumeRunning = runningRef.current;
    let phase: 'prep' | 'run' = gate && !resumeRunning ? 'prep' : 'run';
    let visOkAt = 0;
    let audOkAt = 0;
    let prepSince = performance.now();
    let badSince = 0;
    if (phase === 'prep') {
      stopAudioNodes();
      audioAnchorRef.current = null;
      for (const [, v] of videosRef.current) if (!v.paused) v.pause();
    }
    prepRequestRef.current = false;
    const enterPrep = (t: number, stall: boolean) => {
      phase = 'prep';
      runningRef.current = false;
      visOkAt = 0;
      audOkAt = 0;
      prepSince = performance.now();
      badSince = 0;
      stopAudioNodes();
      audioAnchorRef.current = null;
      for (const [id, v] of videosRef.current) { if (!v.paused) v.pause(); if (v.playbackRate !== rateOf(id)) v.playbackRate = rateOf(id); }
      prevActiveVideoRef.current = new Set();
      prevActiveAudioRef.current = new Set();
      const c = playClockRef.current;
      if (c) { c.t = t; c.wall = performance.now(); }
      if (stall) { const st = previewStats(); st.stalls = (st.stalls || 0) + 1; feelStall(); }
    };
    const prepStep = (clock: { wall: number; t: number }, nowWall: number) => {
      const t = clock.t;
      clock.wall = nowWall; // 準備中は時計を進めない（字幕・場面の層も止まったまま）
      const allActive = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      const active = allActive.slice(visibleFrom(allActive, t));
      for (const vc of active) {
        const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
        const fs = url ? framesRef.current.get(url) : null;
        const expected = clipSourceTime(vc.clip, t);
        if (fs) void fs.ready.then(() => fs.seekTo(expected));
        if (isFrozen(vc.clip)) continue;
        const v = videosRef.current.get(String(vc.clip.id));
        if (!v) continue;
        if (!v.paused) v.pause();
        if (!v.seeking && Math.abs(v.currentTime - expected) > 0.04) { try { v.currentTime = expected; } catch { /* not ready */ } }
      }
      if (webAudio && nowWall - lastAheadWall > 250) { lastAheadWall = nowWall; ensureAudioAhead(t, 6); }
      drawFrame(t);
      const audioOk = !webAudio || audioReadyAt(t);
      const ctxOk = !webAudio || !mgr || mgr.ctx.state === 'running' || nowWall - prepSince > 400;
      const visOk = visualReadyAt(t, 'start', nowWall - prepSince > 300);
      if (visOk && !visOkAt) visOkAt = nowWall;
      if (audioOk && !audOkAt) audOkAt = nowWall;
      const ready = (visOk && audioOk && ctxOk) || nowWall - prepSince > 6000;
      if (!ready) return;
      if (showDiag) {
        const st0 = previewStats() as unknown as { startDetail?: number[][] };
        (st0.startDetail ||= []).push([Math.round((visOkAt || nowWall) - prepSince), Math.round((audOkAt || nowWall) - prepSince)]);
      }
      // そろった: 映像の要素・音・時計を同じ瞬間に流し始める
      const st = previewStats();
      (st.startWaits ||= []).push(Math.round(nowWall - prepSince));
      feelStart(nowWall - prepSince);
      if (st.startWaits.length > 50) st.startWaits.splice(0, 10);
      for (const vc of active) {
        if (isFrozen(vc.clip)) continue;
        const v = videosRef.current.get(String(vc.clip.id));
        if (v) { const rv = rateOf(String(vc.clip.id)); if (v.playbackRate !== rv) v.playbackRate = rv; void v.play().catch(() => {}); }
      }
      if (mgr && mgr.ctx.state === 'running') audioAnchorRef.current = { ctxT0: mgr.ctx.currentTime + 0.05, t0: t, rate: R };
      clock.t = t;
      clock.wall = performance.now() + 50; // 音の時計が無い時も、音と同じく0.05秒後から進める
      phase = 'run';
      runningRef.current = true;
      badSince = 0;
    };
    const step = () => {
      const clock = playClockRef.current;
      if (!clock) return;
      // Provisional time from the wall clock; refined below to the MASTER video element's actual
      // position so the playhead and the displayed frame are the same quantity (zero drift).
      const nowWall = performance.now();
      const dtMs = nowWall - lastWall;
      lastWall = nowWall;
      if (prepRequestRef.current) {
        prepRequestRef.current = false;
        if (gate) enterPrep(clock.t, false);
      }
      // 画面の描き直しが1秒以上止まっていた（別のアプリ・別の画面へ行って戻った）: 音の予約・映像の要素・
      // 時計がそれぞれ勝手に進んでいて、そのまま続けると同じ所が二重に流れた（2026-11-19 本人「別の画面や
      // 別のアプリに行ってから戻ると同じ場所が2回再生されながら進む」）。離れた所から全部そろえ直す。
      if (phase === 'run' && dtMs > 1000) {
        enterPrep(lastT, false);
        prepStep(clock, nowWall);
        rafRef.current = requestAnimationFrame(step);
        return;
      }
      if (phase === 'prep') {
        prepStep(clock, nowWall);
        rafRef.current = requestAnimationFrame(step);
        return;
      }
      if (webAudio && !audioAnchorRef.current && mgr && mgr.ctx.state === 'running') anchorNow(clock.t + (R * Math.max(0, nowWall - clock.wall)) / 1000);
      const heard = heardTime();
      let t = heard != null ? heard : clock.t + (R * Math.max(0, nowWall - clock.wall)) / 1000;
      if (t >= sequenceDuration) {
        for (const [, v] of videosRef.current) v.pause();
        for (const [, a] of audiosRef.current) a.pause();
        onEnded();
        drawFrame(sequenceDuration);
        onTimeChange(sequenceDuration);
        return;
      }

      // VIDEO: align + play each active clip's muted element (frozen clips draw from WebCodecs,
      // so just make sure their single frame is decoded).
      const allActive = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      const active = allActive.slice(visibleFrom(allActive, t));
      const activeVids = new Set<string>();
      for (const vc of active) {
        const id = String(vc.clip.id);
        if (isFrozen(vc.clip)) {
          const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
          const fs = url ? framesRef.current.get(url) : null;
          if (fs) void fs.ready.then(() => fs.seekTo(Number(vc.clip.source_start || 0)));
          continue;
        }
        if (skimKeys) {
          // 鍵のコマだけ拾う: 要素は止め、今の時刻の手前の鍵のコマを解読させる（同じコマは1回だけ）
          const ve = videosRef.current.get(id);
          if (ve && !ve.paused) ve.pause();
          const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
          const fs = url ? framesRef.current.get(url) : null;
          if (fs) { const kt = fs.keyTimeAt(clipSourceTime(vc.clip, t)); if (kt >= 0) void fs.seekTo(kt); }
          continue;
        }
        const v = videosRef.current.get(id);
        if (!v) continue;
        activeVids.add(id);
        const Rv = rateOf(id);
        const expected = clipSourceTime(vc.clip, t);
        // Seek on activation or on big drift only; re-seeking a playing element every frame is
        // what made audio warble in the old code. Video re-seeks aren't audible.
        // An element already parked on this spot (scrub PARK / pre-roll) is not re-seeked.
        const signed = v.currentTime - expected;
        const drift = Math.abs(signed);
        if (prevActiveVideoRef.current.has(id) && !v.seeking && vc.kind === 'base') {
          const st = previewStats();
          st.avN = (st.avN || 0) + 1; st.avSum = (st.avSum || 0) + drift; st.avMax = Math.max(st.avMax || 0, drift);
          if (drift > 0.045) st.avOver = (st.avOver || 0) + 1; // 1コマ半より大きいずれ
          if (showDiag) { const tr = ((st as unknown as { avTrace?: number[][] }).avTrace ||= []); tr.push([Number(t.toFixed(3)), Number(signed.toFixed(3)), v.playbackRate, Number(vc.clip.timeline_start.toFixed(2)), String(vc.clip.asset_id || '').slice(0, 8), Number(v.currentTime.toFixed(3)), Number(expected.toFixed(3)), v.readyState, v.paused ? 1 : 0] as unknown as number[]); if (tr.length > 3000) tr.splice(0, 1000); }
        }
        if (heard != null) {
          // 音の時計に映像を合わせる: 大きくずれた時だけ頭出し、小さいずれは再生の速さを少し変えて詰める
          // 再生中の要素を頭出しすると、その間（0.2〜0.3秒）止まって、かえってずれが広がる（頭出し→止まる→
          // また頭出し、を繰り返していた）。大きく外れた時だけ頭出しし、ふだんは速さを段で変えて追いつかせる。
          // 毎コマ細かく速さを変えると、ブラウザが再生を引っかける。
          const want = Math.min(16, Rv * (signed < -0.06 ? 1.25 : signed < -0.02 ? 1.06 : signed > 0.06 ? 0.8 : signed > 0.02 ? 0.94 : drift < 0.008 ? 1 : v.playbackRate / Rv));
          if ((!prevActiveVideoRef.current.has(id) && (v.paused ? drift > 0.04 : drift > 0.25 * Rv)) || drift > 0.7 * Rv) {
            try { v.currentTime = expected; } catch { /* not ready */ }
            if (v.playbackRate !== Rv) v.playbackRate = Rv;
          } else if (v.playbackRate !== want) {
            v.playbackRate = want;
          }
        } else if ((!prevActiveVideoRef.current.has(id) && drift > 0.04) || drift > 0.15 * Rv) {
          try { v.currentTime = expected; } catch { /* not ready */ }
          if (v.playbackRate !== Rv) v.playbackRate = Rv;
        }
        if (v.paused) { if (heard == null && v.playbackRate !== Rv) v.playbackRate = Rv; void v.play().catch(() => {}); }
      }
      for (const [id, v] of videosRef.current) {
        if (activeVids.has(id) || v.paused) continue;
        // 境目の前から走らせている要素は止めない
        const vc = visualClips.find((x) => String(x.clip.id) === id);
        if (vc && vc.clip.timeline_start > t && vc.clip.timeline_start - t <= LEAD * R + 0.1) continue;
        v.pause();
      }

      // MASTER CLOCK: drive the timeline time from the actual position of the displayed base
      // <video> element. The playhead and the on-screen frame are then the SAME number, so they
      // can't diverge (the old wall clock let the element drift up to 0.15s behind the playhead).
      // At a cut/gap the active base element isn't playing yet → keep the wall clock (mirrored),
      // and drawFrame paints the frame-accurate WebCodecs frame for `t` until the element syncs.
      let masterT: number | null = null;
      if (heard == null) for (const vc of active) {
        if (vc.kind !== 'base' || isFrozen(vc.clip)) continue;
        const v = videosRef.current.get(String(vc.clip.id));
        if (v && v.readyState >= 2 && v.videoWidth && !v.paused) {
          masterT = Number(vc.clip.timeline_start) + (v.currentTime - Number(vc.clip.source_start || 0)) / clipSpeed(vc.clip);
          break;
        }
      }
      if (masterT != null && Number.isFinite(masterT) && masterT >= 0 && masterT < sequenceDuration) t = masterT;
      lastT = t;
      clock.t = t;                     // mirror so the wall clock continues smoothly from the
      clock.wall = performance.now();  // master when the master drops out at a cut/gap

      // PRE-ROLL: pre-seek a clip about to become active so its frame is ready at the join — both
      // its <video> element AND a WebCodecs frame as a safety net (if the element is still seeking
      // at the cut, drawFrame falls back to the decoded frame instead of flashing black).
      for (const vc of visualClips) {
        const id = String(vc.clip.id);
        if (activeVids.has(id) || isFrozen(vc.clip)) continue;
        if (!(vc.clip.timeline_start > t && vc.clip.timeline_start <= t + PREROLL * R)) continue;
        if (skimKeys) {
          // 鍵のコマだけ拾う早送り: 要素は走らせず、始まりの鍵のコマだけ先に解読しておく
          if (vc.clip.timeline_start > t + 0.5 * R) continue;
          const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
          const fs = url ? framesRef.current.get(url) : null;
          if (fs) { const kt = fs.keyTimeAt(Number(vc.clip.source_start || 0)); if (kt >= 0) void fs.seekTo(kt); }
          continue;
        }
        // 始まった時に上の段にふさがれているクリップは、前もって走らせない
        if (fixLayers) {
          const at = vc.clip.timeline_start + 0.001;
          const there = visualClips.filter((o) => at >= o.clip.timeline_start && at < o.clip.timeline_end);
          if (there.indexOf(vc) < visibleFrom(there, at)) continue;
        }
        const startSrc = Number(vc.clip.source_start || 0);
        const v = videosRef.current.get(id);
        // 走り出し: 要素は再生を押してから実際に進み出すまで0.2〜0.3秒かかる。境目の LEAD 秒前に、
        // 境目より LEAD 秒手前から走らせておき、境目では元から同じ所を進んでいるようにする。
        const until = vc.clip.timeline_start - t;
        // 倍速の時は、その分だけタイムラインの手前から走らせる（走り出しにかかる実時間は同じ）
        // クリップの速さ sp: タイムラインの lead 秒＝素材の lead×sp 秒
        const sp = clipSpeed(vc.clip);
        const lead = Math.min(LEAD * R, startSrc / sp);
        if (v && v.paused) {
          const parkAt = startSrc - lead * sp;
          if (until <= lead && lead > 0.05) {
            try { v.currentTime = startSrc - until * sp; } catch { /* not ready */ }
            if (v.playbackRate !== rateOf(id)) v.playbackRate = rateOf(id);
            void v.play().catch(() => {});
          } else if (Math.abs(v.currentTime - parkAt) > 0.1) {
            try { v.currentTime = parkAt; } catch { /* not ready */ }
          }
        }
        const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
        const fs = url ? framesRef.current.get(url) : null;
        if (fs) void fs.ready.then(() => fs.seekTo(startSrc));
      }

      let audioGap = false;
      if (webAudio) {
        audioGap = scheduleAudio(t, dtMs);
        // この先10秒に始まる音も、4回/秒ずつ前もって解読しておく（切れ目で読み込みを待たない）
        if (nowWall - lastAheadWall > 250) { lastAheadWall = nowWall; ensureAudioAhead(t, 10); }
      }
      // AUDIO（前の作り・?webaudio=0 の時）: align + play each active audio clip's element (one per clip).
      const activeAudioClips = new Set<string>();
      let elementGap = false;
      for (const c of audioClips) {
        if (!(t >= c.timeline_start && t < c.timeline_end)) continue;
        const id = String(c.id);
        const a = audiosRef.current.get(id);
        if (!a) continue;
        activeAudioClips.add(id);
        const expected = Number(c.source_start || 0) + (t - c.timeline_start) * clipSpeed(c);
        const aDrift = Math.abs(a.currentTime - expected);
        if ((!prevActiveAudioRef.current.has(id) && aDrift > 0.04) || aDrift > 0.3) a.currentTime = expected;
        a.muted = false;
        a.preservesPitch = true;
        { const ra = Math.min(16, R * clipSpeed(c)); if (a.playbackRate !== ra) a.playbackRate = ra; }
        a.volume = c.volume == null ? 1 : Math.max(0, Math.min(1, Number(c.volume) || 0));
        if (a.paused) void a.play().catch(() => {});
        if (a.paused || a.seeking || a.readyState < 3 || Math.abs(a.currentTime - expected) > 0.25) elementGap = true;
      }
      if (elementGap) previewStats().audioGapMs += dtMs;
      // 前の作り: これから始まる音のクリップも前もって頭出ししておく（切れ目で読み込みを待たない）
      for (const c of audioClips) {
        if (!(c.timeline_start > t && c.timeline_start <= t + PREROLL)) continue;
        const a = audiosRef.current.get(String(c.id));
        const startSrc = Number(c.source_start || 0);
        if (a && a.paused && Math.abs(a.currentTime - startSrc) > 0.05) { try { a.currentTime = startSrc; } catch { /* not ready */ } }
      }
      for (const [id, a] of audiosRef.current) if (!activeAudioClips.has(id) && !a.paused) a.pause();
      prevActiveAudioRef.current = activeAudioClips;
      prevActiveVideoRef.current = activeVids;

      const drawn = drawFrame(t);
      // 映像か音が時計に追いついていない: 0.15秒続いたら、全部止めてそろうまで待つ（時計だけ進めない）
      const visualOk = drawn && visualReadyAt(t, 'run');
      if (!visualOk) { const st = previewStats(); st.frozenMs = (st.frozenMs || 0) + dtMs; feelFrozen(dtMs); }
      // 4倍以上の早送りでは、映像が追いつかなくても時計と音を止めない（絵は前のコマのまま、追いついた所から出る）。
      // 切れ目ごとに準備を待つと、10倍のつもりが7倍しか進まず何度も止まる（2026-11-19 本人「スマホで最大10倍」）。
      const skim = R >= 4;
      if (gate && ((!visualOk && !skim) || audioGap)) {
        if (!badSince) badSince = nowWall;
        else if (nowWall - badSince > 150) {
          enterPrep(t, true);
          onTimeChange(Number(t.toFixed(3)));
          rafRef.current = requestAnimationFrame(step);
          return;
        }
      } else badSince = 0;
      onTimeChange(Number(t.toFixed(3)));
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    // 裏へ行く時は音と映像の要素をその場で止める（画面の描き直しが止まると、予約済みの音と映像の要素だけが
    // 先へ進み、戻った時に二重に流れる元になる）。戻ったら、離れた所からそろえ直して流れ出す。
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        if (phase === 'run') enterPrep(lastT, false);
        else stopAudioNodes();
      } else {
        if (mgr && mgr.ctx.state !== 'running') void mgr.ctx.resume().catch(() => {});
        if (phase === 'prep') { prepSince = performance.now(); const c = playClockRef.current; if (c) c.wall = performance.now(); }
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      stopAudioNodes();
    };
    // currentTime intentionally excluded: snapshotted into playClockRef at start
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, visualClips, audioClips, sequenceDuration, drawFrame, onTimeChange, onEnded, srcByAssetId, scheduleAudio, stopAudioNodes, ensureAudioAhead, visualReadyAt, audioReadyAt, fixLayers, imageSrcByAssetId, rate]);

  // 再生中に利用者が位置を動かした（目盛りを押した・クリップをダブルクリックした・矢印キー）:
  // 再生の時計をその位置に付け替え、映像と音の要素を新しい位置へ合わせ直す。止めずに続ける。
  const currentTimeRef = useRef(currentTime);
  currentTimeRef.current = currentTime;
  const seekRevSeenRef = useRef(seekRev);
  useEffect(() => {
    if (seekRevSeenRef.current === seekRev) return;
    seekRevSeenRef.current = seekRev;
    if (!playingRef.current || !playClockRef.current) return;
    playClockRef.current = { wall: performance.now(), t: currentTimeRef.current };
    prevActiveVideoRef.current = new Set();
    prevActiveAudioRef.current = new Set();
    stopAudioNodes();
    if (gateRef.current) {
      // 新しい位置の映像と音がそろってから流れ出す（再生の輪が準備に入る）
      audioAnchorRef.current = null;
      prepRequestRef.current = true;
      return;
    }
    const mgr = audioMgrRef.current;
    audioAnchorRef.current = mgr && mgr.ctx.state === 'running' ? { ctxT0: mgr.ctx.currentTime + 0.04, t0: currentTimeRef.current, rate: rateRef.current } : null;
  }, [seekRev, stopAudioNodes]);

  const pickAtRef = useRef<((e: { clientX: number; clientY: number; button: number }) => void) | null>(null);
  // The source size of a picture clip (decoded video frame / loaded image), or null while loading.
  const clipDims = (clip: SequenceClip): { w: number; h: number } | null => {
    const imageUrl = imageSrcByAssetId.get(String(clip.asset_id || ''));
    if (imageUrl) {
      const img = imageFor(imageUrl);
      return img ? { w: img.naturalWidth, h: img.naturalHeight } : null;
    }
    const url = srcByAssetId.get(String(clip.asset_id || ''));
    const fs = url ? framesRef.current.get(url) : null;
    // a transparent video's watching copy is colour over alpha: the picture is the top half
    const half = ALPHA_ASSET_IDS.has(String(clip.asset_id || '')) ? 2 : 1;
    if (fs?.width && fs?.height) return { w: fs.width, h: fs.height / half };
    const vel = videosRef.current.get(String(clip.id));
    if (vel?.videoWidth) return { w: vel.videoWidth, h: vel.videoHeight / half };
    const md = (assets || []).find((a) => a.id === String(clip.asset_id || ''))?.metadata;
    return md?.width && md?.height ? { w: Number(md.width), h: Number(md.height) } : null;
  };

  // Selection box for the active selected clip. PiP/overlay uses its `position` window; a base
  // clip uses its SOURCE rectangle (locked to the footage aspect via `transform`) so shrinking
  // it reveals the whole source — no 9:16 crop. The box may overflow the frame.
  const selectionBoxFor = (selectedClipId: string | null | undefined) => {
    if (!selectedClipId) return null;
    const vc = visualClips.find((x) => String(x.clip.id) === String(selectedClipId));
    if (!vc) return null;
    if (!(currentTime >= vc.clip.timeline_start && currentTime < vc.clip.timeline_end)) return null;
    if (isOneForm(vc.clip)) {
      const d = clipDims(vc.clip);
      if (!d) return null;
      const m = motionAt(vc.clip, currentTime - vc.clip.timeline_start);
      const P = pictureRect(vc.clip, m, d.w, d.h, dims.w, dims.h);
      return { vc, kind: 'transform' as const, tf: m as Motion,
        rect: { x: P.x / dims.w, y: P.y / dims.h, width: P.w / dims.w, height: P.h / dims.h } };
    }
    const p = vc.position;
    const isFullPos = !!p && p.x <= 0.001 && p.y <= 0.001 && p.width >= 0.999 && p.height >= 0.999;
    if (p && !isFullPos) {
      return { vc, kind: 'position' as const, rect: p };
    }
    const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
    const fs = url ? framesRef.current.get(url) : null;
    const vw = fs?.width || 0;
    const vh = (fs?.height || 0) / (ALPHA_ASSET_IDS.has(String(vc.clip.asset_id || '')) ? 2 : 1);
    if (!vw || !vh) return null;
    const tf = vc.clip.transform || { scale: 1, x: 0, y: 0 };
    const { w, h } = dims;
    const cover = Math.max(w / vw, h / vh);
    const destW = vw * cover * tf.scale;
    const destH = vh * cover * tf.scale;
    const destX = (w - destW) / 2 + tf.x * w;
    const destY = (h - destH) / 2 + tf.y * h;
    return {
      vc, kind: 'transform' as const, tf,
      rect: { x: destX / w, y: destY / h, width: destW / w, height: destH / h },
    };
  };
  const selectedBox = selectionBoxFor(selectedClipId);

  const startBoxDrag = useCallback(
    (e: React.PointerEvent, mode: 'move' | 'nw' | 'ne' | 'sw' | 'se') => {
      if (!selectedBox) return;
      e.preventDefault();
      e.stopPropagation();
      const wrap = wrapRef.current;
      if (!wrap) return;
      // the picture area inside the preview (the canvas is letterboxed in its frame)
      const wb = wrap.getBoundingClientRect();
      const rect = contentRect
        ? { left: wb.left + contentRect.left, top: wb.top + contentRect.top, width: contentRect.width, height: contentRect.height }
        : wb;
      const start = { x: e.clientX, y: e.clientY };
      const clipId = String(selectedBox.vc.clip.id);

      let moved = false;
      const clickUp = () => {
        if (!moved && mode === 'move') pickAtRef.current?.({ clientX: start.x, clientY: start.y, button: 0 });
      };
      if (selectedBox.kind === 'transform') {
        if (!onTransformChange) { const up0 = () => { window.removeEventListener('pointerup', up0); clickUp(); }; window.addEventListener('pointerup', up0); return; }
        const tf0 = { ...selectedBox.tf };
        const boxCx = selectedBox.rect.x + selectedBox.rect.width / 2;
        const boxCy = selectedBox.rect.y + selectedBox.rect.height / 2;
        const startDist = Math.hypot((start.x - rect.left) / rect.width - boxCx, (start.y - rect.top) / rect.height - boxCy) || 0.0001;
        const move = (ev: PointerEvent) => {
          if (!moved && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 3) return;
          moved = true;
          if (mode === 'move') {
            const dx = (ev.clientX - start.x) / rect.width;
            const dy = (ev.clientY - start.y) / rect.height;
            onTransformChange(clipId, { scale: tf0.scale, x: Number((tf0.x + dx).toFixed(4)), y: Number((tf0.y + dy).toFixed(4)) });
          } else {
            const dist = Math.hypot((ev.clientX - rect.left) / rect.width - boxCx, (ev.clientY - rect.top) / rect.height - boxCy);
            const factor = Math.max(0.1, dist / startDist);
            onTransformChange(clipId, { scale: Number(Math.max(0.1, Math.min(5, tf0.scale * factor)).toFixed(4)), x: tf0.x, y: tf0.y });
          }
        };
        const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); clickUp(); };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        return;
      }

      if (!onPositionChange) return;
      const p0 = { ...selectedBox.rect };
      const move = (ev: PointerEvent) => {
        if (!moved && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 3) return;
        moved = true;
        const dx = (ev.clientX - start.x) / rect.width;
        const dy = (ev.clientY - start.y) / rect.height;
        let { x, y, width, height } = p0;
        if (mode === 'move') {
          x = p0.x + dx; y = p0.y + dy;
        } else {
          if (mode === 'nw') { x = p0.x + dx; y = p0.y + dy; width = p0.width - dx; height = p0.height - dy; }
          if (mode === 'ne') { y = p0.y + dy; width = p0.width + dx; height = p0.height - dy; }
          if (mode === 'sw') { x = p0.x + dx; width = p0.width - dx; height = p0.height + dy; }
          if (mode === 'se') { width = p0.width + dx; height = p0.height + dy; }
          const MIN = 0.05;
          width = Math.max(MIN, width); height = Math.max(MIN, height);
        }
        onPositionChange(clipId, { x: Number(x.toFixed(4)), y: Number(y.toFixed(4)), width: Number(width.toFixed(4)), height: Number(height.toFixed(4)) });
      };
      const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); clickUp(); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    },
    [selectedBox, onPositionChange, onTransformChange, contentRect],
  );

  // 選んだテロップの枠: 描かれたテロップの文字の箱を測って、映像と同じ青い枠を出す
  const [capBox, setCapBox] = useState<{ x: number; y: number; width: number; height: number } | null>(null);
  const selectedCaption = selectedClipId ? renderCaptions.find((c) => c.id === String(selectedClipId)) || null : null;
  useLayoutEffect(() => {
    if (!selectedCaption || playing) { setCapBox(null); return; }
    const measure = () => {
      const wrap = wrapRef.current;
      const el = wrap?.querySelector(`[data-caption-id="${CSS.escape(selectedCaption.id || "")}"]`) as HTMLElement | null;
      if (!wrap || !el) { setCapBox(null); return; }
      const wb = wrap.getBoundingClientRect();
      const eb = el.getBoundingClientRect();
      if (!wb.width || !wb.height || !eb.width) { setCapBox(null); return; }
      setCapBox({ x: (eb.left - wb.left) / wb.width, y: (eb.top - wb.top) / wb.height, width: eb.width / wb.width, height: eb.height / wb.height });
    };
    measure();
    const raf = requestAnimationFrame(measure);   // 書体の読み込み直後に1回測り直す
    return () => cancelAnimationFrame(raf);
  }, [selectedCaption, currentTime, playing, contentRect]);

  const startCaptionDrag = useCallback((e: React.PointerEvent) => {
    if (!selectedCaption || !onCaptionMove || !contentRect) return;
    e.preventDefault();
    e.stopPropagation();
    const start = { x: e.clientX, y: e.clientY };
    // y はテロップの高さ（画面の下からの割合、上へ＋、未指定は0.08）。x は右への寄せ（画面の幅に対する割合）
    const d0 = { x: Number(selectedCaption.design?.x || 0), y: selectedCaption.design?.y == null ? 0.08 : Number(selectedCaption.design.y) };
    const id = selectedCaption.id || "";
    const move = (ev: PointerEvent) => {
      const dx = (ev.clientX - start.x) / contentRect.width;
      const dy = (ev.clientY - start.y) / contentRect.height;
      onCaptionMove(id, { x: Number((d0.x + dx).toFixed(4)), y: Number(Math.max(0, Math.min(0.92, d0.y - dy)).toFixed(4)) });
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }, [selectedCaption, onCaptionMove, contentRect]);

  // プレビューの上で押した所にある物を選ぶ: テロップ → 絵と映像（上の段から）→ 場面。
  // 絵は透けている所を押しても選ばない（下の物が選ばれる）。同じ所をもう一度押すと、
  // そこに重なっている下の物へ順に選び直す（2026-11-16 本人「全部の素材がクリックで選択できるように」）。
  const pickCycleRef = useRef<{ x: number; y: number; ids: string[]; i: number } | null>(null);
  const alphaCanvasRef = useRef<CanvasRenderingContext2D | null>(null);
  const opaqueAt = useCallback((img: HTMLImageElement, sx: number, sy: number): boolean => {
    if (!alphaCanvasRef.current) {
      const c = document.createElement('canvas');
      c.width = 1; c.height = 1;
      alphaCanvasRef.current = c.getContext('2d', { willReadFrequently: true });
    }
    const ctx = alphaCanvasRef.current;
    if (!ctx) return true;
    try {
      ctx.clearRect(0, 0, 1, 1);
      ctx.drawImage(img, Math.floor(sx), Math.floor(sy), 1, 1, 0, 0, 1, 1);
      return ctx.getImageData(0, 0, 1, 1).data[3] > 24;
    } catch { return true; } // unreadable picture: treat as solid
  }, []);
  // 画面のその点にある物（テロップ → 絵と映像の上の段から → 場面）と、画面に対する割合の位置
  const hitsAt = useCallback((clientX: number, clientY: number): { ids: string[]; fx: number; fy: number } | null => {
    const e = { clientX, clientY };
    const wrap = wrapRef.current;
    if (!wrap) return null;
    const ids: string[] = [];
    let fx = -1;
    let fy = -1;
    // 押した所にある物を、前（上の段）から順に。同じ段ならテロップ → 絵と映像 → 場面
    const hits: Array<{ id: string; layer: number; rank: number }> = [];
    const pushHit = (id: string, rank: number) => hits.push({ id, layer: laneById.get(id) ?? 0, rank });
    for (const el of Array.from(wrap.querySelectorAll('[data-caption-id]')).reverse() as HTMLElement[]) {
      const b = el.getBoundingClientRect();
      if (e.clientX >= b.left && e.clientX <= b.right && e.clientY >= b.top && e.clientY <= b.bottom && el.dataset.captionId) pushHit(el.dataset.captionId, 0);
    }
    if (contentRect) {
      const wb = wrap.getBoundingClientRect();
      fx = (e.clientX - wb.left - contentRect.left) / contentRect.width;
      fy = (e.clientY - wb.top - contentRect.top) / contentRect.height;
      const X = fx * dims.w;
      const Y = fy * dims.h;
      const t = currentTime;
      for (let i = visualClips.length - 1; i >= 0; i -= 1) {
        const vc = visualClips[i];
        if (!(t >= vc.clip.timeline_start && t < vc.clip.timeline_end)) continue;
        if (isOneForm(vc.clip)) {
          const d = clipDims(vc.clip);
          if (!d) continue;
          const P = pictureRect(vc.clip, motionAt(vc.clip, t - vc.clip.timeline_start), d.w, d.h, dims.w, dims.h);
          const V = visibleRect(vc.clip, P);
          if (!(X >= Math.max(0, V.x) && X <= Math.min(dims.w, V.x + V.w) && Y >= Math.max(0, V.y) && Y <= Math.min(dims.h, V.y + V.h))) continue;
          const imageUrl = imageSrcByAssetId.get(String(vc.clip.asset_id || ''));
          const img = imageUrl ? imageFor(imageUrl) : null;
          if (img && !opaqueAt(img, ((X - P.x) / P.w) * img.naturalWidth, ((Y - P.y) / P.h) * img.naturalHeight)) continue;
          // 透明な映像も、透けている所を押したら下の物を選ぶ
          const aid = String(vc.clip.asset_id || '');
          if (!img && ALPHA_ASSET_IDS.has(aid) && !alphaSolidAt(aid, (X - P.x) / P.w, (Y - P.y) / P.h)) continue;
        } else {
          const p = vc.position;
          if (p && !(fx >= p.x && fx <= p.x + p.width && fy >= p.y && fy <= p.y + p.height)) continue;
        }
        pushHit(String(vc.clip.id), 1);
      }
      for (const sc of [...sceneClips].reverse()) {
        if (t >= Number(sc.timeline_start) && t < Number(sc.timeline_end)) pushHit(String(sc.id), 2);
      }
    }
    hits.forEach((h, i) => { (h as { i?: number }).i = i; });
    hits.sort((a, b) => b.layer - a.layer || a.rank - b.rank || ((a as { i?: number }).i! - (b as { i?: number }).i!));
    for (const h of hits) if (!ids.includes(h.id)) ids.push(h.id);
    return { ids, fx, fy };
  }, [contentRect, currentTime, visualClips, sceneClips, dims, imageSrcByAssetId, imageFor, opaqueAt, laneById]); // eslint-disable-line react-hooks/exhaustive-deps

  const pointAt = useCallback((clientX: number, clientY: number, pressed: boolean) => {
    if (!onPoint) return;
    const hit = hitsAt(clientX, clientY);
    if (!hit || hit.fx < 0 || hit.fx > 1 || hit.fy < 0 || hit.fy > 1) { onPoint(null); return; }
    onPoint({ x: Math.round(hit.fx * 1000) / 1000, y: Math.round(hit.fy * 1000) / 1000, ids: hit.ids.slice(0, 6), pressed });
  }, [onPoint, hitsAt]);
  // 動かしている間は0.2秒に1回だけ調べ、最後に止まった所は必ず知らせる（間引いた最後の位置を落とさない）
  const pointMoveAt = useRef(0);
  const pointLast = useRef<{ x: number; y: number } | null>(null);
  const pointTimer = useRef<number | undefined>(undefined);
  const onPointerMove = useCallback((e: { clientX: number; clientY: number; buttons: number }) => {
    if (!onPoint || e.buttons) return;
    pointLast.current = { x: e.clientX, y: e.clientY };
    const now = performance.now();
    if (now - pointMoveAt.current >= 200) {
      pointMoveAt.current = now;
      pointAt(e.clientX, e.clientY, false);
    }
    window.clearTimeout(pointTimer.current);
    pointTimer.current = window.setTimeout(() => {
      const last = pointLast.current;
      if (last) pointAt(last.x, last.y, false);
    }, 220);
  }, [onPoint, pointAt]);
  useEffect(() => () => window.clearTimeout(pointTimer.current), []);

  const pickAt = useCallback((e: { clientX: number; clientY: number; button: number }) => {
    if (e.button === 0) pointAt(e.clientX, e.clientY, true);
    if (!onPick || e.button !== 0) return;
    const hit = hitsAt(e.clientX, e.clientY);
    if (!hit) return;
    const { ids } = hit;
    if (!ids.length) { pickCycleRef.current = null; onPick(null); return; }
    const prev = pickCycleRef.current;
    const same = prev && Math.hypot(prev.x - e.clientX, prev.y - e.clientY) < 6 && prev.ids.join('|') === ids.join('|');
    const i = same && prev ? (prev.i + 1) % ids.length : 0;
    pickCycleRef.current = { x: e.clientX, y: e.clientY, ids, i };
    onPick(ids[i]);
  }, [onPick, hitsAt, pointAt]);

  useEffect(() => { pickAtRef.current = pickAt; }, [pickAt]);
  const editingCaption = useContext(CaptionEditContext);
  const box = selectedBox?.rect;
  // Measure captions in the same coordinate system as the letterboxed picture.
  const groupIds = selectedClipIds && selectedClipIds.length > 1 ? selectedClipIds : [];
  const [captionRects, setCaptionRects] = useState<Map<string, DOMRect>>(new Map());
  useLayoutEffect(() => {
    if (!selectedClipIds || selectedClipIds.length < 2 || !contentRect || playing) return;
    const wrap = wrapRef.current;
    if (!wrap) return;
    const elements = Array.from(wrap.querySelectorAll<HTMLElement>('[data-caption-id]'))
      .filter(el => selectedClipIds.includes(el.dataset.captionId || ''));
    const measure = () => {
      const wb = wrap.getBoundingClientRect();
      setCaptionRects(new Map(elements.map(el => {
        const eb = el.getBoundingClientRect();
        return [el.dataset.captionId!, new DOMRect(eb.left - wb.left, eb.top - wb.top, eb.width, eb.height)];
      })));
    };
    measure();
    const observer = new ResizeObserver(measure);
    elements.forEach(el => observer.observe(el));
    return () => observer.disconnect();
  }, [sequence, selectedClipIds, currentTime, contentRect, playing]);
  const members = groupIds.flatMap(id => {
    if (!contentRect || playing) return [];
    const caption = renderCaptions.find(c => c.id === id && c.start <= currentTime && c.end > currentTime);
    const captionRect = captionRects.get(id);
    if (caption && captionRect) {
      const x = Number(caption.design?.x ?? 0), y = Number(caption.design?.y ?? 0.08);
      return [{ id, rect: captionRect, captionY: y, patch: (dx: number, dy: number): Partial<SequenceClip> =>
        ({ style: { ...caption.design, x: x + dx, y: y - dy } }) }];
    }
    const pic = selectionBoxFor(id);
    if (!pic) return [];
    const { x, y, width, height } = pic.rect;
    const rect = new DOMRect(contentRect.left + x * contentRect.width, contentRect.top + y * contentRect.height,
      width * contentRect.width, height * contentRect.height);
    return [{ id, rect, captionY: null as number | null, patch: (dx: number, dy: number): Partial<SequenceClip> => {
      if (pic.kind === 'position') return { position: { ...pic.rect, x: x + dx, y: y + dy } };
      const transform = { ...pic.tf, x: pic.tf.x + dx, y: pic.tf.y + dy };
      const keys = sortedKeys(pic.vc.clip);
      return keys.length ? { motion_keys: setKeyAt(keys, currentTime - pic.vc.clip.timeline_start,
        transform, Number(sequence?.frame_rate) || 30) } : { transform };
    } }];
  });
  function startGroupMove(e: React.PointerEvent) {
    if (!contentRect || !onGroupMove || e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const start = { x: e.clientX, y: e.clientY };
    const ys = members.flatMap(m => m.captionY == null ? [] : [m.captionY]);
    const minY = Math.max(-Infinity, ...ys.map(y => y - .92));
    const maxY = Math.min(Infinity, ...ys);
    const { width, height } = contentRect;
    const apply = onGroupMove;
    e.currentTarget.setPointerCapture(e.pointerId);
    const target = e.currentTarget;
    const move = (ev: PointerEvent) => {
      if (ev.pointerId !== e.pointerId) return;
      const dx = (ev.clientX - start.x) / width;
      const dy = Math.min(maxY, Math.max(minY, (ev.clientY - start.y) / height));
      apply(new Map(members.map(m => [m.id, m.patch(dx, dy)])));
    };
    const finish = () => {
      target.removeEventListener('pointermove', move as EventListener);
      target.removeEventListener('lostpointercapture', finish);
    };
    target.addEventListener('pointermove', move as EventListener);
    target.addEventListener('lostpointercapture', finish);
  }
  const handle = 'absolute h-3 w-3 rounded-sm border border-white bg-sky-400';

  return (
    <div ref={wrapRef} className={`relative ${className || ''}`} style={{ width: '100%', height: '100%' }} onPointerDown={pickAt} onPointerMove={onPointerMove} onPointerLeave={() => { window.clearTimeout(pointTimer.current); pointLast.current = null; onPoint?.(null); }}>
      <canvas
        ref={canvasRef}
        width={Math.round(dims.w * pxScale)}
        height={Math.round(dims.h * pxScale)}
        style={{ display: 'block', width: '100%', height: '100%', objectFit: 'contain', background: '#000' }}
      />
      {showDiag ? (
        <div
          ref={diagRef}
          className="pointer-events-none absolute left-1 top-1 rounded bg-black/70 px-2 py-1 font-mono text-[11px] text-lime-300"
        >
          t=0.00
        </div>
      ) : null}
      {loadProgress.total > 0 && loadProgress.ready < loadProgress.total ? (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/40">
          <div className="h-7 w-7 animate-spin rounded-full border-2 border-white/30 border-t-white" />
          <div className="text-xs text-white/80">
            素材を準備中… {loadProgress.ready}/{loadProgress.total}
          </div>
        </div>
      ) : null}
      {localProg && localProg.active && localProg.bytesTotal > 0 ? (
        <div
          data-local-media
          title="このパソコンに素材の写しを取り込んでいます。終わると再生が速くなります。取り込み中も編集・再生はできます。"
          className="pointer-events-none absolute bottom-1 left-1 rounded bg-black/60 px-2 py-0.5 text-[11px] text-white/80"
        >
          素材を取り込み中 {Math.min(99, Math.floor((localProg.bytesDone / localProg.bytesTotal) * 100))}%
        </div>
      ) : null}
      {/* 段の上下どおりに下から積む: 場面・テロップ・上の段の絵（lane-order.ts） */}
      {stack.bands.map((band, bi) => {
        if (band.kind === 'pic') {
          if (band.canvas === 0) return null; // 一番下は上の canvas（canvasRef）
          return (
            <canvas
              key={`pic-${band.canvas}`}
              ref={(el) => { upperCanvasRefs.current[band.canvas] = el; }}
              width={Math.round(dims.w * pxScale)}
              height={Math.round(dims.h * pxScale)}
              className="pointer-events-none absolute left-0 top-0"
              style={{ width: '100%', height: '100%', objectFit: 'contain' }}
            />
          );
        }
        if (!contentRect) return null;
        if (band.kind === 'scene') {
          const clips = sceneClips.filter((c) => band.ids.has(String(c.id)));
          return clips.length ? (
            <div
              key={`scene-${bi}`}
              className="pointer-events-none absolute overflow-hidden"
              style={{ left: contentRect.left, top: contentRect.top, width: contentRect.width, height: contentRect.height }}
            >
              <SceneLayer clips={clips} time={currentTime} playing={playing} clockRef={playClockRef} liveTime={currentTime} />
            </div>
          ) : null;
        }
        const caps = renderCaptions.filter((c) => band.ids.has(String(c.id)));
        return caps.length ? (
          <div
            key={`cap-${bi}`}
            className="pointer-events-none absolute overflow-hidden"
            style={{ left: contentRect.left, top: contentRect.top, width: contentRect.width, height: contentRect.height }}
          >
            <div style={{ transformOrigin: 'top left', transform: `scale(${contentRect.width / dims.w})` }}>
              <LiveCaptionLayer playing={playing} currentTime={currentTime} clockRef={playClockRef} outW={dims.w} outH={dims.h} captions={caps} />
            </div>
          </div>
        ) : null;
      })}
      {members.length > 1 && !editingCaption && members.map(m => (
        <div key={m.id} data-preview-group-member={m.id} className="absolute cursor-move border-2 border-sky-400"
          style={{ left: m.rect.x, top: m.rect.y, width: m.rect.width, height: m.rect.height, touchAction: 'none' }}
          onPointerDown={startGroupMove} />
      ))}
      {members.length < 2 && capBox && !editingCaption ? (
        <div
          data-caption-select-box
          className="absolute cursor-move rounded-sm border-2 border-sky-400 bg-sky-400/10"
          style={{
            left: `${capBox.x * 100}%`, top: `${capBox.y * 100}%`,
            width: `${capBox.width * 100}%`, height: `${capBox.height * 100}%`,
            touchAction: 'none',
          }}
          onPointerDown={startCaptionDrag}
          title="ダブルクリックで文字を編集、ドラッグで位置を移動"
        />
      ) : null}
      {members.length < 2 && box && !capBox ? (
        <div
          className="absolute cursor-move border-2 border-sky-400"
          style={{
            ...(contentRect
              ? { left: contentRect.left + box.x * contentRect.width, top: contentRect.top + box.y * contentRect.height,
                  width: box.width * contentRect.width, height: box.height * contentRect.height }
              : { left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }),
            touchAction: 'none',
          }}
          onPointerDown={(e) => startBoxDrag(e, 'move')}
        >
          <div className={`${handle} -left-1.5 -top-1.5 cursor-nwse-resize`} onPointerDown={(e) => startBoxDrag(e, 'nw')} />
          <div className={`${handle} -right-1.5 -top-1.5 cursor-nesw-resize`} onPointerDown={(e) => startBoxDrag(e, 'ne')} />
          <div className={`${handle} -bottom-1.5 -left-1.5 cursor-nesw-resize`} onPointerDown={(e) => startBoxDrag(e, 'sw')} />
          <div className={`${handle} -bottom-1.5 -right-1.5 cursor-nwse-resize`} onPointerDown={(e) => startBoxDrag(e, 'se')} />
        </div>
      ) : null}
    </div>
  );
}
