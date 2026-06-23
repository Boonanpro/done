'use client';

import { useMemo } from 'react';
import {
  CAPTION_FONT_FACE_CSS,
  type CaptionDesign,
  captionAnchorStyle,
  captionBoxStyle,
  captionTextStyle,
} from './caption-design';

export type RenderCaption = {
  id?: string;
  text: string;
  start: number;
  end: number;
  design?: CaptionDesign;
};

// Renders the caption layer at the OUTPUT resolution (outW x outH). The preview scales this
// down with a CSS transform; the export screenshots it 1:1. Same component both places.
export function CaptionLayer({
  outW,
  outH,
  captions,
  time,
}: {
  outW: number;
  outH: number;
  captions: RenderCaption[];
  time: number;
}) {
  const active = useMemo(() => {
    const a = captions.filter((c) => c.text?.trim() && time >= c.start && time <= c.end);
    return a.length ? a[a.length - 1] : null; // last active wins (mirrors the old canvas behavior)
  }, [captions, time]);
  const design: CaptionDesign = active?.design || {};
  return (
    <div style={{ position: 'relative', width: outW, height: outH, overflow: 'hidden', pointerEvents: 'none' }}>
      <style>{CAPTION_FONT_FACE_CSS}</style>
      {active ? (
        <div style={captionAnchorStyle(design, outH)}>
          <div style={captionBoxStyle(design, outH)}>
            <p style={captionTextStyle(design, outH)}>{active.text}</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
