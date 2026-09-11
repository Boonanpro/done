'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { EditSequence, SequenceAsset, SequenceClip } from './video-review-editor';
import { CaptionLayer, type RenderCaption } from './caption-layer';
import type { CaptionDesign } from './caption-design';
import { FrameSourceManager, webCodecsSupported } from './frame-source';

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
  playing: boolean;
  format: string;
  onTimeChange: (t: number) => void;
  onEnded: () => void;
  className?: string;
  // Direct-manipulation of a clip's position/transform in the preview.
  selectedClipId?: string | null;
  onPositionChange?: (clipId: string, position: { x: number; y: number; width: number; height: number }) => void;
  onTransformChange?: (clipId: string, transform: { scale: number; x: number; y: number }) => void;
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

function isFrozen(clip: SequenceClip): boolean {
  return clip.source_end != null && Number(clip.source_end) <= Number(clip.source_start || 0);
}
function clipSourceTime(clip: SequenceClip, t: number): number {
  return Number(clip.source_start || 0) + (isFrozen(clip) ? 0 : t - clip.timeline_start);
}

export function TimelinePreview({ sequence, assets, blurRegionsAt, currentTime, playing, format, onTimeChange, onEnded, className, selectedClipId, onPositionChange, onTransformChange }: Props) {
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
  const dims = useMemo(() => canvasDims(format), [format]);
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

  const videoAssets = useMemo(() => (assets || []).filter((a) => assetSrc(a)), [assets]);

  const assetById = useMemo(() => {
    const m = new Map<string, SequenceAsset>();
    for (const a of videoAssets) m.set(a.id, a);
    return m;
  }, [videoAssets]);

  // asset_id -> decode source URL (the proxy). Memoised so frame lookups are cheap per draw.
  const srcByAssetId = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of videoAssets) { const s = assetSrc(a); if (s) m.set(a.id, s); }
    return m;
  }, [videoAssets]);

  const sequenceDuration = useMemo(() => {
    const tracks = sequence?.tracks || [];
    return Math.max(0, ...tracks.flatMap((t) => (t.clips || []).map((c) => c.timeline_end || 0)), Number(sequence?.duration || 0));
  }, [sequence]);

  // flat visual clips (base + overlay), with layer + position
  const visualClips = useMemo<VisualClip[]>(() => {
    const out: VisualClip[] = [];
    for (const track of sequence?.tracks || []) {
      if (track.type !== 'video' && track.type !== 'overlay') continue;
      for (const clip of track.clips || []) {
        const overlay = isOverlayClip(clip, track.type);
        // A pop-out clip is drawn by the editor's canvas overlay (matted person breaking out of a
        // rounded card); skip its plain-wipe rendering here so no sharp-cornered rectangle peeks
        // out behind the rounded card.
        if (overlay && (clip.effects || []).some((e) => e.type === 'popout')) continue;
        out.push({
          clip,
          kind: overlay ? 'overlay' : 'base',
          layer: clip.layer ?? (overlay ? 1 : 0),
          position: (clip.position as VisualClip['position']) || null,
        });
      }
    }
    return out.sort((a, b) => a.layer - b.layer); // draw bottom (low layer) first
  }, [sequence]);

  const captionClips = useMemo(
    () => (sequence?.tracks || []).filter((t) => t.type === 'caption').flatMap((t) => t.clips || []),
    [sequence],
  );

  const renderCaptions = useMemo<RenderCaption[]>(
    () =>
      captionClips
        .filter((c) => typeof c.text === 'string' && c.text.trim())
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

  const effectClips = useMemo(
    () => (sequence?.tracks || []).filter((t) => t.type === 'effect').flatMap((t) => t.clips || []),
    [sequence],
  );

  const audioClips = useMemo(
    () => (sequence?.tracks || []).filter((t) => t.type === 'audio').flatMap((t) => t.clips || []),
    [sequence],
  );

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
        fs.ready.then(() => { readyUrlsRef.current.add(src); setReadyTick((v) => v + 1); countReady(); }).catch(() => { readyUrlsRef.current.add(src); countReady(); });
      }
    }
    for (const u of [...attachedReadyRef.current]) if (!wanted.has(u)) attachedReadyRef.current.delete(u);
  }, [visualClips, srcByAssetId]);

  // Audio elements — ONE PER AUDIO CLIP (keyed by clip id), recycled by asset to avoid reloads.
  const PRELOAD_BEHIND = 6;
  const PRELOAD_AHEAD = 16;
  const WINDOW_STEP = 3;
  const loadBucket = Math.floor((currentTime || 0) / WINDOW_STEP);
  useEffect(() => {
    const map = audiosRef.current;
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
      v.src = assetSrc(a);
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
  }, [audioClips, assetById, loadBucket]);

  // Muted VIDEO <video> elements — one per visual clip near the playhead, recycled by asset so a
  // split/ripple reuses an already-decoded element (no reload). These are only drawn during
  // playback; while paused the canvas comes from WebCodecs, so this reconcile is never visible.
  useEffect(() => {
    const map = videosRef.current;
    const lo = (currentTime || 0) - PRELOAD_BEHIND;
    const hi = (currentTime || 0) + PRELOAD_AHEAD;
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
      v.src = assetSrc(a);
      v.dataset.assetId = aid;
      v.muted = true; // audio comes from the dedicated audio elements
      v.playsInline = true;
      v.preload = 'auto';
      v.style.display = 'none';
      document.body.appendChild(v);
      map.set(cid, v);
    }
    for (const list of orphansByAsset.values()) for (const el of list) el.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visualClips, assetById, loadBucket]);

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

  // Resolve a clip's frame at time t. During playback we draw the hardware <video> element
  // (real-time, synced to audio); when paused/scrubbing we draw the WebCodecs cache (frame-
  // accurate). The <video> path falls through to WebCodecs while the element is still loading
  // (play-start transition) and for frozen clips (a single held frame is cheap to cache).
  const frameFor = useCallback(
    (clip: SequenceClip, t: number): { src: CanvasImageSource; vw: number; vh: number } | null => {
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
          if (playingRef.current || !supported || Math.abs(vel.currentTime - expected) < 0.12) {
            return { src: vel, vw: vel.videoWidth, vh: vel.videoHeight };
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
      const frame = fs.peek(clipSourceTime(clip, t), lo, hi);
      if (!frame) return null;
      return { src: frame, vw: frame.width || fs.width, vh: frame.height || fs.height };
    },
    [srcByAssetId, supported],
  );

  const drawFrame = useCallback(
    (t: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const { w, h } = dims;

      const active = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      // Resolve every active clip's frame up front (null = not decoded yet).
      const layers: Array<{ vc: VisualClip; got: { src: CanvasImageSource; vw: number; vh: number } }> = [];
      for (const vc of active) {
        const got = frameFor(vc.clip, t);
        if (got) layers.push({ vc, got });
      }
      // NEVER-BLACK: if the timeline HAS content here but its primary layer isn't decoded yet,
      // HOLD the current canvas (don't blank) — like a native NLE, the picture stays up and
      // snaps to the head the instant the frame is ready. We only clear+repaint when we actually
      // have something to draw. A genuine empty gap (no active clips) still paints black, which
      // is correct (the sequence really is empty there).
      const hasBase = active.some((vc) => vc.kind === 'base');
      const baseReady = layers.some((l) => l.vc.kind === 'base');
      if (active.length > 0 && ((hasBase && !baseReady) || (!hasBase && layers.length === 0))) {
        if (showDiag && diagRef.current) {
          const baseClip = active.find((vc) => vc.kind === 'base') || active[0];
          const url = baseClip ? srcByAssetId.get(String(baseClip.clip.asset_id || '')) : null;
          const fs = url ? framesRef.current.get(url) : null;
          diagRef.current.textContent = `t=${t.toFixed(2)}  HOLD  want-src=${baseClip ? clipSourceTime(baseClip.clip, t).toFixed(2) : '-'}  wc[${fs ? fs.status() : 'none'}]`;
        }
        return; // keep the last good frame on screen
      }

      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, w, h);

      for (const { vc, got } of layers) {
        const tf = vc.clip.transform;
        const cr = vc.clip.crop;
        const px = vc.position ? vc.position.x * w : 0;
        const py = vc.position ? vc.position.y * h : 0;
        const pw = vc.position ? vc.position.width * w : w;
        const ph = vc.position ? vc.position.height * h : h;
        // Wipe shape (circle / rounded "photo") clips ANY video clip to that box.
        const shape = (vc.clip as { shape?: string }).shape;
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

      // blur / mosaic regions (effect clips active now)
      const baseGot = (layers.find((l) => l.vc.kind === 'base') || layers[0])?.got || null;
      for (const e of effectClips) {
        const start = Number(e.timeline_start || 0);
        const end = Number(e.timeline_end || 0);
        if (!(t >= start && t < end)) continue;
        const region = (e as unknown as { region?: { x: number; y: number; width: number; height: number } }).region;
        if (!region || !baseGot) continue;
        const rx = region.x * w;
        const ry = region.y * h;
        const rw = Math.max(2, region.width * w);
        const rh = Math.max(2, region.height * h);
        const style = String((e as unknown as { style?: string }).style || '');
        ctx.save();
        ctx.beginPath();
        ctx.rect(rx, ry, rw, rh);
        ctx.clip();
        ctx.filter = style.includes('mosaic') ? 'blur(8px)' : 'blur(14px)';
        drawCover(ctx, baseGot.src, baseGot.vw, baseGot.vh, 0, 0, w, h);
        ctx.restore();
      }

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
        ctx.filter = 'blur(14px)';
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
    },
    [dims, visualClips, effectClips, blurRegionsAt, frameFor, showDiag],
  );

  // SCRUB: when not playing, paint the exact frame for currentTime. With WebCodecs we decode it
  // frame-accurately (no <video> seek latency); without it we seek the <video> elements instead.
  useEffect(() => {
    if (playing) return;
    let cancelled = false;
    const active = visualClips.filter((vc) => currentTime >= vc.clip.timeline_start && currentTime < vc.clip.timeline_end);
    drawFrame(currentTime); // paint best-available immediately (previous frame, no black flash)
    if (supported) {
      const seeks = active.map((vc) => {
        const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
        if (!url) return Promise.resolve();
        const fs = framesRef.current.get(url);
        if (!fs) return Promise.resolve();
        return fs.ready.then(() => fs.seekTo(clipSourceTime(vc.clip, currentTime)));
      });
      void Promise.all(seeks).then(() => { if (!cancelled) drawFrame(currentTime); });
      return () => { cancelled = true; };
    }
    // Fallback (no WebCodecs): seek the muted <video> elements and redraw once they land.
    for (const vc of active) {
      if (isFrozen(vc.clip)) continue;
      const v = videosRef.current.get(String(vc.clip.id));
      if (v) { if (!v.paused) v.pause(); try { v.currentTime = clipSourceTime(vc.clip, currentTime); } catch { /* not ready */ } }
    }
    const timer = window.setTimeout(() => { if (!cancelled) drawFrame(currentTime); }, 140);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [currentTime, playing, supported, visualClips, drawFrame, srcByAssetId, readyTick]);

  // PLAYBACK: a wall-clock timeline drives muted VIDEO <video> elements and unmuted AUDIO <video>
  // elements, all playing in real time at rate 1, each seeked to its source offset when its clip
  // becomes active (and re-synced only on large drift). Because video and audio are BOTH hardware
  // <video> elements on the same clock, they stay in sync without per-frame correction — this is
  // the proven native-NLE playback path. drawFrame() composites the video elements onto the canvas.
  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      playClockRef.current = null;
      prevActiveAudioRef.current = new Set();
      prevActiveVideoRef.current = new Set();
      for (const [, v] of videosRef.current) v.pause();
      for (const [, a] of audiosRef.current) a.pause();
      return;
    }
    if (!playClockRef.current) playClockRef.current = { wall: performance.now(), t: currentTime };
    const PREROLL = 1.5; // pre-seek a clip about to start so its first frame is ready at the cut
    const step = () => {
      const clock = playClockRef.current;
      if (!clock) return;
      // Provisional time from the wall clock; refined below to the MASTER video element's actual
      // position so the playhead and the displayed frame are the same quantity (zero drift).
      let t = clock.t + (performance.now() - clock.wall) / 1000;
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
      const active = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      const activeVids = new Set<string>();
      for (const vc of active) {
        const id = String(vc.clip.id);
        if (isFrozen(vc.clip)) {
          const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
          const fs = url ? framesRef.current.get(url) : null;
          if (fs) void fs.ready.then(() => fs.seekTo(Number(vc.clip.source_start || 0)));
          continue;
        }
        const v = videosRef.current.get(id);
        if (!v) continue;
        activeVids.add(id);
        const expected = clipSourceTime(vc.clip, t);
        // Seek on activation or on big drift only; re-seeking a playing element every frame is
        // what made audio warble in the old code. Video re-seeks aren't audible.
        if (!prevActiveVideoRef.current.has(id) || Math.abs(v.currentTime - expected) > 0.15) {
          try { v.currentTime = expected; } catch { /* not ready */ }
        }
        if (v.paused) void v.play().catch(() => {});
      }
      for (const [id, v] of videosRef.current) if (!activeVids.has(id) && !v.paused) v.pause();

      // MASTER CLOCK: drive the timeline time from the actual position of the displayed base
      // <video> element. The playhead and the on-screen frame are then the SAME number, so they
      // can't diverge (the old wall clock let the element drift up to 0.15s behind the playhead).
      // At a cut/gap the active base element isn't playing yet → keep the wall clock (mirrored),
      // and drawFrame paints the frame-accurate WebCodecs frame for `t` until the element syncs.
      let masterT: number | null = null;
      for (const vc of active) {
        if (vc.kind !== 'base' || isFrozen(vc.clip)) continue;
        const v = videosRef.current.get(String(vc.clip.id));
        if (v && v.readyState >= 2 && v.videoWidth && !v.paused) {
          masterT = Number(vc.clip.timeline_start) + (v.currentTime - Number(vc.clip.source_start || 0));
          break;
        }
      }
      if (masterT != null && Number.isFinite(masterT) && masterT >= 0 && masterT < sequenceDuration) t = masterT;
      clock.t = t;                     // mirror so the wall clock continues smoothly from the
      clock.wall = performance.now();  // master when the master drops out at a cut/gap

      // PRE-ROLL: pre-seek a clip about to become active so its frame is ready at the join — both
      // its <video> element AND a WebCodecs frame as a safety net (if the element is still seeking
      // at the cut, drawFrame falls back to the decoded frame instead of flashing black).
      for (const vc of visualClips) {
        const id = String(vc.clip.id);
        if (activeVids.has(id) || isFrozen(vc.clip)) continue;
        if (!(vc.clip.timeline_start > t && vc.clip.timeline_start <= t + PREROLL)) continue;
        const startSrc = Number(vc.clip.source_start || 0);
        const v = videosRef.current.get(id);
        if (v && Math.abs(v.currentTime - startSrc) > 0.1) { try { v.currentTime = startSrc; } catch { /* not ready */ } }
        const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
        const fs = url ? framesRef.current.get(url) : null;
        if (fs) void fs.ready.then(() => fs.seekTo(startSrc));
      }

      // AUDIO: align + play each active audio clip's element (one per clip).
      const activeAudioClips = new Set<string>();
      for (const c of audioClips) {
        if (!(t >= c.timeline_start && t < c.timeline_end)) continue;
        const id = String(c.id);
        const a = audiosRef.current.get(id);
        if (!a) continue;
        activeAudioClips.add(id);
        const expected = Number(c.source_start || 0) + (t - c.timeline_start);
        if (!prevActiveAudioRef.current.has(id) || Math.abs(a.currentTime - expected) > 0.3) a.currentTime = expected;
        a.muted = false;
        a.volume = c.role === 'music' ? 0.5 : c.role === 'sfx' ? 0.8 : 1;
        if (a.paused) void a.play().catch(() => {});
      }
      for (const [id, a] of audiosRef.current) if (!activeAudioClips.has(id) && !a.paused) a.pause();
      prevActiveAudioRef.current = activeAudioClips;
      prevActiveVideoRef.current = activeVids;

      drawFrame(t);
      onTimeChange(Number(t.toFixed(3)));
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    };
    // currentTime intentionally excluded: snapshotted into playClockRef at start
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, visualClips, audioClips, sequenceDuration, drawFrame, onTimeChange, onEnded, srcByAssetId]);

  // Selection box for the active selected clip. PiP/overlay uses its `position` window; a base
  // clip uses its SOURCE rectangle (locked to the footage aspect via `transform`) so shrinking
  // it reveals the whole source — no 9:16 crop. The box may overflow the frame.
  const selectedBox = (() => {
    if (!selectedClipId) return null;
    const vc = visualClips.find((x) => String(x.clip.id) === String(selectedClipId));
    if (!vc) return null;
    if (!(currentTime >= vc.clip.timeline_start && currentTime < vc.clip.timeline_end)) return null;
    const p = vc.position;
    const isFullPos = !!p && p.x <= 0.001 && p.y <= 0.001 && p.width >= 0.999 && p.height >= 0.999;
    if (p && !isFullPos) {
      return { vc, kind: 'position' as const, rect: p };
    }
    const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
    const fs = url ? framesRef.current.get(url) : null;
    const vw = fs?.width || 0;
    const vh = fs?.height || 0;
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
  })();

  const startBoxDrag = useCallback(
    (e: React.PointerEvent, mode: 'move' | 'nw' | 'ne' | 'sw' | 'se') => {
      if (!selectedBox) return;
      e.preventDefault();
      e.stopPropagation();
      const wrap = wrapRef.current;
      if (!wrap) return;
      const rect = wrap.getBoundingClientRect();
      const start = { x: e.clientX, y: e.clientY };
      const clipId = String(selectedBox.vc.clip.id);

      if (selectedBox.kind === 'transform') {
        if (!onTransformChange) return;
        const tf0 = { ...selectedBox.tf };
        const boxCx = selectedBox.rect.x + selectedBox.rect.width / 2;
        const boxCy = selectedBox.rect.y + selectedBox.rect.height / 2;
        const startDist = Math.hypot((start.x - rect.left) / rect.width - boxCx, (start.y - rect.top) / rect.height - boxCy) || 0.0001;
        const move = (ev: PointerEvent) => {
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
        const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        return;
      }

      if (!onPositionChange) return;
      const p0 = { ...selectedBox.rect };
      const move = (ev: PointerEvent) => {
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
      const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    },
    [selectedBox, onPositionChange, onTransformChange],
  );

  const box = selectedBox?.rect;
  const handle = 'absolute h-3 w-3 rounded-sm border border-white bg-sky-400';

  return (
    <div ref={wrapRef} className={`relative ${className || ''}`} style={{ width: '100%', height: '100%' }}>
      <canvas
        ref={canvasRef}
        width={dims.w}
        height={dims.h}
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
      {contentRect && renderCaptions.length ? (
        <div
          className="pointer-events-none absolute overflow-hidden"
          style={{ left: contentRect.left, top: contentRect.top, width: contentRect.width, height: contentRect.height }}
        >
          <div style={{ transformOrigin: 'top left', transform: `scale(${contentRect.width / dims.w})` }}>
            <CaptionLayer outW={dims.w} outH={dims.h} captions={renderCaptions} time={currentTime} />
          </div>
        </div>
      ) : null}
      {box ? (
        <div
          className="absolute cursor-move border-2 border-sky-400"
          style={{
            left: `${box.x * 100}%`, top: `${box.y * 100}%`,
            width: `${box.width * 100}%`, height: `${box.height * 100}%`,
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
