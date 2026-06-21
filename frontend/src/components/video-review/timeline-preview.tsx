'use client';

import { useCallback, useEffect, useMemo, useRef } from 'react';

import type { EditSequence, SequenceAsset, SequenceClip } from './video-review-editor';

// Live timeline compositor: draws the current state of the edit (base video +
// overlay/PiP layers + captions + blur) onto a <canvas> for the given playhead
// time, so manual edits reflect immediately (delete a caption -> gone; move a clip
// -> reflected). The full-quality export stays in the server-side renderer.
// Stage 1 = visual compositing + scrub + playback (video). Audio is layered in next.

type Props = {
  sequence: EditSequence | null;
  assets: SequenceAsset[];
  currentTime: number;
  playing: boolean;
  format: string;
  onTimeChange: (t: number) => void;
  onEnded: () => void;
  className?: string;
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

// Wrap caption text so each line fits maxWidth. Keeps ASCII words intact; wraps CJK
// per-character. Respects explicit newlines. Mirrors backend _wrap_caption_ass so the
// preview matches the export.
function wrapCaption(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const out: string[] = [];
  for (const hard of text.split('\n')) {
    let line = '';
    let i = 0;
    while (i < hard.length) {
      const ch = hard[i];
      const isAscii = ch.charCodeAt(0) < 128;
      if (isAscii && ch.trim()) {
        // take the whole ASCII word
        let word = '';
        while (i < hard.length && hard[i].charCodeAt(0) < 128 && hard[i].trim()) {
          word += hard[i]; i++;
        }
        if (line && ctx.measureText(line + word).width > maxWidth) {
          out.push(line); line = word;
        } else {
          line += word;
        }
        continue;
      }
      if (line.trim() && ctx.measureText(line + ch).width > maxWidth) {
        out.push(line); line = ch.trim() ? ch : '';
      } else {
        line += ch;
      }
      i++;
    }
    out.push(line.replace(/\s+$/, ''));
  }
  return out.length ? out : [text];
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

export function TimelinePreview({ sequence, assets, currentTime, playing, format, onTimeChange, onEnded, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const videosRef = useRef<Map<string, HTMLVideoElement>>(new Map());
  // Separate elements for audio: the same asset may be used as a video layer (at one
  // source time) AND as an audio clip (at a different source time), so they can't
  // share one element.
  const audiosRef = useRef<Map<string, HTMLVideoElement>>(new Map());
  const rafRef = useRef<number | null>(null);
  const playClockRef = useRef<{ wall: number; t: number } | null>(null);

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

  const effectClips = useMemo(
    () => (sequence?.tracks || []).filter((t) => t.type === 'effect').flatMap((t) => t.clips || []),
    [sequence],
  );

  const audioClips = useMemo(
    () => (sequence?.tracks || []).filter((t) => t.type === 'audio').flatMap((t) => t.clips || []),
    [sequence],
  );
  const audioAssets = useMemo(() => {
    const ids = new Set(audioClips.map((c) => String(c.asset_id || '')).filter(Boolean));
    return videoAssets.filter((a) => ids.has(a.id));
  }, [audioClips, videoAssets]);

  const assetById = useMemo(() => {
    const m = new Map<string, SequenceAsset>();
    for (const a of videoAssets) m.set(a.id, a);
    return m;
  }, [videoAssets]);

  // One hidden <video> PER CLIP (keyed by clip id), not per asset. Two clips that use the
  // SAME asset at DIFFERENT source times (e.g. a fullscreen background + a PiP wipe of the
  // same footage) must each own a separate element — sharing one made them fight over
  // currentTime, so the background jumped to the wipe's time (flicker / wrong frame).
  useEffect(() => {
    const map = videosRef.current;
    const wanted = new Map<string, string>(); // clipId -> src
    for (const vc of visualClips) {
      const a = vc.clip.asset_id ? assetById.get(String(vc.clip.asset_id)) : null;
      if (a) wanted.set(String(vc.clip.id), assetSrc(a));
    }
    for (const [cid, el] of map) {
      if (!wanted.has(cid)) {
        el.remove();
        map.delete(cid);
      }
    }
    for (const [cid, src] of wanted) {
      const existing = map.get(cid);
      if (existing) {
        if (existing.src !== src && src) existing.src = src; // asset of this clip changed
        continue;
      }
      const v = document.createElement('video');
      v.src = src;
      // same-origin (Next proxy) — do NOT set crossOrigin (would break the load).
      v.muted = true;
      v.playsInline = true;
      v.preload = 'auto';
      v.style.display = 'none';
      document.body.appendChild(v);
      map.set(cid, v);
    }
  }, [visualClips, assetById]);

  // hidden audio elements for assets referenced by audio clips
  useEffect(() => {
    const map = audiosRef.current;
    const wanted = new Set(audioAssets.map((a) => a.id));
    for (const [id, el] of map) {
      if (!wanted.has(id)) {
        el.remove();
        map.delete(id);
      }
    }
    for (const a of audioAssets) {
      if (map.has(a.id)) continue;
      const v = document.createElement('video');
      v.src = assetSrc(a);
      v.muted = true; // unmuted only while its clip is active during playback
      v.playsInline = true;
      v.preload = 'auto';
      v.style.display = 'none';
      document.body.appendChild(v);
      map.set(a.id, v);
    }
  }, [audioAssets]);

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
        if (vc.kind === 'overlay' && vc.position) {
          const px = vc.position.x * w;
          const py = vc.position.y * h;
          const pw = vc.position.width * w;
          const ph = vc.position.height * h;
          drawCover(ctx, v, px, py, pw, ph);
        } else {
          drawCover(ctx, v, 0, 0, w, h);
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

      // captions — style-aware, with line-wrapping so long text fits the frame width.
      const caps = captionClips.filter((c) => t >= c.timeline_start && t <= c.timeline_end && typeof c.text === 'string' && c.text.trim());
      const cap = caps[caps.length - 1];
      if (cap?.text) {
        const st = cap.style || {};
        const baseFont = h * 0.038;
        const fontSize = Math.round(baseFont * (st.fontSize ? Number(st.fontSize) : 1));
        const weight = st.bold === false ? 'normal' : 'bold';
        ctx.font = `${weight} ${fontSize}px "Yu Gothic UI", "Meiryo", sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.lineJoin = 'round';
        ctx.lineWidth = Math.max(3, fontSize * 0.18 * (st.outlineWidth != null ? Number(st.outlineWidth) : 1));
        ctx.strokeStyle = st.outlineColor || '#000';
        ctx.fillStyle = st.color || '#fff';
        const maxWidth = w * 0.92;
        const lines = wrapCaption(ctx, cap.text, maxWidth);
        const lineH = fontSize * 1.2;
        const block = lineH * lines.length;
        const cx = w / 2;
        // vertical anchor by position preset
        const pos = st.position || 'bottom';
        let firstCy: number;
        if (pos === 'top') firstCy = Math.round(h * 0.06) + lineH / 2;
        else if (pos === 'center') firstCy = h / 2 - block / 2 + lineH / 2;
        else firstCy = h - Math.round(h * 0.06) - block + lineH / 2;
        lines.forEach((ln, i) => {
          const cy = firstCy + i * lineH;
          ctx.strokeText(ln, cx, cy);
          ctx.fillText(ln, cx, cy);
        });
      }
    },
    [dims, visualClips, captionClips, effectClips],
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
      const srcTime = Number(vc.clip.source_start || 0) + (currentTime - vc.clip.timeline_start);
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
      for (const [, v] of videosRef.current) v.pause();
      for (const [, a] of audiosRef.current) a.pause();
      return;
    }
    playClockRef.current = { wall: performance.now(), t: currentTime };
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
        const expected = Number(vc.clip.source_start || 0) + (t - vc.clip.timeline_start);
        if (Math.abs(v.currentTime - expected) > 0.18) v.currentTime = expected;
        if (v.paused) void v.play().catch(() => {});
      }
      for (const [id, v] of videosRef.current) if (!activeIds.has(id) && !v.paused) v.pause();

      // audio: play each active audio clip's source (dedicated elements); pause the rest
      const activeAudioAssets = new Set<string>();
      for (const c of audioClips) {
        if (!(t >= c.timeline_start && t < c.timeline_end)) continue;
        const id = String(c.asset_id || '');
        const a = audiosRef.current.get(id);
        if (!a) continue;
        activeAudioAssets.add(id);
        const expected = Number(c.source_start || 0) + (t - c.timeline_start);
        if (Math.abs(a.currentTime - expected) > 0.2) a.currentTime = expected;
        a.muted = false;
        a.volume = c.role === 'music' ? 0.5 : c.role === 'sfx' ? 0.8 : 1;
        if (a.paused) void a.play().catch(() => {});
      }
      for (const [id, a] of audiosRef.current) if (!activeAudioAssets.has(id) && !a.paused) a.pause();

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

  return (
    <canvas
      ref={canvasRef}
      width={dims.w}
      height={dims.h}
      className={className}
      style={{ display: 'block', width: '100%', height: '100%', objectFit: 'contain', background: '#000' }}
    />
  );
}
