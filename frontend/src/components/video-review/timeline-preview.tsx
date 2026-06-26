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
  // WebCodecs frame decoders, one per asset URL (shared across all clips of that asset).
  const framesRef = useRef<FrameSourceManager>(null as unknown as FrameSourceManager);
  if (!framesRef.current) framesRef.current = new FrameSourceManager();
  // Hidden <video> elements for AUDIO only — one per audio clip (recycled by asset).
  const audiosRef = useRef<Map<string, HTMLVideoElement>>(new Map());
  const rafRef = useRef<number | null>(null);
  const playClockRef = useRef<{ wall: number; t: number } | null>(null);
  const prevActiveAudioRef = useRef<Set<string>>(new Set());

  const supported = useMemo(() => webCodecsSupported(), []);
  const dims = useMemo(() => canvasDims(format), [format]);
  // Bumped when an asset's decoder finishes loading, so the scrub effect re-runs and paints the
  // first frame the moment it's decodable (the initial decode resolves async after the canvas
  // has already mounted — without this, the opening frame stayed black until you scrubbed).
  const [readyTick, setReadyTick] = useState(0);

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
    for (const src of wanted) {
      const fs = framesRef.current.get(src); // kick off decoder init
      if (fs && !attachedReadyRef.current.has(src)) {
        attachedReadyRef.current.add(src);
        fs.ready.then(() => setReadyTick((v) => v + 1)).catch(() => {});
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

  // full unmount cleanup
  useEffect(() => {
    const amap = audiosRef.current;
    const frames = framesRef.current;
    return () => {
      for (const [, el] of amap) el.remove();
      amap.clear();
      frames.closeAll();
    };
  }, []);

  // Resolve a clip's decoded frame at time t (or null if not decoded yet).
  const frameFor = useCallback(
    (clip: SequenceClip, t: number): { src: CanvasImageSource; vw: number; vh: number } | null => {
      const url = srcByAssetId.get(String(clip.asset_id || ''));
      if (!url) return null;
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
    [srcByAssetId],
  );

  const drawFrame = useCallback(
    (t: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const { w, h } = dims;
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, w, h);

      const active = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      for (const vc of active) {
        const got = frameFor(vc.clip, t);
        if (!got) continue;
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
      const baseGot = (() => {
        const base = active.find((vc) => vc.kind === 'base') || active[0];
        return base ? frameFor(base.clip, t) : null;
      })();
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
    },
    [dims, visualClips, effectClips, blurRegionsAt, frameFor],
  );

  // SCRUB: when not playing, decode the exact frame for currentTime then draw. The decoder
  // seek is frame-accurate (no <video> seek latency); we redraw once each active clip's
  // frame is cached.
  useEffect(() => {
    if (playing || !supported) return;
    let cancelled = false;
    const active = visualClips.filter((vc) => currentTime >= vc.clip.timeline_start && currentTime < vc.clip.timeline_end);
    drawFrame(currentTime); // paint best-available immediately (previous frame, no black flash)
    const seeks = active.map((vc) => {
      const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
      if (!url) return Promise.resolve();
      const fs = framesRef.current.get(url);
      if (!fs) return Promise.resolve();
      return fs.ready.then(() => fs.seekTo(clipSourceTime(vc.clip, currentTime)));
    });
    void Promise.all(seeks).then(() => { if (!cancelled) drawFrame(currentTime); });
    return () => { cancelled = true; };
  }, [currentTime, playing, supported, visualClips, drawFrame, srcByAssetId, readyTick]);

  // PLAYBACK: wall-clock timeline; prefetch each active source ahead so frames are decoded
  // before the playhead reaches them; draw every frame from the cache; audio via <video>.
  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      playClockRef.current = null;
      prevActiveAudioRef.current = new Set();
      for (const [, a] of audiosRef.current) a.pause();
      return;
    }
    if (!playClockRef.current) playClockRef.current = { wall: performance.now(), t: currentTime };
    const PREFETCH_AHEAD = 1.0;  // seconds of frames to keep decoded ahead of the playhead
    const PREROLL = 0.5;         // pre-decode a clip about to start
    const step = () => {
      const clock = playClockRef.current;
      if (!clock) return;
      // Provisional time from the wall clock; corrected below to the audio element so the two
      // never drift apart (the old engine kept video on <video> too, so they were inherently
      // synced — here video is canvas/rAF and audio is <video>, so we slave video to audio).
      let t = clock.t + (performance.now() - clock.wall) / 1000;

      // AUDIO: play each active clip's source (one dedicated element per clip), and pick a
      // master element (voice preferred) to use as the clock.
      const activeAudioClips = new Set<string>();
      let masterEl: HTMLVideoElement | null = null;
      let masterClip: SequenceClip | null = null;
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
        if (!masterClip || (c.role === 'voice' && masterClip.role !== 'voice')) { masterEl = a; masterClip = c; }
      }
      for (const [id, a] of audiosRef.current) if (!activeAudioClips.has(id) && !a.paused) a.pause();
      prevActiveAudioRef.current = activeAudioClips;

      // Audio-master clock: once the master audio element is actually playing, lock the timeline
      // time to ITS currentTime so the video frame we draw matches what's being heard.
      if (masterEl && masterClip && !masterEl.paused && masterEl.readyState >= 2) {
        const tAudio = Number(masterClip.timeline_start) + (masterEl.currentTime - Number(masterClip.source_start || 0));
        if (Number.isFinite(tAudio) && tAudio >= 0) {
          t = tAudio;
          clock.t = t;                      // mirror into the wall clock so playback stays
          clock.wall = performance.now();   // smooth across audio gaps (no master => wall clock)
        }
      }

      if (t >= sequenceDuration) {
        for (const [, a] of audiosRef.current) a.pause();
        onEnded();
        drawFrame(sequenceDuration);
        onTimeChange(sequenceDuration);
        return;
      }

      // VIDEO: keep decoded frames flowing ahead of the (audio-locked) playhead, then draw.
      const active = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      for (const vc of active) {
        const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
        if (!url) continue;
        const fs = framesRef.current.get(url);
        if (!fs || isFrozen(vc.clip)) continue; // frozen clip needs only its single cached frame
        fs.prefetch(clipSourceTime(vc.clip, t), PREFETCH_AHEAD);
      }
      for (const vc of visualClips) {
        if (active.includes(vc)) continue;
        const startsSoon = vc.clip.timeline_start > t && vc.clip.timeline_start <= t + PREROLL;
        if (!startsSoon) continue;
        const url = srcByAssetId.get(String(vc.clip.asset_id || ''));
        const fs = url ? framesRef.current.get(url) : null;
        if (fs) fs.prefetch(Number(vc.clip.source_start || 0), 0.1);
      }

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
      {!supported ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4 text-center text-xs text-white/70">
          このブラウザはWebCodecsプレビューに未対応です（Chrome/Edge最新版でご利用ください）。
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
