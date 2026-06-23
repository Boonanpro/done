// Single source of truth for how a caption looks. BOTH the live preview overlay and the
// server-side export (Playwright screenshots the /caption-frame route) render through the
// helpers here, at the OUTPUT resolution, so the timeline preview equals the burned-in video
// pixel-for-pixel. No ffmpeg/libass styling is involved for designed captions.

import type { CSSProperties } from 'react';

export type CaptionFontId =
  | 'noto-sans'
  | 'dela-gothic'
  | 'zen-maru'
  | 'reggae'
  | 'mplus-rounded'
  | 'rocknroll';

// Registry of the bundled OFL fonts (all commercial / video-burn-in OK). `css` is the
// font-family value; `weight` is what we actually request (display faces are single-weight).
export const CAPTION_FONTS: Record<CaptionFontId, { label: string; css: string; weight: number }> = {
  'noto-sans':     { label: '標準',     css: '"NotoSansJP"',    weight: 900 },
  'dela-gothic':   { label: '極太',     css: '"DelaGothicOne"', weight: 400 },
  'zen-maru':      { label: '角丸',     css: '"ZenMaruGothic"', weight: 900 },
  'reggae':        { label: 'レゲエ',   css: '"ReggaeOne"',     weight: 400 },
  'mplus-rounded': { label: '丸ポップ', css: '"MPLUSRounded"',  weight: 800 },
  'rocknroll':     { label: 'ロック',   css: '"RocknRollOne"',  weight: 400 },
};

// [cssFamily, url, weight] for every bundled face. FULL .ttf files (not unicode-range subsets —
// those drop uncommon kanji, leaving captions blank). Used to load fonts deterministically via
// the FontFace JS API (the export route MUST await these before screenshotting; @font-face in
// an injected <style> doesn't register reliably in document.fonts in time).
export const CAPTION_FONT_FILES: ReadonlyArray<[string, string, string]> = [
  ['NotoSansJP', '/fonts/NotoSansJP.ttf', '100 900'],
  ['DelaGothicOne', '/fonts/DelaGothicOne-Regular.ttf', '400'],
  ['ZenMaruGothic', '/fonts/ZenMaruGothic-Black.ttf', '900'],
  ['ReggaeOne', '/fonts/ReggaeOne-Regular.ttf', '400'],
  ['MPLUSRounded', '/fonts/MPLUSRounded1c-ExtraBold.ttf', '800'],
  ['RocknRollOne', '/fonts/RocknRollOne-Regular.ttf', '400'],
];

// @font-face for every bundled file. Emitted as a <style> by CaptionLayer so it works both
// inside the editor (no global-CSS constraint) and on the standalone /caption-frame route.
export const CAPTION_FONT_FACE_CSS = `
@font-face{font-family:'NotoSansJP';font-weight:100 900;src:url('/fonts/NotoSansJP.ttf') format('truetype');font-display:block;}
@font-face{font-family:'DelaGothicOne';src:url('/fonts/DelaGothicOne-Regular.ttf') format('truetype');font-display:block;}
@font-face{font-family:'ZenMaruGothic';font-weight:900;src:url('/fonts/ZenMaruGothic-Black.ttf') format('truetype');font-display:block;}
@font-face{font-family:'ReggaeOne';src:url('/fonts/ReggaeOne-Regular.ttf') format('truetype');font-display:block;}
@font-face{font-family:'MPLUSRounded';font-weight:800;src:url('/fonts/MPLUSRounded1c-ExtraBold.ttf') format('truetype');font-display:block;}
@font-face{font-family:'RocknRollOne';src:url('/fonts/RocknRollOne-Regular.ttf') format('truetype');font-display:block;}
`;

// Designed caption look. All fields optional; an empty design renders as a clean white
// Noto-Sans caption with a black outline (a sane default, not the old plain Yu Gothic).
export type CaptionDesign = {
  font?: CaptionFontId;
  color?: string;             // text fill (ignored when gradient is set)
  gradient?: [string, string];// vertical gradient fill (top, bottom)
  outlineColor?: string;
  outlineWidth?: number;      // multiplier of the default stroke (1 = default, 0 = none)
  fontSize?: number;          // multiplier of the base size (base = outH * 0.052)
  position?: 'bottom' | 'center' | 'top';
  // Background box behind the text (the modern "telop bar" look). Absent = no box.
  bg?: { color?: string; opacity?: number; radius?: number; padX?: number; padY?: number };
  // Soft drop shadow on the whole caption block.
  shadow?: { color?: string; blur?: number; dx?: number; dy?: number };
  letterSpacing?: number;     // multiplier of fontSize (0.02 = subtle tracking)
};

const num = (v: unknown, d: number) => (Number.isFinite(Number(v)) ? Number(v) : d);

// Vertical placement of the caption block within the frame.
export function captionAnchorStyle(design: CaptionDesign, outH: number): CSSProperties {
  const pos = design.position || 'bottom';
  const margin = Math.round(outH * 0.07);
  return {
    position: 'absolute',
    left: 0,
    right: 0,
    display: 'flex',
    justifyContent: 'center',
    ...(pos === 'top'
      ? { top: margin, alignItems: 'flex-start' }
      : pos === 'center'
        ? { top: 0, bottom: 0, alignItems: 'center' }
        : { bottom: margin, alignItems: 'flex-end' }),
  };
}

// The caption "block" — an inline box that may carry the background bar + drop shadow.
export function captionBoxStyle(design: CaptionDesign, outH: number): CSSProperties {
  const base = outH * 0.052;
  const fs = base * num(design.fontSize, 1);
  const style: CSSProperties = {
    maxWidth: '88%',
    textAlign: 'center',
    lineHeight: 1.28,
    boxSizing: 'border-box',
  };
  if (design.bg) {
    const op = num(design.bg.opacity, 1);
    style.background = hexToRgba(design.bg.color || '#000000', op);
    style.borderRadius = Math.round(fs * num(design.bg.radius, 0.18));
    style.padding = `${Math.round(fs * num(design.bg.padY, 0.16))}px ${Math.round(fs * num(design.bg.padX, 0.42))}px`;
  }
  if (design.shadow) {
    const s = design.shadow;
    style.filter = `drop-shadow(${num(s.dx, 0)}px ${num(s.dy, Math.round(fs * 0.06))}px ${num(s.blur, Math.round(fs * 0.12))}px ${s.color || 'rgba(0,0,0,0.55)'})`;
  }
  return style;
}

// The text itself — font, fill (solid or gradient), outline (stroke painted behind the fill).
export function captionTextStyle(design: CaptionDesign, outH: number): CSSProperties {
  const base = outH * 0.052;
  const fs = base * num(design.fontSize, 1);
  const fontDef = CAPTION_FONTS[design.font || 'noto-sans'];
  const strokeW = fs * 0.085 * num(design.outlineWidth, 1);
  const style: CSSProperties = {
    margin: 0,
    fontFamily: `${fontDef.css}, "Yu Gothic UI", sans-serif`,
    fontWeight: fontDef.weight,
    fontSize: `${Math.round(fs)}px`,
    letterSpacing: `${(num(design.letterSpacing, 0) * fs).toFixed(2)}px`,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    // Stroke painted behind the fill = clean outline that doesn't eat the glyph.
    WebkitTextStroke: strokeW > 0.1 ? `${strokeW.toFixed(2)}px ${design.outlineColor || '#000000'}` : undefined,
    paintOrder: 'stroke fill',
  } as CSSProperties;
  if (design.gradient) {
    style.backgroundImage = `linear-gradient(180deg, ${design.gradient[0]}, ${design.gradient[1]})`;
    (style as Record<string, unknown>).WebkitBackgroundClip = 'text';
    (style as Record<string, unknown>).backgroundClip = 'text';
    style.color = 'transparent';
  } else {
    style.color = design.color || '#ffffff';
  }
  return style;
}

function hexToRgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${Math.max(0, Math.min(1, alpha))})`;
}
