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
  | 'rocknroll'
  | 'mincho'
  | 'hiragino-w6'
  | 'hiragino-w8'
  | 'toppan-mincho';

// Registry of caption fonts. The first seven are the bundled OFL fonts (frontend/public/fonts).
// The last three are the owner's own fonts (macOS / Morisawa faces kept in ~/.dan/fonts, NOT in
// git — redistributing them is not allowed), served by the backend's scene font route; their
// fallbacks keep a caption readable when that file can't be loaded. `css` is the font-family
// value; `weight` is what we actually request (display faces are single-weight).
export const CAPTION_FONTS: Record<CaptionFontId, { label: string; css: string; weight: number }> = {
  'noto-sans':     { label: '標準',     css: '"NotoSansJP"',    weight: 900 },
  'dela-gothic':   { label: '極太',     css: '"DelaGothicOne"', weight: 400 },
  'zen-maru':      { label: '角丸',     css: '"ZenMaruGothic"', weight: 900 },
  'reggae':        { label: 'レゲエ',   css: '"ReggaeOne"',     weight: 400 },
  'mplus-rounded': { label: '丸ポップ', css: '"MPLUSRounded"',  weight: 800 },
  'rocknroll':     { label: 'ロック',   css: '"RocknRollOne"',  weight: 400 },
  'mincho':        { label: '明朝',     css: '"ShipporiMincho"',weight: 800 },
  'hiragino-w6':   { label: 'ヒラギノ角ゴ W6', css: '"HiraginoW6", "Hiragino Sans", "NotoSansJP"', weight: 600 },
  'hiragino-w8':   { label: 'ヒラギノ角ゴ W8', css: '"HiraginoW8", "Hiragino Sans", "NotoSansJP"', weight: 800 },
  'toppan-mincho': { label: '凸版文久見出し明朝', css: '"ToppanMidashiMincho", "ShipporiMincho"', weight: 800 },
};

// Look up a font by id, falling back to the default for anything unknown. Stored designs can
// carry ids the registry doesn't have (an agent once saved font:"Hiragino Sans"); indexing
// CAPTION_FONTS directly then crashed the whole /caption-frame export page.
export function captionFont(id: unknown): { label: string; css: string; weight: number } {
  return (typeof id === 'string' && Object.prototype.hasOwnProperty.call(CAPTION_FONTS, id))
    ? CAPTION_FONTS[id as CaptionFontId]
    : CAPTION_FONTS['noto-sans'];
}

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
  ['ShipporiMincho', '/fonts/ShipporiMincho-ExtraBold.ttf', '800'],
];

// The owner's fonts (see CAPTION_FONTS). Not bundled: fetched from the backend only when a
// caption actually uses one (they are 4-7 MB each), so the export page doesn't load them for
// every caption. Same [cssFamily, url, weight] shape as CAPTION_FONT_FILES.
const OWNER_FONT_BASE = '/api/v1/editor-assistant/scene-vendor/fonts/';
export const CAPTION_OWNER_FONT_FILES: Partial<Record<CaptionFontId, [string, string, string]>> = {
  'hiragino-w6': ['HiraginoW6', `${OWNER_FONT_BASE}HiraginoSans-W6.otf`, '600'],
  'hiragino-w8': ['HiraginoW8', `${OWNER_FONT_BASE}HiraginoSans-W8.otf`, '800'],
  'toppan-mincho': ['ToppanMidashiMincho', `${OWNER_FONT_BASE}ToppanBunkyuMidashiMincho-ExtraBold.otf`, '800'],
};

// Font files the given captions need: every bundled face plus the owner fonts they name.
export function captionFontFilesFor(designs: ReadonlyArray<CaptionDesign | undefined | null>): Array<[string, string, string]> {
  const out: Array<[string, string, string]> = [...CAPTION_FONT_FILES];
  for (const d of designs) {
    const f = d && typeof d.font === 'string' && Object.prototype.hasOwnProperty.call(CAPTION_OWNER_FONT_FILES, d.font)
      ? CAPTION_OWNER_FONT_FILES[d.font as CaptionFontId] : undefined;
    if (f && !out.includes(f)) out.push(f);
  }
  return out;
}

// Load faces via the FontFace API and add them to document.fonts (the export MUST await this
// before screenshotting). One promise per file, so later payloads reuse earlier loads. A face that
// fails or takes longer than `timeoutMs` is skipped: the caption then draws in its fallback font
// instead of vanishing or blocking the export.
const fontLoads = new Map<string, Promise<void>>();
export function loadCaptionFontFiles(files: ReadonlyArray<readonly [string, string, string]>, timeoutMs = 7000): Promise<void> {
  const fontSet = typeof document !== 'undefined' ? (document as unknown as { fonts?: FontFaceSet }).fonts : undefined;
  if (!fontSet || typeof FontFace === 'undefined') return Promise.resolve();
  return Promise.all(files.map(([family, url, weight]) => {
    let p = fontLoads.get(url);
    if (!p) {
      p = (async () => {
        const face = new FontFace(family, `url("${url}")`, { weight: String(weight) });
        await face.load();
        fontSet.add(face);
      })().catch(() => { fontLoads.delete(url); });
      fontLoads.set(url, p);
    }
    return Promise.race([p, new Promise<void>((r) => setTimeout(r, timeoutMs))]);
  })).then(() => fontSet.ready).then(() => undefined, () => undefined);
}

// @font-face for every bundled file. Emitted as a <style> by CaptionLayer so it works both
// inside the editor (no global-CSS constraint) and on the standalone /caption-frame route.
export const CAPTION_FONT_FACE_CSS = `
@font-face{font-family:'NotoSansJP';font-weight:100 900;src:url('/fonts/NotoSansJP.ttf') format('truetype');font-display:block;}
@font-face{font-family:'DelaGothicOne';src:url('/fonts/DelaGothicOne-Regular.ttf') format('truetype');font-display:block;}
@font-face{font-family:'ZenMaruGothic';font-weight:900;src:url('/fonts/ZenMaruGothic-Black.ttf') format('truetype');font-display:block;}
@font-face{font-family:'ReggaeOne';src:url('/fonts/ReggaeOne-Regular.ttf') format('truetype');font-display:block;}
@font-face{font-family:'MPLUSRounded';font-weight:800;src:url('/fonts/MPLUSRounded1c-ExtraBold.ttf') format('truetype');font-display:block;}
@font-face{font-family:'RocknRollOne';src:url('/fonts/RocknRollOne-Regular.ttf') format('truetype');font-display:block;}
@font-face{font-family:'ShipporiMincho';font-weight:800;src:url('/fonts/ShipporiMincho-ExtraBold.ttf') format('truetype');font-display:block;}
${Object.values(CAPTION_OWNER_FONT_FILES).map((f) => `@font-face{font-family:'${f![0]}';font-weight:${f![2]};src:url('${f![1]}') format('opentype');font-display:swap;}`).join('\n')}
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
  maxWidth?: number;          // fraction of frame width (default .88; manual values may exceed 1)
  textAlign?: 'left' | 'center' | 'right';
  position?: 'bottom' | 'center' | 'top';
  x?: number;                 // fine horizontal nudge, fraction of frame width  (+ = right)
  y?: number;                 // fine vertical nudge,   fraction of frame height (+ = down)
  // Background box behind the text (the modern "telop bar" look). Absent = no box.
  bg?: { color?: string; opacity?: number; radius?: number; padX?: number; padY?: number };
  // Soft drop shadow on the whole caption block.
  shadow?: { color?: string; blur?: number; dx?: number; dy?: number };
  letterSpacing?: number;     // multiplier of fontSize (0.02 = subtle tracking)
  // Slant of the whole caption block (box included), in degrees. Negative leans the tops to the
  // right like italics (-9 = the red emphasis look). Clamped to ±30.
  skew?: number;
  // M2 — motion. Box-intro animations (pop/fade/slide) need only the caption's own clock;
  // word-level effects (typewriter / karaoke) sync to per-word timings when present.
  animation?: CaptionAnimation;
  animationSpeed?: number;    // multiplier for the intro duration (default 1; bigger = faster)
  highlightColor?: string;    // karaoke: fill of the word being spoken (default = a warm yellow)
  highlightScale?: number;    // karaoke: scale bump on the active word (default 1.12)
  // 選択範囲ごとの文字色。s/e は text の UTF-16 コード単位のインデックス [s, e)。
  // ネイティブエディタの「選択範囲の色」から書かれる。後のスパンが優先。
  colorSpans?: { s: number; e: number; color: string }[];
};

// Caption motion presets. 'pop'/'fade'/'slide' are pure intro animations; 'typewriter' reveals
// text progressively; 'karaoke' highlights each word as it is spoken (uses per-word timings).
export type CaptionAnimation = 'none' | 'pop' | 'fade' | 'slide' | 'typewriter' | 'karaoke';

// easeOutBack-ish overshoot for 'pop'. p in [0,1] -> scale around 1.
export function popScale(p: number): number {
  if (p >= 1) return 1;
  const c = 1.70158;
  const x = p - 1;
  return 1 + (c + 1) * x * x * x + c * x * x;
}

export function easeOut(p: number): number {
  return 1 - Math.pow(1 - Math.max(0, Math.min(1, p)), 3);
}

const num = (v: unknown, d: number) => (Number.isFinite(Number(v)) ? Number(v) : d);

// Curated high-quality looks (font + outline + box/shadow/gradient + motion). One click sets a
// caption's whole design. Position is intentionally NOT set (presets are design-only; the user
// controls placement separately). A mix of static / animated / audio-synced styles.
export const CAPTION_DESIGN_PRESETS: ReadonlyArray<{ id: string; label: string; design: CaptionDesign }> = [
  { id: 'standard', label: '標準', design: { font: 'noto-sans', color: '#ffffff', outlineColor: '#000000', outlineWidth: 1 } },
  { id: 'variety', label: 'バラエティ黄', design: { font: 'dela-gothic', color: '#ffe000', outlineColor: '#000000', outlineWidth: 1.4, animation: 'pop' } },
  { id: 'red-pop', label: '赤ポップ', design: { font: 'dela-gothic', color: '#ff3b30', outlineColor: '#ffffff', outlineWidth: 1.4, animation: 'pop' } },
  { id: 'bar', label: '字幕バー', design: { font: 'noto-sans', color: '#ffffff', outlineColor: '#000000', outlineWidth: 0.5, bg: { color: '#000000', opacity: 0.62, radius: 0.2, padX: 0.5, padY: 0.18 }, animation: 'fade' } },
  { id: 'simple-box-black', label: 'シンプル黒箱', design: { font: 'noto-sans', color: '#ffffff', outlineColor: '#000000', outlineWidth: 0, bg: { color: '#000000', opacity: 1, radius: 0.05, padX: 0.5, padY: 0.22 } } },
  { id: 'simple-box-white', label: 'シンプル白箱', design: { font: 'noto-sans', color: '#111111', outlineColor: '#000000', outlineWidth: 0, bg: { color: '#ffffff', opacity: 1, radius: 0.05, padX: 0.5, padY: 0.22 } } },
  { id: 'karaoke', label: 'カラオケ実況', design: { font: 'mplus-rounded', color: '#ffffff', outlineColor: '#1b1b1b', outlineWidth: 1.3, animation: 'karaoke', highlightColor: '#ff3b6b', highlightScale: 1.16 } },
  { id: 'type', label: 'タイプ', design: { font: 'noto-sans', color: '#ffffff', outlineColor: '#000000', outlineWidth: 1, animation: 'typewriter' } },
  { id: 'neon', label: 'ネオン', design: { font: 'dela-gothic', color: '#19e6ff', outlineColor: '#003b46', outlineWidth: 1.2, shadow: { color: '#19e6ff', blur: 24, dy: 0 }, animation: 'fade' } },
  { id: 'mincho', label: '明朝・上品', design: { font: 'mincho', color: '#ffffff', outlineColor: '#000000', outlineWidth: 0.6, bg: { color: '#16213e', opacity: 0.52, radius: 0.1, padX: 0.5, padY: 0.2 }, animation: 'slide' } },
  { id: 'cute', label: '丸かわいい', design: { font: 'zen-maru', color: '#ff7aa8', outlineColor: '#ffffff', outlineWidth: 1.6, animation: 'pop' } },
  { id: 'rock', label: 'ロック', design: { font: 'rocknroll', gradient: ['#ffe600', '#ff8a00'], outlineColor: '#000000', outlineWidth: 1.4, animation: 'pop' } },
];

// Vertical placement of the caption block within the frame.
export function captionAnchorStyle(design: CaptionDesign, outH: number): CSSProperties {
  // y = vertical POSITION as a fraction up from the screen bottom: 0 = bottom edge, ~0.92 = near
  // the top, positive = UP. Unset captions sit in the usual lower area (0.08). x = horizontal nudge.
  const dx = design.x || 0;
  const yFrac = design.y == null ? 0.08 : Math.max(0, Math.min(0.92, design.y));
  const nudge = dx ? { transform: `translateX(${(dx * 100).toFixed(3)}%)` } : {};
  return {
    position: 'absolute',
    left: 0,
    right: 0,
    display: 'flex',
    justifyContent: 'center',
    ...nudge,
    bottom: Math.round(yFrac * outH),
    alignItems: 'flex-end',
  };
}

// The caption "block" — an inline box that may carry the background bar + drop shadow.
export function captionBoxStyle(design: CaptionDesign, outH: number): CSSProperties {
  const base = outH * 0.052;
  const fs = base * num(design.fontSize, 1);
  const maxWidth = Math.max(0.05, Math.min(2, num(design.maxWidth, 0.88)));
  const textAlign = design.textAlign === 'left' || design.textAlign === 'right' ? design.textAlign : 'center';
  const style: CSSProperties = {
    maxWidth: `${maxWidth * 100}%`,
    flexShrink: 0,
    textAlign,
    lineHeight: 1.28,
    boxSizing: 'border-box',
  };
  if (design.bg) {
    const op = num(design.bg.opacity, 1);
    style.background = hexToRgba(design.bg.color || '#000000', op);
    style.borderRadius = Math.round(fs * num(design.bg.radius, 0.18));
    style.padding = `${Math.round(fs * num(design.bg.padY, 0.16))}px ${Math.round(fs * num(design.bg.padX, 0.42))}px`;
  }
  const skew = Math.max(-30, Math.min(30, num(design.skew, 0)));
  if (skew) style.transform = `skewX(${skew}deg)`;
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
  const fontDef = captionFont(design.font);
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
