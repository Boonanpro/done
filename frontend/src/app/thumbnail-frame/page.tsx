'use client';

// サムネの書き出しの的。サーバー（scripts/render_thumbnail.py）が headless Chromium でここを開き、
// window.__setThumbPayload({doc, marks, outW}) で中身を渡して、data-thumb-ready="true" になったら撮る。
// エディターと同じ <ThumbCanvas> で描くので、書き出しは画面で見た物と同じ。どの画面からもつながない。

import { useEffect, useState } from 'react';

import { ThumbCanvas } from '@/components/thumbnail/thumb-canvas';
import { asThumbDoc, loadThumbFonts, type ThumbDoc, type ThumbMark } from '@/components/thumbnail/thumb-doc';

type Payload = { doc: ThumbDoc; marks?: ThumbMark[]; outW?: number };

declare global {
  interface Window { __setThumbPayload?: (p: Payload) => void }
}

export default function ThumbnailFramePage() {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [fontsReady, setFontsReady] = useState(false);
  const [imgs, setImgs] = useState<[number, number]>([0, 1]);
  useEffect(() => {
    window.__setThumbPayload = (p) => {
      const doc = asThumbDoc(p.doc);
      setFontsReady(false);
      setPayload({ ...p, doc });
      void loadThumbFonts(doc).then(() => document.fonts.ready).then(() => setFontsReady(true));
    };
    document.body.style.margin = '0';
    document.body.style.background = 'transparent';
  }, []);
  if (!payload) return <div data-thumb-ready="waiting" />;
  const outW = payload.outW || 1280;
  const ready = fontsReady && imgs[0] >= imgs[1];
  return (
    <div style={{ width: outW, position: 'absolute', left: 0, top: 0 }} data-thumb-ready={ready ? 'true' : 'loading'}>
      <ThumbCanvas
        doc={payload.doc}
        width={outW}
        marks={payload.marks}
        onImageState={(a, b) => setImgs([a, b])}
      />
    </div>
  );
}
