import { createContext } from 'react';
import type { CaptionDesign } from './caption-design';

type Span = NonNullable<CaptionDesign['colorSpans']>[number];
export type WordRange = Pick<Span, 's' | 'e'>;
export type WordLook = Omit<Span, 's' | 'e'>;
const attributes = ['color', 'scale', 'font', 'bold', 'outlineColor', 'outlineWidth', 'outlineOpacity'] as const;

export function styleWords(spans: Span[] = [], range: WordRange, patch: WordLook): Span[] {
  const cuts = Array.from(new Set([range.s, range.e, ...spans.flatMap(sp => [sp.s, sp.e])])).sort((a, b) => a - b);
  const result: Span[] = [];
  const topFirst = [...spans].reverse();
  for (let i = 1; i < cuts.length; i++) {
    const s = cuts[i - 1], e = cuts[i];
    const old = topFirst.find(sp => sp.s <= s && s < sp.e);
    const look = { ...old, ...(range.s <= s && s < range.e ? patch : {}), s, e };
    if (!attributes.some(key => look[key] != null)) continue;
    const last = result[result.length - 1];
    if (last && last.e === s && attributes.every(key => last[key] === look[key])) last.e = e;
    else result.push(look);
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

export type CaptionEdit = {
  id: string;
  point: { x: number; y: number };
  range: WordRange | null;
  onText: (text: string) => void;
  onRange: (range: WordRange) => void;
  onExit: () => void;
};
export const CaptionEditContext = createContext<CaptionEdit | null>(null);
