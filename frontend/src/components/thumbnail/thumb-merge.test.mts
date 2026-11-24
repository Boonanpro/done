// 試し: node --experimental-strip-types frontend/src/components/thumbnail/thumb-merge.test.mts
import { mergeThumbDocs } from './thumb-doc.ts';
const P = (id: string, x = 0, extra: any = {}) => ({ id, type: 'image', src: id, x, y: 0, w: 1, h: 1, ...extra });
const doc = (parts: any[], extra: any = {}) => ({ width: 10, height: 10, parts, ...extra });
let fail = 0;
const eq = (name: string, a: unknown, b: unknown) => { const ok = JSON.stringify(a) === JSON.stringify(b); if (!ok) fail++; console.log(ok ? 'PASS' : 'FAIL', name, ok ? '' : JSON.stringify(a)); };
// 実際に起きた事: ダンが card の絵を差し替え、本人は別の部品を動かしていた → 両方残る
const base = doc([P('bg'), P('card'), P('t1', 5)]);
const theirs = doc([P('bg'), P('card', 0, { src: 'card2' }), P('t1', 5)], { rev: 2 });
const ours = doc([P('bg'), P('card'), P('t1', 9)]);
const m = mergeThumbDocs(base as any, ours as any, theirs as any);
eq('ダンの絵の差し替えが残る', (m.parts[1] as any).src, 'card2');
eq('本人の動かしも残る', (m.parts[2] as any).x, 9);
// 同じ部品を両方が変えた → 手元（本人）
const m2 = mergeThumbDocs(base as any, doc([P('bg'), P('card', 3), P('t1', 5)]) as any, theirs as any);
eq('同じ部品は本人が勝つ', [(m2.parts[1] as any).x, (m2.parts[1] as any).src], [3, 'card']);
// ダンが足した部品・本人が消した部品
const m3 = mergeThumbDocs(base as any, doc([P('bg'), P('t1', 5)]) as any, doc([P('bg'), P('card'), P('new'), P('t1', 5)]) as any);
eq('本人が消した物は消え、ダンが足した物は同じ所に', m3.parts.map((p: any) => p.id), ['bg', 'new', 't1']);
// 本人が並びを変えた
const m4 = mergeThumbDocs(base as any, doc([P('t1', 5), P('bg'), P('card')]) as any, doc([P('bg'), P('card', 0, { src: 'c2' }), P('t1', 5)]) as any);
eq('本人の並び＋ダンの中身', m4.parts.map((p: any) => p.id + ':' + p.src), ['t1:t1', 'bg:bg', 'card:c2']);
// 元に戻す: 自分の1手（t1 を 5→9）だけを戻し、その後のダンの直しは残す
const before = doc([P('bg'), P('card'), P('t1', 5)]);
const after = doc([P('bg'), P('card'), P('t1', 9)]);
const now = doc([P('bg'), P('card', 0, { src: 'card2' }), P('t1', 9)]);
const u = mergeThumbDocs(after as any, before as any, now as any);
eq('元に戻すはダンの直しを巻き戻さない', u.parts.map((p: any) => `${p.id}:${p.x}:${p.src}`), ['bg:0:bg', 'card:0:card2', 't1:5:t1']);
process.exit(fail ? 1 : 0);
