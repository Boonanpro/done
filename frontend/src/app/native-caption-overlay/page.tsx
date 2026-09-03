'use client';

import { useEffect, useState } from 'react';
import { CaptionLayer, type RenderCaption } from '@/components/video-review/caption-layer';
import { CAPTION_FONT_FILES } from '@/components/video-review/caption-design';

type Payload = { outW: number; outH: number; time: number; captions: RenderCaption[] };

declare global {
  interface Window {
    __setNativeCaptionPayload?: (payload: Payload) => void;
    chrome?: { webview?: { addEventListener?: (type: string, cb: (event: MessageEvent) => void) => void } };
  }
}

const EMPTY: Payload = { outW: 1080, outH: 1920, time: 0, captions: [] };

async function loadFonts() {
  try {
    const fontSet = (document as unknown as { fonts?: FontFaceSet }).fonts;
    if (!fontSet || typeof FontFace === 'undefined') return;
    await Promise.all(
      CAPTION_FONT_FILES.map(async ([family, url, weight]) => {
        try {
          const face = new FontFace(family, `url("${url}")`, { weight: String(weight) });
          await face.load();
          fontSet.add(face);
        } catch {
          /* keep overlay alive if one font fails */
        }
      }),
    );
    await fontSet.ready;
  } catch {
    /* ignored */
  }
}

export default function NativeCaptionOverlayPage() {
  const [payload, setPayload] = useState<Payload>(EMPTY);

  useEffect(() => {
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
    document.body.style.margin = '0';
    document.body.style.overflow = 'hidden';
    document.body.style.pointerEvents = 'none';
    void loadFonts();

    window.__setNativeCaptionPayload = (next: Payload) => setPayload(next || EMPTY);
    const onMessage = (event: MessageEvent) => {
      const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
      if (data?.type === 'caption-payload') setPayload(data.payload || EMPTY);
    };
    window.chrome?.webview?.addEventListener?.('message', onMessage);
    return () => {
      delete window.__setNativeCaptionPayload;
    };
  }, []);

  return (
    <div style={{ width: payload.outW, height: payload.outH, background: 'transparent', pointerEvents: 'none' }}>
      <CaptionLayer outW={payload.outW} outH={payload.outH} captions={payload.captions} time={payload.time} />
    </div>
  );
}
