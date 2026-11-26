// The PostScript face is sent to After Effects; the web family is from the owner's Adobe kit.
export const HEADING_FONTS = {
  'kozuka-heavy': { label: '小塚ゴシック H', face: 'KozGoPr6N-Heavy', web: 'kozuka-gothic-pr6n', weight: 900 },
  'neokuro': { label: 'ネオクロ', face: 'Neokuro-Regular', web: 'neokuro', weight: 900 },
  'ryo-display': { label: 'りょう Display EB', face: 'RyoDispPlusN-ExtraBold', web: 'ryo-display-plusn', weight: 800 },
  'shuei-ymincho': { label: '秀英横太明朝 B', face: 'DNPShueiYMinStd-B', web: 'dnp-shuei-ymincho-std', weight: 600 },
  'v7-maru': { label: 'VDL Ｖ７丸ゴシック EB', face: 'VDL-V7MaruGothic-ExtraBold', web: 'vdl-v7marugothic', weight: 800 },
} as const;

export const BUNDLED_ADOBE_FONTS = {
  'biz-udp': { label: 'BIZ UDPゴシック', face: 'BIZUDPGothic-Bold', weight: 700 },
  'zen-kaku': { label: 'ZEN角ゴシック New', face: 'ZenKakuGothicNew-Bold', weight: 700 },
  'kaisei': { label: '解星 特ミン', face: 'KaiseiTokumin-ExtraBold', weight: 800 },
  // Keep the original faces for previously authored captions.
  'klee': { label: 'クレー One', face: 'KleeOne-SemiBold', weight: 600 },
  'yuji': { label: '佑字 肅', face: 'YujiSyuku-Regular', weight: 400 },
} as const;

export const ADOBE_FONTS = { ...HEADING_FONTS, ...BUNDLED_ADOBE_FONTS };
export const isRetiredFont = (id: string) => id === 'klee' || id === 'yuji';
export function adobeFontUrl(face: string) {
  return `/fonts/adobe-selection/${face}.woff2`;
}
export const ADOBE_FONT_CSS = Object.values(BUNDLED_ADOBE_FONTS).map(f =>
  `@font-face{font-family:'${f.face}';font-weight:${f.weight};src:url('${adobeFontUrl(f.face)}') format('woff2');font-display:swap;}`
).join('\n');

type Kit = {
  load(options: { async: boolean; active(): void; inactive(): void }): void;
  kit: { family: string; update(range: string): Promise<void> }[];
};
let kitReady: Promise<Kit> | undefined;
export function loadHeadingKit(): Promise<Kit> {
  if (kitReady) return kitReady;
  kitReady = new Promise<Kit>((resolve, reject) => {
    const script = document.createElement('script');
    const fail = () => { clearTimeout(timer); script.remove(); reject(Error('Adobe Fonts を読み込めませんでした。')); };
    const timer = setTimeout(fail, 15000);
    script.src = 'https://use.typekit.net/lwb4ygw.js';
    script.async = true;
    script.onload = () => {
      const kit = (window as Window & { Typekit?: Kit }).Typekit;
      if (!kit) return fail();
      kit.load({ async: true, active() { clearTimeout(timer); resolve(kit); }, inactive: fail });
    };
    script.onerror = fail;
    document.head.appendChild(script);
  }).catch((err) => { kitReady = undefined; throw err; });
  return kitReady;
}

// A second caption in the same export page can require characters absent from the first subset.
// Wait for the selected Adobe face to finish adding those glyphs before capturing the frame.
export async function prepareHeadingText(captions: {text: string; design?: {font?: string}}[]) {
  const ranges = new Map<string, Set<string>>();
  for (const {text, design} of captions) {
    if (!design?.font || !Object.hasOwn(HEADING_FONTS, design.font)) continue;
    const font = HEADING_FONTS[design.font as keyof typeof HEADING_FONTS];
    const chars = ranges.get(font.web) ?? new Set<string>();
    for (const char of Array.from(text)) chars.add('U+' + char.codePointAt(0)!.toString(16));
    ranges.set(font.web, chars);
  }
  if (!ranges.size) return;
  const kit = await loadHeadingKit();
  await Promise.all(Array.from(ranges, async ([family, chars]) => {
    const font = kit.kit.find(f => f.family === family);
    if (!font) throw Error(`Adobe Fonts に ${family} が見つかりません。`);
    await font.update(Array.from(chars).join(','));
  }));
  await document.fonts.ready;
}
