'use client';

import { useEffect, useState } from 'react';
import { CaptionLayer, type RenderCaption } from '@/components/video-review/caption-layer';
import { captionFontFilesFor, loadCaptionFontFiles } from '@/components/video-review/caption-design';

type Payload = { outW: number; outH: number; time: number; captions: RenderCaption[] };

declare global {
  interface Window {
    __setNativeCaptionPayload?: (payload: Payload) => void;
    chrome?: { webview?: { addEventListener?: (type: string, cb: (event: MessageEvent) => void) => void } };
  }
}

const EMPTY: Payload = { outW: 1080, outH: 1920, time: 0, captions: [] };

function loadFonts(p?: Payload) {
  // keep the overlay alive if a font fails: loadCaptionFontFiles skips it
  return loadCaptionFontFiles(captionFontFilesFor((p?.captions || []).map((c) => c.design)));
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

    window.__setNativeCaptionPayload = (next: Payload) => { void loadFonts(next); setPayload(next || EMPTY); };
    const onMessage = (event: MessageEvent) => {
      const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
      if (data?.type === 'caption-payload') { void loadFonts(data.payload); setPayload(data.payload || EMPTY); }
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
