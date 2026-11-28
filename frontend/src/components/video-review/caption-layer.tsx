'use client';

import { useContext, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { CaptionEditContext, type CaptionEdit } from './caption-word-edit';
import { HEADING_FONTS, loadHeadingKit } from './adobe-fonts';
import { revealTokens } from './caption-reveal';
import type { CSSProperties } from 'react';
import {
  CAPTION_FONT_FACE_CSS,
  type CaptionDesign, type CaptionSpan, captionFont,
  captionAnchorStyle,
  captionBoxStyle,
  captionFontPx, captionShadowFilter, captionShadowPerRun,
  captionTextStyle, captionStrokeColor, outlinePercent,
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

// Split text into reveal/highlight units (caption-reveal.ts). typewriter never reveals one
// character at a time: whole at once, or by the parts written in words.
function tokenize(cap: RenderCaption, anim: 'typewriter' | 'karaoke'): CaptionWord[] {
  return revealTokens(cap, anim);
}

type ColorSpan = CaptionSpan;

// 範囲色: idx を含む最後のスパンが勝つ
function spanAt(spans: ColorSpan[] | undefined, idx: number): ColorSpan | undefined {
  if (!spans) return undefined;
  for (let i = spans.length - 1; i >= 0; i--) {
    const sp = spans[i];
    if (idx >= sp.s && idx < sp.e) return sp;
  }
  return undefined;
}
// 範囲の大きさ: 行の他の文字に対する倍率（強調の言葉だけ大きく）
// shadow: 言葉ごとに影を描く時の、この字幕の影（sp に影が無い文字に使う）
type RunShadow = { base?: string; fs: number };
function spanStyle(sp: ColorSpan | undefined, shadow?: RunShadow): CSSProperties | undefined {
  const runFilter = shadow ? (sp?.shadow ? captionShadowFilter(sp.shadow, shadow.fs) : shadow.base) : undefined;
  if (!sp) return runFilter ? { filter: runFilter } : undefined;
  const st: CSSProperties = {};
  if (runFilter) st.filter = runFilter;
  if (sp.color) { st.color = sp.color; st.WebkitTextFillColor = sp.color; }
  if (sp.font) {
    const font = captionFont(sp.font);
    st.fontFamily = font.css + ', sans-serif';
    st.fontWeight = font.weight;
  }
  if (sp.bold != null) st.fontWeight = sp.bold ? 900 : 400;
  if (sp.outlineWidth != null) st.WebkitTextStrokeWidth = (0.085 * sp.outlineWidth) + 'em';
  if (sp.outlineColor || sp.outlineOpacity != null) {
    Object.assign(st, {
      ...(sp.outlineColor ? { '--caption-outline-color': sp.outlineColor } : {}),
      ...(sp.outlineOpacity != null ? { '--caption-outline-percent': outlinePercent(sp.outlineOpacity) } : {}),
      WebkitTextStrokeColor: captionStrokeColor,
    });
  }
  const sc = Number(sp.scale);
  if (Number.isFinite(sc) && sc >= 0 && sc !== 1) st.fontSize = `${sc}em`;
  return st;
}

// テキストをスパン境界で分割し、色付き区間を <span> で包む。gradient 使用時は
// WebkitTextFillColor が transparent になっているため両方上書きする。
function textRuns(text: string, spans: ColorSpan[] = [], offset = 0, shadow?: RunShadow) {
  const limit = offset + text.length;
  const cuts = new Set([offset, limit]);
  for (const span of spans) {
    if (offset < span.s && span.s < limit) cuts.add(span.s);
    if (offset < span.e && span.e < limit) cuts.add(span.e);
  }
  const points = [...cuts].sort((a, b) => a - b);
  return points.slice(0, -1).map((start, i) => ({
    start, text: text.slice(start - offset, points[i + 1] - offset), style: spanStyle(spanAt(spans, start), shadow),
  }));
}

function renderSpanned(text: string, spans?: ColorSpan[], offset = 0, highlight?: string, shadow?: RunShadow) {
  if (!spans?.length) return text;
  return textRuns(text, spans, offset, shadow).map(run =>
    run.style ? <span key={run.start} style={highlight ? { ...run.style, color: highlight, WebkitTextFillColor: highlight } : run.style}>{run.text}</span> : run.text);
}

function offsets(el: HTMLElement) {
  const sel = window.getSelection();
  if (!sel?.rangeCount || !el.contains(sel.anchorNode) || !el.contains(sel.focusNode)) return null;
  const offset = (node: Node, n: number) => {
    const r = document.createRange();
    r.selectNodeContents(el);
    r.setEnd(node, n);
    return r.toString().length;
  };
  return [offset(sel.anchorNode!, sel.anchorOffset), offset(sel.focusNode!, sel.focusOffset)] as const;
}

function textPoint(el: HTMLElement, offset: number): [Node, number] {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const length = node.textContent?.length ?? 0;
    if (offset <= length) return [node, offset];
    offset -= length;
  }
  return [el, el.childNodes.length];
}

// The browser owns the live DOM (and IME composition). Repaint style runs on a
// committed change, retaining both ends of a backwards or forwards selection.
function EditableCaption({ cap, style, edit, shadow }: { cap: RenderCaption; style: CSSProperties; edit: CaptionEdit; shadow?: RunShadow }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const composing = useRef(false);
  const point = useRef(edit.point);
  const pendingCaret = useRef<number | null>(null);
  useLayoutEffect(() => {
    const el = ref.current!;
    if (composing.current) return;
    const caret = pendingCaret.current;
    pendingCaret.current = null;
    const selection = caret == null ? offsets(el) : [caret, caret];
    const children: Node[] = textRuns(cap.text, cap.design?.colorSpans, 0, shadow).map(run => {
      if (!run.style) return document.createTextNode(run.text);
      const span = document.createElement('span');
      span.textContent = run.text;
      Object.assign(span.style, run.style);
      for (const [name, value] of Object.entries(run.style)) {
        if (name.startsWith('--')) span.style.setProperty(name, String(value));
      }
      return span;
    });
    // A trailing line break needs a caret stop on the empty final line.
    if (cap.text.endsWith('\n')) children.push(document.createElement('br'));
    if (caret == null && el.childNodes.length === children.length && children.every((node, i) => node.isEqualNode(el.childNodes[i]))) return;
    el.replaceChildren(...children);
    if (selection && document.activeElement === el) {
      window.getSelection()?.setBaseAndExtent(...textPoint(el, selection[0]), ...textPoint(el, selection[1]));
    }
  }, [cap.text, cap.design?.colorSpans, shadow?.base, shadow?.fs]);
  useLayoutEffect(() => {
    const el = ref.current!;
    el.focus({ preventScroll: true });
    const r = document.caretRangeFromPoint?.(point.current.x, point.current.y);
    if (r && el.contains(r.startContainer)) {
      window.getSelection()?.collapse(r.startContainer, r.startOffset);
    }
  }, []);
  useLayoutEffect(() => {
    // Keep the chosen letters marked when focus moves to an inspector control.
    if (!edit.range || !window.CSS?.highlights || !window.Highlight) return;
    const el = ref.current!;
    const r = document.createRange();
    r.setStart(...textPoint(el, edit.range.s));
    r.setEnd(...textPoint(el, edit.range.e));
    CSS.highlights.set('caption-selection', new Highlight(r));
    return () => { CSS.highlights.delete('caption-selection'); };
  }, [edit.range, cap.text, cap.design?.colorSpans]);
  useEffect(() => {
    const el = ref.current!;
    const replaceSelection = (text: string) => {
      const ends = offsets(el);
      if (!ends) return;
      const start = Math.min(...ends), end = Math.max(...ends);
      const caret = start + text.length;
      pendingCaret.current = caret;
      edit.onText(cap.text.slice(0, start) + text + cap.text.slice(end));
      edit.onRange({ s: caret, e: caret });
    };
    // Native editable paragraphs add a second newline as a caret placeholder
    // after Enter. Store the authored newline exactly once, including on mobile.
    const beforeInput = (e: InputEvent) => {
      if (e.isComposing || !['insertParagraph', 'insertLineBreak'].includes(e.inputType)) return;
      e.preventDefault();
      replaceSelection('\n');
    };
    const paste = (e: ClipboardEvent) => {
      if (!e.clipboardData) return;
      e.preventDefault();
      replaceSelection(e.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n'));
    };
    el.addEventListener('beforeinput', beforeInput);
    el.addEventListener('paste', paste);
    return () => {
      el.removeEventListener('beforeinput', beforeInput);
      el.removeEventListener('paste', paste);
    };
  }, [cap.text, edit]);
  function reportRange() {
    const el = ref.current!;
    if (document.activeElement !== el) return;
    const ends = offsets(el);
    if (ends) edit.onRange({ s: Math.min(...ends), e: Math.max(...ends) });
  }
  function commit() {
    const el = ref.current!;
    if (!composing.current) edit.onText(el.textContent || '');
    reportRange();
  }
  return <p ref={ref} contentEditable="plaintext-only" role="textbox" aria-label="テロップ本文"
    aria-multiline spellCheck={false}
    style={{ ...style, pointerEvents: 'auto', userSelect: 'text', cursor: 'text', outline: 'none', minWidth: '0.35em', minHeight: '1em', caretColor: 'currentColor' }}
    onPointerDown={e => e.stopPropagation()} onDoubleClick={e => e.stopPropagation()}
    onSelect={reportRange} onPointerUp={reportRange} onKeyUp={reportRange}
    onCompositionStart={() => { composing.current = true; }}
    onCompositionEnd={() => { composing.current = false; commit(); }} onInput={commit}
    onKeyDown={e => {
      e.stopPropagation();
      if (e.key === 'Escape' && !e.nativeEvent.isComposing) { e.preventDefault(); edit.onExit(); }
    }} />;
}

// One caption box (position/animation/karaoke). Extracted so the layer can draw EVERY
// active caption — the old "last active wins" single-pick made overlapping captions
// (e.g. a side-super lane above the subtitle lane) hide each other in the preview.
function SingleCaption({ cap, time, outW, outH }: { cap: RenderCaption; time: number; outW: number; outH: number }) {
  const design: CaptionDesign = cap.design || {};
  const edit = useContext(CaptionEditContext);
  const anim = design.animation;
  const wordLevel = anim === 'typewriter' || anim === 'karaoke';
  const tokens = useMemo(() => (wordLevel ? tokenize(cap, anim === 'karaoke' ? 'karaoke' : 'typewriter') : null), [cap, wordLevel, anim]);

  const local = time - cap.start;
  const baseBox = captionBoxStyle(design, outH);
  const intro = introStyle(design, local, outH);
  // the intro motion (pop/slide) and the design's slant both live in `transform`: keep both
  const boxStyle: CSSProperties = {
    ...baseBox,
    ...intro,
    transform: [intro.transform, baseBox.transform].filter(Boolean).join(' ') || undefined,
  };
  const textStyle = captionTextStyle(design, outH);
  const highlight = design.highlightColor || '#ffe14d';
  const hlScale = num(design.highlightScale, 1.12);
  const colorSpans = design.colorSpans;
  const runShadow: RunShadow | undefined = captionShadowPerRun(design)
    ? { base: design.shadow ? captionShadowFilter(design.shadow, captionFontPx(design, outH)) : undefined, fs: captionFontPx(design, outH) }
    : undefined;
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
  if (edit && edit.id === cap.id) {
    content = <EditableCaption cap={cap} style={textStyle} edit={edit} shadow={runShadow} />;
  } else if (tokens) {
    content = (
      <p style={textStyle}>
        {tokens.map((tok, i) => {
          const spoken = time >= tok.end;
          const activeWord = time >= tok.start && time < tok.end;
          const offset = tokenOffsets?.[i] ?? 0;
          const runs = renderSpanned(tok.text, colorSpans, offset, anim === 'karaoke' && activeWord ? highlight : undefined, runShadow);
          if (anim === 'typewriter') {
            // reveal: hide tokens not yet reached (keep layout stable via visibility)
            const shown = time >= tok.start;
            return (
              <span
                key={i}
                style={{
                  visibility: shown ? 'visible' : 'hidden',
                }}
              >
                {runs}
              </span>
            );
          }
          // karaoke: dim upcoming words, highlight the one being spoken
          const col = activeWord ? highlight : undefined;
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
              {runs}
            </span>
          );
        })}
      </p>
    );
  } else {
    content = <p style={textStyle}>{renderSpanned(cap.text, colorSpans, 0, undefined, runShadow)}</p>;
  }

  const motion = captionMotionAt(cap,time);
  return (
    <div style={{position:'absolute',inset:0,transformOrigin:'0 0',transform:`translate(${motion.x*outW}px,${motion.y*outH}px) scale(${motion.w},${motion.h})`,opacity:cap.opacity??1}}>
      <div style={captionAnchorStyle(design, outH)}>
        <div data-caption-id={cap.id || undefined} style={boxStyle}>{content}</div>
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
  const editingId = useContext(CaptionEditContext)?.id;
  const usesHeadingFont = captions.some(c => [c.design?.font, ...(c.design?.colorSpans ?? []).map(s => s.font)]
    .some(font => font && Object.hasOwn(HEADING_FONTS, font)));
  useEffect(() => {
    if (usesHeadingFont) void loadHeadingKit().catch(() => {});
  }, [usesHeadingFont]);
  // ALL active captions render, in payload (lane) order — later entries stack on top,
  // matching "every clip is visible; upper lanes in front". The old single-pick
  // (`a[a.length - 1]`, "last active wins") hid the subtitle lane whenever a
  // side-super overlapped it.
  const actives = useMemo(() => {
    const hidden = new Set(hiddenCaptionIds);
    return captions.filter(
      (c) => (c.text?.trim() || (editingId && c.id === editingId)) && !hidden.has(c.id || '') && isCaptionActive(c, time, fps),
    );
  }, [captions, fps, hiddenCaptionIds, time, editingId]);

  return (
    <div style={{ position: 'relative', width: outW, height: outH, overflow: 'hidden', pointerEvents: 'none' }}>
      <style>{CAPTION_FONT_FACE_CSS}{editingId && '::highlight(caption-selection){background-color:rgba(50,145,255,.42)}'}</style>
      {actives.map((cap, i) => (
        <SingleCaption key={cap.id || i} cap={cap} time={time} outW={outW} outH={outH} />
      ))}
    </div>
  );
}
