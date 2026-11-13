'use client';

/**
 * Editable scenes on the timeline (a clip with `scene` = a HyperFrames-style HTML composition with
 * one GSAP timeline). The preview draws them with the SAME sandboxed scene frame the export
 * screenshots (/caption-frame -> editor-scene.js), so what the editor shows is what gets burned.
 * The frame is transparent: the footage under it stays real timeline clips.
 */
import { useEffect, useMemo, useRef } from 'react';

import type { SequenceClip } from './video-review-editor';
import { setSceneInfo, type SceneItem } from './scene-store';

type SceneHost = HTMLDivElement & {
  ready?: Promise<{ ok: boolean }>;
  seek?: (t: number) => void;
  setTime?: (t: number) => void;
  dispose?: () => void;
  items?: SceneItem[];
  onitems?: (items: SceneItem[]) => void;
};

const sceneApi = () => window as unknown as { createScenePreview?: (item: unknown, host: HTMLDivElement) => HTMLDivElement };

let scriptLoad: Promise<void> | undefined;
function loadSceneScript(): Promise<void> {
  return scriptLoad ||= new Promise<void>((resolve, reject) => {
    const s = document.createElement('script');
    s.src = '/api/v1/editor-assistant/native-scene-script';
    s.onload = () => resolve();
    s.onerror = () => { scriptLoad = undefined; reject(new Error('scene script')); };
    document.head.append(s);
  });
}

export type SceneClip = SequenceClip & { scene: Record<string, unknown>; scene_offset?: number };

export function isSceneClip(c: SequenceClip): c is SceneClip {
  const s = (c as { scene?: unknown }).scene;
  return !!s && typeof s === 'object' && typeof (s as { html?: unknown }).html === 'string';
}

function localTime(c: SceneClip, t: number) {
  return t - Number(c.timeline_start || 0) + Number(c.scene_offset || 0);
}

const inClip = (c: SceneClip, t: number) => t >= Number(c.timeline_start) && t < Number(c.timeline_end);

function SceneFrame({ clip, time, playing, clockRef }: {
  clip: SceneClip; time: number; playing: boolean;
  clockRef: React.MutableRefObject<{ wall: number; t: number } | null>;
}) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const hostRef = useRef<SceneHost | null>(null);
  const clipRef = useRef(clip);
  clipRef.current = clip;
  const timeRef = useRef(time);
  timeRef.current = time;
  const sceneKey = useMemo(() => JSON.stringify(clip.scene), [clip.scene]);

  // (Re)create the frame when the scene's code or edits change. The old frame stays on screen
  // until the new one has drawn, so editing a text never flashes the scene away.
  useEffect(() => {
    let cancelled = false;
    const box = boxRef.current;
    if (!box) return;
    loadSceneScript().then(() => {
      if (cancelled || !sceneApi().createScenePreview) return;
      const h = document.createElement('div') as SceneHost;
      h.style.cssText = 'position:absolute;inset:0;opacity:0';
      box.append(h);
      const made = performance.now();
      sceneApi().createScenePreview!({ id: clip.id, title: '場面', scene: clipRef.current.scene }, h);
      const frame = h.querySelector('iframe');
      if (frame) frame.style.cssText = 'width:100%;height:100%;border:0;display:block;background:transparent;color-scheme:light';
      const controls = h.querySelector<HTMLElement>('.proposal-controls');
      if (controls) controls.style.display = 'none';
      h.seek?.(localTime(clipRef.current, timeRef.current));
      h.ready?.then((r) => {
        if (cancelled) { h.dispose?.(); h.remove(); return; }
        h.setTime?.(localTime(clipRef.current, playing && clockRef.current ? clockRef.current.t : timeRef.current));
        if (boxRef.current) boxRef.current.dataset.sceneLoadMs = String(Math.round(performance.now() - made));
        requestAnimationFrame(() => {
          if (cancelled) return;
          const old = hostRef.current;
          hostRef.current = h;
          h.style.opacity = '1';
          if (old) { old.dispose?.(); old.remove(); }
        });
        if (r.ok) setSceneInfo(String(clipRef.current.id), { duration: Number((clipRef.current.scene as { duration?: number }).duration) || 0, items: h.items || [] });
      });
    }).catch(() => {});
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneKey, clip.id]);

  useEffect(() => () => { hostRef.current?.dispose?.(); hostRef.current?.remove(); hostRef.current = null; }, []);

  // Paused / scrubbing: follow the playhead.
  useEffect(() => {
    if (playing) return;
    hostRef.current?.setTime?.(localTime(clip, time));
    if (boxRef.current) boxRef.current.style.opacity = inClip(clip, time) ? '1' : '0';
  }, [time, playing, clip]);

  // Playing: follow the preview's own clock every frame (the editor only re-renders 8x/s).
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = -1;
    const loop = () => {
      const c = clockRef.current;
      if (c && hostRef.current) {
        const lt = localTime(clipRef.current, c.t);
        if (Math.abs(lt - last) > 0.004) { hostRef.current.setTime?.(lt); last = lt; }
      }
      if (c && boxRef.current) {
        const v = inClip(clipRef.current, c.t) ? '1' : '0';
        if (boxRef.current.style.opacity !== v) boxRef.current.style.opacity = v;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, clockRef]);

  return <div ref={boxRef} data-scene-clip={String(clip.id)} style={{ position: 'absolute', inset: 0, opacity: inClip(clip, time) ? 1 : 0 }} />;
}

export function SceneLayer({ clips, time, playing, clockRef, liveTime }: {
  clips: SceneClip[]; time: number; playing: boolean;
  clockRef: React.MutableRefObject<{ wall: number; t: number } | null>;
  /** the time the preview is drawing right now (playback clock while playing) */
  liveTime: number;
}) {
  // keep frames mounted a little before and after their clip so they are ready at the cut
  const near = clips.filter((c) => liveTime >= Number(c.timeline_start) - 4 && liveTime < Number(c.timeline_end) + 1);
  return (
    <>
      {near.map((c) => (
        <SceneFrame
          key={String(c.id)}
          clip={c}
          time={time}
          playing={playing}
          clockRef={clockRef}
        />
      ))}
    </>
  );
}
