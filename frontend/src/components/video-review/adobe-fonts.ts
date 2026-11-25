// Adobe Fonts selections with redistributable OFL releases. The same PostScript name
// selects the installed AE face and the browser face used in captions and export.
export const ADOBE_FONTS = {
  'biz-udp': { label: 'BIZ UDPゴシック', face: 'BIZUDPGothic-Bold', weight: 700 },
  'zen-kaku': { label: 'ZEN角ゴシック New', face: 'ZenKakuGothicNew-Bold', weight: 700 },
  'klee': { label: 'クレー One', face: 'KleeOne-SemiBold', weight: 600 },
  'kaisei': { label: '解星 特ミン', face: 'KaiseiTokumin-ExtraBold', weight: 800 },
  'yuji': { label: '佑字 肅', face: 'YujiSyuku-Regular', weight: 400 },
} as const;

export function adobeFontUrl(face: string) {
  return `/fonts/adobe-selection/${face}.woff2`;
}
export const ADOBE_FONT_CSS = Object.values(ADOBE_FONTS).map(f =>
  `@font-face{font-family:'${f.face}';font-weight:${f.weight};src:url('${adobeFontUrl(f.face)}') format('woff2');font-display:swap;}`
).join('\n');
