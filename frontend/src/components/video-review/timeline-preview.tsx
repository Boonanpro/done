'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { EditSequence, SequenceAsset, SequenceClip } from './video-review-editor';
import { CaptionLayer, type RenderCaption } from './caption-layer';
import type { CaptionDesign } from './caption-design';

// Live timeline compositor: draws the current state of the edit (base video +
// overlay/PiP layers + captions + blur) onto a <canvas> for the given playhead
// time, so manual edits reflect immediately (delete a caption -> gone; move a clip
// -> reflected). The full-quality export stays in the server-side renderer.
// Stage 1 = visual compositing + scrub + playback (video). Audio is layered in next.

type Props = {
  sequence: EditSequence | null;
  assets: SequenceAsset[];
  // Manual blur boxes active NOW (normalized output coords, tracked position already resolved).
  // Painted on the canvas so the preview matches the export and never flickers (no backdrop-filter).
  // Resolve the active blur boxes AT a given time. Called inside drawFrame with the playback
  // clock so the box is evaluated at the same instant as the video frame (no lag = no peeking).
  blurRegionsAt?: (t: number) => Array<{ x: number; y: number; width: number; height: number }>;
  currentTime: number;
  playing: boolean;
  format: string;
  onTimeChange: (t: number) => void;
  onEnded: () => void;
  className?: string;
  // Stage 2: direct-manipulation of a PiP/overlay clip's position in the preview.
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

// cover-draw a video frame into a destination rect (object-fit: cover)
function drawCover(
  ctx: CanvasRenderingContext2D,
  video: HTMLVideoElement,
  dx: number,
  dy: number,
  dw: number,
  dh: number,
) {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return;
  const scale = Math.max(dw / vw, dh / vh);
  const sw = dw / scale;
  const sh = dh / scale;
  const sx = (vw - sw) / 2;
  const sy = (vh - sh) / 2;
  ctx.drawImage(video, sx, sy, sw, sh, dx, dy, dw, dh);
}

// Non-destructive placement: draw the FULL source frame (no crop) into the box, scaled to
// cover the box by default (identical look to drawCover when transform is identity), then
// zoomed/panned by `transform`. Overflow is CLIPPED by the box window, so the source pixels
// outside the frame are preserved and revealed when scale<1 or when panned.
function drawSource(
  ctx: CanvasRenderingContext2D,
  video: HTMLVideoElement,
  dx: number, dy: number, dw: number, dh: number,
  transform: { scale: number; x: number; y: number } | null | undefined,
  outW: number, outH: number,
  crop?: { top: number; bottom: number; left: number; right: number } | null,
) {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return;
  // Placement (transform) uses the FULL source — crop does NOT change size/position.
  const s = transform?.scale ?? 1;
  const tx = transform?.x ?? 0;
  const ty = transform?.y ?? 0;
  const cover = Math.max(dw / vw, dh / vh);
  const destW = vw * cover * s;
  const destH = vh * cover * s;
  const destX = dx + (dw - destW) / 2 + tx * outW;
  const destY = dy + (dh - destH) / 2 + ty * outH;
  // crop = a MASK: keep only the inner region of the placed frame; the trimmed edges are
  // simply not painted, so whatever is underneath (lower clip / black) shows there. The
  // visible content stays at the exact same place and size — no zoom.
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
  ctx.drawImage(video, sx, sy, sw, sh, dkX, dkY, dkW, dkH);
  ctx.restore();
}

export function TimelinePreview({ sequence, assets, blurRegionsAt, currentTime, playing, format, onTimeChange, onEnded, className, selectedClipId, onPositionChange, onTransformChange }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const videosRef = useRef<Map<string, HTMLVideoElement>>(new Map());
  // Separate elements for audio: the same asset may be used as a video layer (at one
  // source time) AND as an audio clip (at a different source time), so they can't
  // share one element.
  const audiosRef = useRef<Map<string, HTMLVideoElement>>(new Map());
  const rafRef = useRef<number | null>(null);
  const playClockRef = useRef<{ wall: number; t: number } | null>(null);
  // Clip ids that were active LAST frame, so we seek a media element only when it first
  // becomes active (or drifts a lot) — not every frame, which warbles a playing element.
  const prevActiveVideoRef = useRef<Set<string>>(new Set());
  const prevActiveAudioRef = useRef<Set<string>>(new Set());

  // Only clips within this window of the playhead get a live <video>/<audio> element. This caps
  // the element count (a 90-clip timeline spun up ~90 decoders all fighting one file = the black
  // screen on load). The window re-centres in coarse steps so it isn't recomputed every frame.
  const PRELOAD_BEHIND = 6;   // seconds kept behind the playhead
  const PRELOAD_AHEAD = 16;   // seconds kept ahead (covers upcoming clips + pre-roll)
  const WINDOW_STEP = 3;      // re-window granularity
  const loadBucket = Math.floor((currentTime || 0) / WINDOW_STEP);

  const dims = useMemo(() => canvasDims(format), [format]);

  const videoAssets = useMemo(
    () => (assets || []).filter((a) => assetSrc(a)),
    [assets],
  );

  const sequenceDuration = useMemo(() => {
    const tracks = sequence?.tracks || [];
    return Math.max(0, ...tracks.flatMap((t) => (t.clips || []).map((c) => c.timeline_end || 0)), Number(sequence?.duration || 0));
  }, [sequence]);

  // flat visual clips (base + overlay), with their layer + position
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

  // Captions for the HTML overlay (same shape the export route consumes).
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

  // The video fills the wrapper with object-fit:contain (letterboxed). The caption overlay is
  // rendered at OUTPUT resolution and CSS-scaled to sit exactly over the contained video rect,
  // so it lines up with both the canvas preview and the export. Measured via ResizeObserver.
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
      if (h > ch) {
        h = ch;
        w = ch * aspect;
      }
      setContentRect({ left: (cw - w) / 2, top: (ch - h) / 2, width: w, height: h });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [dims.w, dims.h]);

  const effectClips = useMemo(
    () => (sequence?.tracks || []).filter((t) => t.type === 'effect').flatMap((t) => t.clips || []),
    [sequence],
  );

  const audioClips = useMemo(
    () => (sequence?.tracks || []).filter((t) => t.type === 'audio').flatMap((t) => t.clips || []),
    [sequence],
  );
  const assetById = useMemo(() => {
    const m = new Map<string, SequenceAsset>();
    for (const a of videoAssets) m.set(a.id, a);
    return m;
  }, [videoAssets]);

  // One hidden <video> PER CLIP (keyed by clip id), not per asset. Two clips that use the
  // SAME asset at DIFFERENT source times (e.g. a fullscreen background + a PiP wipe of the
  // same footage) must each own a separate element — sharing one made them fight over
  // currentTime, so the background jumped to the wipe's time (flicker / wrong frame).
  //
  // During a drag the sequence updates every pointer move, so this reconcile runs often and
  // clip ids can churn (an overwritten neighbour splits into `<id>` + `<id>__r`). We must NOT
  // reload elements on every tick: (1) compare by a stored assetId (NOT el.src — the browser
  // normalises src to an absolute URL so a string compare is always "different" and would
  // reload every element every move = full black screen); (2) RECYCLE orphan elements of the
  // same asset for newly-appearing clip ids so a split reuses an already-decoded element.
  useEffect(() => {
    const map = videosRef.current;
    const lo = (currentTime || 0) - PRELOAD_BEHIND;
    const hi = (currentTime || 0) + PRELOAD_AHEAD;
    const wanted = new Map<string, string>(); // clipId -> assetId (only clips near the playhead)
    for (const vc of visualClips) {
      const aid = String(vc.clip.asset_id || '');
      if (!aid || !assetById.has(aid)) continue;
      if (vc.clip.timeline_end >= lo && vc.clip.timeline_start <= hi) wanted.set(String(vc.clip.id), aid);
    }
    // Orphans = elements whose clip id is gone, grouped by assetId for recycling.
    const orphansByAsset = new Map<string, HTMLVideoElement[]>();
    for (const [cid, el] of map) {
      if (!wanted.has(cid)) {
        const aid = el.dataset.assetId || '';
        (orphansByAsset.get(aid) || orphansByAsset.set(aid, []).get(aid)!).push(el);
        map.delete(cid);
      }
    }
    for (const [cid, aid] of wanted) {
      if (map.has(cid)) continue; // unchanged clip keeps its element (no reload)
      const recycled = orphansByAsset.get(aid)?.pop();
      if (recycled) {
        map.set(cid, recycled); // same asset already decoded — reuse, no reload, no black
        continue;
      }
      const a = assetById.get(aid)!;
      const v = document.createElement('video');
      v.src = assetSrc(a);
      v.dataset.assetId = aid;
      // same-origin (Next proxy) — do NOT set crossOrigin (would break the load).
      v.muted = true;
      v.playsInline = true;
      // Default to 'metadata' (header only): with one <video> per clip there can be dozens
      // of elements, and 'auto' makes them ALL fully buffer on mount — that was the ~10s
      // black/no-audio stall on refresh. The proximity effect below upgrades clips near the
      // playhead to 'auto' so the visible ones load fast and the rest stay lightweight.
      v.preload = 'metadata';
      v.style.display = 'none';
      document.body.appendChild(v);
      map.set(cid, v);
    }
    // Truly leftover orphans (asset no longer used anywhere) get removed.
    for (const list of orphansByAsset.values()) {
      for (const el of list) el.remove();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visualClips, assetById, loadBucket]);

  // Eagerly buffer only the clips near the playhead; keep far clips at 'metadata'. This makes
  // refresh fast (a few elements load, not all of them) while playback stays smooth because
  // upcoming clips are upgraded before the cut.
  useEffect(() => {
    const WINDOW_AHEAD = 4;
    const WINDOW_BEHIND = 1.5;
    for (const vc of visualClips) {
      const v = videosRef.current.get(String(vc.clip.id));
      if (!v) continue;
      const near = vc.clip.timeline_end >= currentTime - WINDOW_BEHIND && vc.clip.timeline_start <= currentTime + WINDOW_AHEAD;
      const want = near ? 'auto' : 'metadata';
      if (v.preload !== want) v.preload = want;
    }
  }, [currentTime, visualClips]);

  // Hidden audio elements — ONE PER AUDIO CLIP (keyed by clip id), like the video layers. The
  // same asset can back several audio clips at once (e.g. a dropped full-length clip overlapping
  // existing clips); a single shared element would be yanked to conflicting source times each
  // frame, causing the audio to jump / drift. Per-clip elements (recycled by asset to avoid
  // reloads) give each active clip its own, collision-free playhead.
  useEffect(() => {
    const map = audiosRef.current;
    const lo = (currentTime || 0) - PRELOAD_BEHIND;
    const hi = (currentTime || 0) + PRELOAD_AHEAD;
    const wanted = new Map<string, string>(); // clipId -> assetId (only clips near the playhead)
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
      v.muted = true; // unmuted only while its clip is active during playback
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
    const vmap = videosRef.current;
    const amap = audiosRef.current;
    return () => {
      for (const [, el] of vmap) el.remove();
      for (const [, el] of amap) el.remove();
      vmap.clear();
      amap.clear();
    };
  }, []);

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
        const v = videosRef.current.get(String(vc.clip.id));
        if (!v || !v.videoWidth) continue;
        // Any clip (base or overlay) with a position renders into that box; otherwise
        // fullscreen. The source is placed non-destructively (full frame preserved, clipped
        // by the box) so zoom/pan reveals overflow instead of cropping it.
        const tf = vc.clip.transform;
        const cr = vc.clip.crop;
        if (vc.position) {
          drawSource(ctx, v, vc.position.x * w, vc.position.y * h, vc.position.width * w, vc.position.height * h, tf, w, h, cr);
        } else {
          drawSource(ctx, v, 0, 0, w, h, tf, w, h, cr);
        }
      }

      // blur / mosaic regions (effect clips active now). region is normalized to the
      // output frame here (approximation; source-frame mapping refined later).
      for (const e of effectClips) {
        const start = Number(e.timeline_start || 0);
        const end = Number(e.timeline_end || 0);
        if (!(t >= start && t < end)) continue;
        const region = (e as unknown as { region?: { x: number; y: number; width: number; height: number } }).region;
        if (!region) continue;
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
        // redraw the active base layer within the clipped region
        const base = active.find((vc) => vc.kind === 'base');
        const bv = base ? videosRef.current.get(String(base.clip.id)) : null;
        if (bv && bv.videoWidth) drawCover(ctx, bv, 0, 0, w, h);
        ctx.restore();
      }

      // Manual blur boxes. Resolved at THIS frame's time t (not a lagging prop) so the box tracks
      // the moving target exactly — painted on the canvas (no flicker, matches the baked gaussian).
      for (const r of (blurRegionsAt ? blurRegionsAt(t) : [])) {
        const rx = r.x * w;
        const ry = r.y * h;
        const rw = Math.max(2, r.width * w);
        const rh = Math.max(2, r.height * h);
        ctx.save();
        ctx.beginPath();
        ctx.rect(rx, ry, rw, rh);
        ctx.clip();
        ctx.filter = 'blur(14px)';
        const base = active.find((vc) => vc.kind === 'base') || active[0];
        const bv = base ? videosRef.current.get(String(base.clip.id)) : null;
        if (bv && bv.videoWidth) drawCover(ctx, bv, 0, 0, w, h);
        ctx.restore();
      }

      // Captions are NOT drawn on the canvas anymore — they render as an HTML <CaptionLayer>
      // overlay (same component the export screenshots) so the preview equals the burned video,
      // with real fonts / boxes / shadows the canvas couldn't match.
    },
    [dims, visualClips, effectClips, blurRegionsAt],
  );

  const seekVideo = useCallback((video: HTMLVideoElement, time: number): Promise<void> => {
    return new Promise((resolve) => {
      if (video.readyState >= 2 && Math.abs(video.currentTime - time) < 0.05) return resolve();
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        video.removeEventListener('seeked', finish);
        resolve();
      };
      video.addEventListener('seeked', finish);
      try {
        video.currentTime = Math.max(0, time);
      } catch {
        finish();
      }
      window.setTimeout(finish, 350);
    });
  }, []);

  // SCRUB: when not playing, compose the exact frame for currentTime
  useEffect(() => {
    if (playing) return;
    let cancelled = false;
    const active = visualClips.filter((vc) => currentTime >= vc.clip.timeline_start && currentTime < vc.clip.timeline_end);
    const seeks = active.map((vc) => {
      const v = videosRef.current.get(String(vc.clip.id));
      if (!v) return Promise.resolve();
      // Freeze-frame clip (source_end <= source_start): hold the single source frame, don't advance.
      const frozen = vc.clip.source_end != null && Number(vc.clip.source_end) <= Number(vc.clip.source_start || 0);
      const srcTime = Number(vc.clip.source_start || 0) + (frozen ? 0 : currentTime - vc.clip.timeline_start);
      return seekVideo(v, srcTime);
    });
    void Promise.all(seeks).then(() => {
      if (!cancelled) drawFrame(currentTime);
    });
    return () => {
      cancelled = true;
    };
  }, [currentTime, playing, visualClips, drawFrame, seekVideo]);

  // PLAYBACK: advance a wall-clock-driven timeline; keep each active source playing
  // at the right offset; draw every frame.
  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      playClockRef.current = null;
      prevActiveVideoRef.current = new Set();
      prevActiveAudioRef.current = new Set();
      for (const [, v] of videosRef.current) v.pause();
      for (const [, a] of audiosRef.current) a.pause();
      return;
    }
    // Initialize the wall clock ONLY when playback actually starts. This effect also re-runs
    // when the clip list changes mid-play (a clip added, or the parent passes a new sequence
    // object on a poll); resetting the clock then would snap playback back to the LAGGED
    // `currentTime` prop, jumping every source backward each time — heard as a warbling
    // "play + rewind at once" / underwater voice. Preserving the running clock avoids that.
    if (!playClockRef.current) playClockRef.current = { wall: performance.now(), t: currentTime };
    const step = () => {
      const clock = playClockRef.current;
      if (!clock) return;
      const t = clock.t + (performance.now() - clock.wall) / 1000;
      if (t >= sequenceDuration) {
        for (const [, v] of videosRef.current) v.pause();
        for (const [, a] of audiosRef.current) a.pause();
        onEnded();
        drawFrame(sequenceDuration);
        onTimeChange(sequenceDuration);
        return;
      }
      const active = visualClips.filter((vc) => t >= vc.clip.timeline_start && t < vc.clip.timeline_end);
      const activeIds = new Set<string>();
      for (const vc of active) {
        const id = String(vc.clip.id);
        const v = videosRef.current.get(id);
        if (!v) continue;
        activeIds.add(id);
        const frozen = vc.clip.source_end != null && Number(vc.clip.source_end) <= Number(vc.clip.source_start || 0);
        const expected = Number(vc.clip.source_start || 0) + (frozen ? 0 : t - vc.clip.timeline_start);
        // Keep VIDEO tightly aligned: seek on activation or as soon as it drifts >0.12s. Video
        // re-seeks aren't audible, and a loose tolerance showed the WRONG frame (a later/other
        // clip's footage) — very visible with the short, source-jumping clips after a tight
        // re-cut. (Audio stays seek-on-activation only, below, to avoid the warble.)
        if (frozen) {
          // Hold the frozen frame: keep it parked at the source frame and paused (no playback).
          if (Math.abs(v.currentTime - expected) > 0.04) { try { v.currentTime = expected; } catch { /* not ready */ } }
          if (!v.paused) v.pause();
        } else {
          if (!prevActiveVideoRef.current.has(id) || Math.abs(v.currentTime - expected) > 0.12) v.currentTime = expected;
          if (v.paused) void v.play().catch(() => {});
        }
      }
      for (const [id, v] of videosRef.current) if (!activeIds.has(id) && !v.paused) v.pause();

      // PRE-ROLL: a clip about to become active within PREROLL seconds gets pre-seeked to its
      // start now, so its frame is decoded and ready at the join — kills the flicker/black
      // flash that appeared when the next clip wasn't seeked yet at the cut.
      const PREROLL = 0.5;
      for (const vc of visualClips) {
        const id = String(vc.clip.id);
        if (activeIds.has(id)) continue;
        const startsSoon = vc.clip.timeline_start > t && vc.clip.timeline_start <= t + PREROLL;
        if (!startsSoon) continue;
        const v = videosRef.current.get(id);
        if (!v) continue;
        const startSrc = Number(vc.clip.source_start || 0);
        if (Math.abs(v.currentTime - startSrc) > 0.1) {
          try { v.currentTime = startSrc; } catch { /* not ready yet */ }
        }
      }

      // audio: play each active audio clip's source (one dedicated element per clip); pause rest
      const activeAudioClips = new Set<string>();
      for (const c of audioClips) {
        if (!(t >= c.timeline_start && t < c.timeline_end)) continue;
        const id = String(c.id);
        const a = audiosRef.current.get(id);
        if (!a) continue;
        activeAudioClips.add(id);
        // Seek the audio element ONLY when its clip just became active (align it once to the
        // wall clock) or it drifted a lot (>0.3s). Re-seeking a PLAYING audio element every
        // frame is exactly what made the voice warble / sound underwater. Video & audio are
        // both aligned to the same wall-clock time at onset, so they stay lip-synced as they
        // play at rate 1 — without chasing each other frame by frame.
        const expected = Number(c.source_start || 0) + (t - c.timeline_start);
        if (!prevActiveAudioRef.current.has(id) || Math.abs(a.currentTime - expected) > 0.3) a.currentTime = expected;
        a.muted = false;
        a.volume = c.role === 'music' ? 0.5 : c.role === 'sfx' ? 0.8 : 1;
        if (a.paused) void a.play().catch(() => {});
      }
      for (const [id, a] of audiosRef.current) if (!activeAudioClips.has(id) && !a.paused) a.pause();
      prevActiveVideoRef.current = activeIds;
      prevActiveAudioRef.current = activeAudioClips;

      drawFrame(t);
      onTimeChange(Number(t.toFixed(3)));
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    };
    // currentTime intentionally excluded: we snapshot it into playClockRef at start
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, visualClips, audioClips, sequenceDuration, drawFrame, onTimeChange, onEnded]);

  // Selection box for the active selected clip. A PiP/overlay clip uses its `position`
  // window (free-aspect box). A base clip uses its SOURCE rectangle (locked to the video's
  // real aspect ratio, derived from `transform`) so the box matches the actual footage shape
  // (e.g. tall for a phone screen recording) and shrinking it reveals the WHOLE source — no
  // 9:16 crop. The box may overflow the frame; the frame is just a window.
  const selectedBox = (() => {
    if (!selectedClipId) return null;
    const vc = visualClips.find((x) => String(x.clip.id) === String(selectedClipId));
    if (!vc) return null;
    if (!(currentTime >= vc.clip.timeline_start && currentTime < vc.clip.timeline_end)) return null;
    // A position that is (effectively) the full frame is NOT a real PiP window — treat the
    // clip as a base clip so its box is locked to the source aspect (not 9:16).
    const p = vc.position;
    const isFullPos = !!p && p.x <= 0.001 && p.y <= 0.001 && p.width >= 0.999 && p.height >= 0.999;
    if (p && !isFullPos) {
      return { vc, kind: 'position' as const, rect: p };
    }
    const v = videosRef.current.get(String(vc.clip.id));
    const vw = v?.videoWidth || 0;
    const vh = v?.videoHeight || 0;
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
        // Base clip: move = pan (transform.x/y); corner = uniform aspect-locked scale around center.
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

      // PiP/overlay: free-aspect position window. Allow off-screen placement (the frame is
      // just a window) — no [0,1] clamp on position, only a minimum size.
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
