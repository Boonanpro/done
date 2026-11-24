// 試し: node --experimental-strip-types frontend/src/components/thumbnail/thumb-order.test.mts
import { reorderParts, stepParts, mergeThumbDocs } from './thumb-doc.ts';
const P = (id: string) => ({ id });
let fail = 0;
const eq = (name: string, a: unknown, b: unknown) => { const ok = JSON.stringify(a) === JSON.stringify(b); if (!ok) fail++; console.log(ok ? 'PASS' : 'FAIL', name, ok ? '' : JSON.stringify(a)); };
const ids = (xs: { id: string }[]) => xs.map((x) => x.id).join('');
// parts は奥→手前。一覧（上が手前）は e d c b a
const parts = ['a', 'b', 'c', 'd', 'e'].map(P);
eq('一番下の a を一番上へ', ids(reorderParts(parts, ['a'], 0)), 'bcdea');
eq('一番上の e を一番下へ', ids(reorderParts(parts, ['e'], 5)), 'eabcd');
eq('d を c と b の間へ（一覧の3番目の前）', ids(reorderParts(parts, ['d'], 3)), 'abdce');
eq('同じ所に落とすと変わらない', ids(reorderParts(parts, ['c'], 2)), 'abcde');
eq('離れた2つ（e と b）をまとめて一番下へ・互いの前後は保つ', ids(reorderParts(parts, ['e', 'b'], 5)), 'beacd');
eq('1つ前へ', ids(stepParts(parts, ['b'], 'up')), 'acbde');
eq('一番手前は前へ動かない', ids(stepParts(parts, ['e'], 'up')), 'abcde');
eq('1つ後ろへ（複数）', ids(stepParts(parts, ['c', 'e'], 'down')), 'acbed');
eq('一番前へ（複数）', ids(stepParts(parts, ['a', 'c'], 'front')), 'bdeac');
eq('一番後ろへ', ids(stepParts(parts, ['d'], 'back')), 'dabce');
// 並べ替えを元に戻す（その後にダンが中身を変えていても並びだけ戻る）
const doc = (ps: any[]) => ({ width: 1, height: 1, parts: ps });
const before = doc(parts), after = doc(reorderParts(parts, ['a'], 0));
const now = doc(after.parts.map((p: any) => (p.id === 'c' ? { ...p, src: 'dan' } : p)));
const u = mergeThumbDocs(after as any, before as any, now as any);
eq('並べ替えの取り消しはダンの直しを残す', u.parts.map((p: any) => p.id + (p.src ? ':' + p.src : '')), ['a', 'b', 'c:dan', 'd', 'e']);
process.exit(fail ? 1 : 0);
