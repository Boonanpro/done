'use client';

// Internal render target. The export pipeline (app/api/production_asset_routes.py) points a
// headless Chromium at /caption-frame?p=<base64 json> and screenshots it with a transparent
// background. Because it renders the SAME <CaptionLayer> as the live editor preview, the burned
// caption matches the timeline pixel-for-pixel. Not linked from any UI.
//
// For ANIMATED captions the screenshotter loads the page ONCE then drives the playhead via
// window.__renderCaptionAt(t) per frame (much faster than navigating per frame).

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { CaptionLayer, type RenderCaption } from '@/components/video-review/caption-layer';
import { CAPTION_FONT_FILES } from '@/components/video-review/caption-design';

type Payload = { outW: number; outH: number; time: number; captions: RenderCaption[] };

declare global {
  interface Window {
    __renderCaptionAt?: (t: number) => Promise<void>;
    __setCaptionPayload?: (payload: Payload) => Promise<void>;
    __nativeCaptionPayload?: Payload;
  }
}

function decodePayload(raw: string | null): Payload | null {
  if (!raw) return null;
  try {
    // URL-safe base64 (-/_) -> standard, then base64(UTF-8 JSON) -> JSON. escape/atob handles
    // multibyte (Japanese) text. URL-safe is required: a '+' in the query becomes a space.
    const std = raw.replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(decodeURIComponent(escape(atob(std)))) as Payload;
  } catch {
    return null;
  }
}

function Inner() {
  const sp = useSearchParams();
  const initialPayload = decodePayload(sp.get('p'));
  const [payload, setPayload] = useState<Payload | null>(initialPayload);
  const [time, setTime] = useState<number>(initialPayload?.time ?? 0);
  const [viewport, setViewport] = useState({ w: 1, h: 1 });
  const [ready, setReady] = useState(false);

  // Let the screenshotter set the playhead and await the next painted frame.
  useEffect(() => {
    window.__renderCaptionAt = (t: number) =>
      new Promise<void>((resolve) => {
        setTime(t);
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });
    window.__setCaptionPayload = (next: Payload) =>
      new Promise<void>((resolve) => {
        setPayload(next);
        setTime(next.time);
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });
    if (window.__nativeCaptionPayload) {
      void window.__setCaptionPayload(window.__nativeCaptionPayload);
    }
    return () => {
      delete window.__renderCaptionAt;
      delete window.__setCaptionPayload;
    };
  }, []);

  useEffect(() => {
    const update = () => setViewport({ w: window.innerWidth, h: window.innerHeight });
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  useEffect(() => {
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
    document.body.style.margin = '0';
    let cancelled = false;
    (async () => {
      // The bundled faces use font-display:block (invisible until loaded), and @font-face in an
      // injected <style> does NOT register in document.fonts in time for the screenshot. So load
      // every face via the FontFace API and add it to document.fonts explicitly, then await.
      try {
        const fontSet = (document as unknown as { fonts?: FontFaceSet }).fonts;
        if (fontSet && typeof FontFace !== 'undefined') {
          await Promise.all(
            CAPTION_FONT_FILES.map(async ([family, url, weight]) => {
              try {
                const face = new FontFace(family, `url("${url}")`, { weight: String(weight) });
                await face.load();
                fontSet.add(face);
              } catch {
                /* a single face failing must not block the rest */
              }
            }),
          );
          await fontSet.ready;
        }
      } catch {
        /* ignore */
      }
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (cancelled) return;
          setReady(true);
          document.body.setAttribute('data-caption-ready', '1');
        }),
      );
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!payload) return null;
  const scale = Math.min(viewport.w / payload.outW, viewport.h / payload.outH);
  const left = (viewport.w - payload.outW * scale) / 2;
  const top = (viewport.h - payload.outH * scale) / 2;
  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', position: 'relative', pointerEvents: 'none' }} data-ready={ready ? '1' : '0'}>
      <div style={{ width: payload.outW, height: payload.outH, position: 'absolute', left, top, transform: `scale(${scale})`, transformOrigin: 'top left' }}>
        <CaptionLayer outW={payload.outW} outH={payload.outH} captions={payload.captions} time={time} />
      </div>
    </div>
  );
}

export default function CaptionFramePage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}
