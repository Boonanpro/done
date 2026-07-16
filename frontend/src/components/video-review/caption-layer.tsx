'use client';

import { useMemo } from 'react';
import type { CSSProperties } from 'react';
import {
  CAPTION_FONT_FACE_CSS,
  type CaptionDesign,
  captionAnchorStyle,
  captionBoxStyle,
  captionTextStyle,
  easeOut,
  popScale,
} from './caption-design';

export type CaptionWord = { text: string; start: number; end: number };

export type RenderCaption = {
  id?: string;
  text: string;
  start: number;
  end: number;
  design?: CaptionDesign;
  // Per-word timings (absolute timeline seconds), e.g. from Whisper. Drive karaoke/typewriter.
  words?: CaptionWord[];
};

export function captionFrame(time: number, fps = 30): number {
  const rate = Number.isFinite(fps) && fps > 1 ? fps : 30;
  return Math.round(time * rate);
}

export function isCaptionActive(cap: RenderCaption, time: number, fps = 30): boolean {
  const frame = captionFrame(time, fps);
  return frame >= captionFrame(cap.start, fps) && frame < captionFrame(cap.end, fps);
}

const num = (v: unknown, d: number) => (Number.isFinite(Number(v)) ? Number(v) : d);

// Box-level intro animation (pop/fade/slide). Word-level effects return {} here and are handled
// by the token renderer below. outH is needed so slide distance scales with the output.
function introStyle(design: CaptionDesign, local: number, outH: number): CSSProperties {
  const a = design.animation;
  if (!a || a === 'none' || a === 'typewriter' || a === 'karaoke') return {};
  const inDur = 0.3 / num(design.animationSpeed, 1);
  const p = Math.max(0, Math.min(1, local / inDur));
  if (a === 'fade') return { opacity: p };
  if (a === 'slide') return { opacity: p, transform: `translateY(${(1 - easeOut(p)) * outH * 0.03}px)` };
  // pop: overshoot scale + quick fade
  return { opacity: Math.min(1, p * 1.4), transform: `scale(${popScale(p)})` };
}

// Split text into reveal/highlight units. Uses per-word timings when present (Whisper); otherwise
// keeps ASCII words whole + CJK per character, with even timing across the caption.
function tokenize(cap: RenderCaption): CaptionWord[] {
  if (cap.words && cap.words.length) return cap.words;
  const units: string[] = [];
  const text = cap.text;
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch.charCodeAt(0) < 128 && ch.trim()) {
      let word = '';
      while (i < text.length && text[i].charCodeAt(0) < 128 && text[i].trim()) word += text[i++];
      units.push(word);
    } else {
      units.push(ch);
      i++;
    }
  }
  const dur = Math.max(0.01, cap.end - cap.start);
  return units.map((u, idx) => ({
    text: u,
    start: cap.start + (dur * idx) / units.length,
    end: cap.start + (dur * (idx + 1)) / units.length,
  }));
}

// Renders the caption layer at the OUTPUT resolution (outW x outH). The preview scales this
// down with a CSS transform; the export screenshots it 1:1. Same component both places.
export function CaptionLayer({
  outW,
  outH,
  captions,
  time,
  fps = 30,
  hiddenCaptionIds = [],
}: {
  outW: number;
  outH: number;
  captions: RenderCaption[];
  time: number;
  fps?: number;
  hiddenCaptionIds?: string[];
}) {
  const active = useMemo(() => {
    const hidden = new Set(hiddenCaptionIds);
    const a = captions.filter((c) => c.text?.trim() && !hidden.has(c.id || '') && isCaptionActive(c, time, fps));
    return a.length ? a[a.length - 1] : null; // last active wins (mirrors the old canvas behavior)
  }, [captions, fps, hiddenCaptionIds, time]);

  const design: CaptionDesign = active?.design || {};
  const anim = design.animation;
  const wordLevel = anim === 'typewriter' || anim === 'karaoke';

  const tokens = useMemo(() => (active && wordLevel ? tokenize(active) : null), [active, wordLevel]);

  if (!active) {
    return (
      <div style={{ position: 'relative', width: outW, height: outH, overflow: 'hidden', pointerEvents: 'none' }}>
        <style>{CAPTION_FONT_FACE_CSS}</style>
      </div>
    );
  }

  const local = time - active.start;
  const boxStyle: CSSProperties = { ...captionBoxStyle(design, outH), ...introStyle(design, local, outH) };
  const textStyle = captionTextStyle(design, outH);
  const highlight = design.highlightColor || '#ffe14d';
  const hlScale = num(design.highlightScale, 1.12);

  let content: React.ReactNode;
  if (tokens) {
    content = (
      <p style={textStyle}>
        {tokens.map((tok, i) => {
          const spoken = time >= tok.end;
          const activeWord = time >= tok.start && time < tok.end;
          if (anim === 'typewriter') {
            // reveal: hide tokens not yet reached (keep layout stable via visibility)
            const shown = time >= tok.start;
            return (
              <span key={i} style={{ visibility: shown ? 'visible' : 'hidden' }}>
                {tok.text}
              </span>
            );
          }
          // karaoke: dim upcoming words, highlight the one being spoken
          return (
            <span
              key={i}
              style={{
                display: 'inline-block',
                color: activeWord ? highlight : undefined,
                opacity: spoken || activeWord ? 1 : 0.45,
                transform: activeWord ? `scale(${hlScale})` : undefined,
                transition: 'none',
              }}
            >
              {tok.text}
            </span>
          );
        })}
      </p>
    );
  } else {
    content = <p style={textStyle}>{active.text}</p>;
  }

  return (
    <div style={{ position: 'relative', width: outW, height: outH, overflow: 'hidden', pointerEvents: 'none' }}>
      <style>{CAPTION_FONT_FACE_CSS}</style>
      <div style={captionAnchorStyle(design, outH)}>
        <div style={boxStyle}>{content}</div>
      </div>
    </div>
  );
}
