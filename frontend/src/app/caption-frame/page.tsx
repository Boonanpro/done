'use client';

// Internal render target. The export pipeline (app/api/production_asset_routes.py) points a
// headless Chromium at /caption-frame?p=<base64 json> and screenshots it with a transparent
// background. Because it renders the SAME <CaptionLayer> as the live editor preview, the burned
// caption matches the timeline pixel-for-pixel. Not linked from any UI.

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { CaptionLayer, type RenderCaption } from '@/components/video-review/caption-layer';
import { CAPTION_FONT_FILES } from '@/components/video-review/caption-design';

type Payload = { outW: number; outH: number; time: number; captions: RenderCaption[] };

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
  const payload = decodePayload(sp.get('p'));
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Make the page itself transparent so omit_background screenshots are clean.
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
    document.body.style.margin = '0';
    let cancelled = false;
    (async () => {
      // IMPORTANT: the bundled faces use font-display:block (invisible until loaded), and
      // @font-face declared in an injected <style> does NOT register in document.fonts in time
      // for the screenshot. So load every face via the FontFace API and add it to document.fonts
      // explicitly, then await — otherwise the screenshot catches blank (unpainted) text.
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
      // Two RAFs so layout + paint settle before the screenshotter reads the readiness flag.
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
  return (
    <div style={{ width: payload.outW, height: payload.outH }} data-ready={ready ? '1' : '0'}>
      <CaptionLayer outW={payload.outW} outH={payload.outH} captions={payload.captions} time={payload.time} />
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
