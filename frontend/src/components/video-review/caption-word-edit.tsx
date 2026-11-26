import type { CaptionDesign } from './caption-design';

type Span = NonNullable<CaptionDesign['colorSpans']>[number];
export type WordRange = Pick<Span, 's' | 'e'>;
type WordLook = Pick<Span, 'color' | 'scale'>;

export function styleWords(spans: Span[] = [], range: WordRange, patch: WordLook): Span[] {
  const cuts = Array.from(new Set([range.s, range.e, ...spans.flatMap(sp => [sp.s, sp.e])])).sort((a, b) => a - b);
  const result: Span[] = [];
  const topFirst = [...spans].reverse();
  for (let i = 1; i < cuts.length; i++) {
    const s = cuts[i - 1], e = cuts[i];
    const old = topFirst.find(sp => sp.s <= s && s < sp.e);
    const look = { color: old?.color, scale: old?.scale, ...(range.s <= s && s < range.e ? patch : {}) };
    if (!look.color && look.scale == null) continue;
    const last = result[result.length - 1];
    if (last && last.e === s && last.color === look.color && last.scale === look.scale) last.e = e;
    else result.push({ s, e, ...look });
  }
  return result;
}

// Text positions in a textarea and in colorSpans both count UTF-16 code units.
export function moveWordStyles(spans: Span[], before: string, after: string): Span[] {
  let start = 0, tail = 0;
  while (start < Math.min(before.length, after.length) && before[start] === after[start]) start++;
  while (tail < Math.min(before.length, after.length) - start && before[before.length-1-tail] === after[after.length-1-tail]) tail++;
  const oldEnd = before.length - tail, newEnd = after.length - tail, shift = newEnd - oldEnd;
  return spans.flatMap(sp => {
    if (sp.e <= start) return [sp];
    if (sp.s >= oldEnd) return [{ ...sp, s: sp.s + shift, e: sp.e + shift }];
    const s = Math.min(sp.s, start), e = sp.e >= oldEnd ? sp.e + shift : start;
    return e > s ? [{ ...sp, s, e }] : [];
  });
}

export function WordControls({ design, range, change }: {
  design: CaptionDesign; range: WordRange; change: (look: WordLook) => void;
}) {
  const span = [...(design.colorSpans || [])].reverse().find(sp => sp.s <= range.s && range.s < sp.e);
  const scale = span?.scale ?? 1;
  return <div className="flex flex-wrap items-center gap-2 text-xs">
    <label>選択文字の色 <input aria-label="選択文字の色" type="color" value={span?.color || design.color || '#ffffff'}
      className="h-6 w-8 align-middle" onChange={e => change({color: e.target.value})} /></label>
    <label>大きさ {Math.round(scale * 100)}% <input aria-label="選択文字の大きさ" type="range" min="0.5" max="2.5" step="0.05"
      className="w-20 align-middle" value={scale} onChange={e => change({scale: Number(e.target.value)})} /></label>
  </div>;
}
