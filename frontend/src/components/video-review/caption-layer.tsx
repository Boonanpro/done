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
  transform_keys?: { t: number; x: number; y: number; w?: number; h?: number }[];
  opacity?: number;
};

// Same full-canvas transform as the native compositor. Pure time evaluation also
// makes backwards seeks and text edits preserve the authored movement.
export function captionMotionAt(cap: RenderCaption, time: number) {
  const keys = (cap.transform_keys || []).filter(k => [k.t,k.x,k.y].every(Number.isFinite)).slice().sort((a,b)=>a.t-b.t);
  if (!keys.length) return {x:0,y:0,w:1,h:1};
  const rel = time-cap.start;
  const last = keys[keys.length-1];
  const index = keys.findIndex(k=>k.t>rel);
  const a = rel<=keys[0].t ? keys[0] : index<0 ? last : keys[index-1];
  const b = rel<=keys[0].t ? a : index<0 ? a : keys[index];
  const f = a===b ? 0 : Math.max(0,Math.min(1,(rel-a.t)/Math.max(1e-9,b.t-a.t)));
  const mix = (p:number,q:number)=>p+(q-p)*f;
  return {x:mix(a.x,b.x),y:mix(a.y,b.y),w:mix(a.w??1,b.w??1),h:mix(a.h??1,b.h??1)};
}

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

type ColorSpan = { s: number; e: number; color: string };

// 範囲色: idx を含む最後のスパンが勝つ
function spanColorAt(spans: ColorSpan[] | undefined, idx: number): string | undefined {
  if (!spans) return undefined;
  for (let i = spans.length - 1; i >= 0; i--) {
    const sp = spans[i];
    if (idx >= sp.s && idx < sp.e) return sp.color;
  }
  return undefined;
}

// テキストをスパン境界で分割し、色付き区間を <span> で包む。gradient 使用時は
// WebkitTextFillColor が transparent になっているため両方上書きする。
function renderSpanned(text: string, spans?: ColorSpan[]): React.ReactNode {
  if (!spans || !spans.length) return text;
  const cuts = new Set<number>([0, text.length]);
  for (const sp of spans) {
    cuts.add(Math.max(0, Math.min(text.length, sp.s)));
    cuts.add(Math.max(0, Math.min(text.length, sp.e)));
  }
  const pts = [...cuts].sort((a, b) => a - b);
  const segs: React.ReactNode[] = [];
  for (let i = 0; i + 1 < pts.length; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (a >= b) continue;
    const col = spanColorAt(spans, a);
    segs.push(
      col ? (
        <span key={a} style={{ color: col, WebkitTextFillColor: col }}>
          {text.slice(a, b)}
        </span>
      ) : (
        text.slice(a, b)
      ),
    );
  }
  return segs;
}

// One caption box (position/animation/karaoke). Extracted so the layer can draw EVERY
// active caption — the old "last active wins" single-pick made overlapping captions
// (e.g. a side-super lane above the subtitle lane) hide each other in the preview.
function SingleCaption({ cap, time, outW, outH }: { cap: RenderCaption; time: number; outW: number; outH: number }) {
  const design: CaptionDesign = cap.design || {};
  const anim = design.animation;
  const wordLevel = anim === 'typewriter' || anim === 'karaoke';
  const tokens = useMemo(() => (wordLevel ? tokenize(cap) : null), [cap, wordLevel]);

  const local = time - cap.start;
  const boxStyle: CSSProperties = { ...captionBoxStyle(design, outH), ...introStyle(design, local, outH) };
  const textStyle = captionTextStyle(design, outH);
  const highlight = design.highlightColor || '#ffe14d';
  const hlScale = num(design.highlightScale, 1.12);
  const colorSpans = design.colorSpans;
  // トークン先頭の文字インデックス（範囲色をトークン単位に対応付ける）。Whisper 語は
  // 空白がトークンに含まれないことがあるので progressive indexOf で照合する
  const tokenOffsets = useMemo(() => {
    if (!tokens) return null;
    let cur = 0;
    return tokens.map((t) => {
      const at = cap.text.indexOf(t.text, cur);
      const s = at >= 0 ? at : cur;
      cur = s + t.text.length;
      return s;
    });
  }, [tokens, cap.text]);

  let content: React.ReactNode;
  if (tokens) {
    content = (
      <p style={textStyle}>
        {tokens.map((tok, i) => {
          const spoken = time >= tok.end;
          const activeWord = time >= tok.start && time < tok.end;
          const spanCol = spanColorAt(colorSpans, tokenOffsets ? tokenOffsets[i] : 0);
          if (anim === 'typewriter') {
            // reveal: hide tokens not yet reached (keep layout stable via visibility)
            const shown = time >= tok.start;
            return (
              <span
                key={i}
                style={{
                  visibility: shown ? 'visible' : 'hidden',
                  color: spanCol,
                  WebkitTextFillColor: spanCol,
                }}
              >
                {tok.text}
              </span>
            );
          }
          // karaoke: dim upcoming words, highlight the one being spoken
          const col = activeWord ? highlight : spanCol;
          return (
            <span
              key={i}
              style={{
                display: 'inline-block',
                color: col,
                WebkitTextFillColor: col,
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
    content = <p style={textStyle}>{renderSpanned(cap.text, colorSpans)}</p>;
  }

  const motion = captionMotionAt(cap,time);
  return (
    <div style={{position:'absolute',inset:0,transformOrigin:'0 0',transform:`translate(${motion.x*outW}px,${motion.y*outH}px) scale(${motion.w},${motion.h})`,opacity:cap.opacity??1}}>
      <div style={captionAnchorStyle(design, outH)}>
        <div style={boxStyle}>{content}</div>
      </div>
    </div>
  );
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
  // ALL active captions render, in payload (lane) order — later entries stack on top,
  // matching "every clip is visible; upper lanes in front". The old single-pick
  // (`a[a.length - 1]`, "last active wins") hid the subtitle lane whenever a
  // side-super overlapped it.
  const actives = useMemo(() => {
    const hidden = new Set(hiddenCaptionIds);
    return captions.filter(
      (c) => c.text?.trim() && !hidden.has(c.id || '') && isCaptionActive(c, time, fps),
    );
  }, [captions, fps, hiddenCaptionIds, time]);

  return (
    <div style={{ position: 'relative', width: outW, height: outH, overflow: 'hidden', pointerEvents: 'none' }}>
      <style>{CAPTION_FONT_FACE_CSS}</style>
      {actives.map((cap, i) => (
        <SingleCaption key={cap.id || i} cap={cap} time={time} outW={outW} outH={outH} />
      ))}
    </div>
  );
}
