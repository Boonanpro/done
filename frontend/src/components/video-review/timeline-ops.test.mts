// タイムラインの基本の編集（2026-11-25 本人）。node --experimental-strip-types で動かす。
import assert from 'node:assert/strict';
import { applyRoll, applySlide, applySlip, editPoints, insertBlock, multiTrimMoved, nudgeRoom, overwriteMoved, resolveFree, selectionRoll, splitAt, touchingNeighbor, trimRoom, withPartners } from './timeline-ops.ts';
import { rippleMoveGroups, insertPoints } from './ripple-edit.ts';
import type { RLane, RSeq } from './ripple-edit.ts';

const mk = (): { seq: RSeq; lanes: Map<string, RLane> } => {
  const seq: RSeq = {
    tracks: [
      { type: 'video', clips: [
        { id: 'A', asset_id: 'x', timeline_start: 0, timeline_end: 10, source_start: 100, source_end: 110, link_id: 'la' },
        { id: 'B', asset_id: 'x', timeline_start: 10, timeline_end: 20, source_start: 200, source_end: 210, link_id: 'lb' },
        { id: 'C', asset_id: 'x', timeline_start: 20, timeline_end: 30, source_start: 300, source_end: 310, link_id: 'lc' },
        { id: 'P1', asset_id: 'y', timeline_start: 2, timeline_end: 6, source_start: 0, source_end: 4, layer: 1 },
      ] },
      { type: 'audio', clips: [
        { id: 'a', asset_id: 'x', timeline_start: 0, timeline_end: 10, source_start: 100, source_end: 110, link_id: 'la', layer: 0 },
        { id: 'b', asset_id: 'x', timeline_start: 10, timeline_end: 20, source_start: 200, source_end: 210, link_id: 'lb', layer: 0 },
        { id: 'c', asset_id: 'x', timeline_start: 20, timeline_end: 30, source_start: 300, source_end: 310, link_id: 'lc', layer: 0 },
        { id: 'bgm', asset_id: 'm', role: 'music', timeline_start: 0, timeline_end: 30, source_start: 0, source_end: 30, layer: 1 },
      ] },
      { type: 'caption', clips: [
        { id: 'capB', text: 'B', timeline_start: 12, timeline_end: 14, source_start: 0, source_end: 0, layer: 2 },
        { id: 'capC', text: 'C', timeline_start: 22, timeline_end: 25, source_start: 0, source_end: 0, layer: 2 },
      ] },
    ],
  };
  const lanes = new Map<string, RLane>([
    ['A', { zone: 'visual', layer: 0 }], ['B', { zone: 'visual', layer: 0 }], ['C', { zone: 'visual', layer: 0 }], ['P1', { zone: 'visual', layer: 1 }],
    ['a', { zone: 'audio', layer: 0 }], ['b', { zone: 'audio', layer: 0 }], ['c', { zone: 'audio', layer: 0 }],
    ['bgm', { zone: 'audio', layer: 1 }], ['capB', { zone: 'visual', layer: 2 }], ['capC', { zone: 'visual', layer: 2 }],
  ]);
  return { seq, lanes };
};
const clip = (s: RSeq, id: string) => (s.tracks || []).flatMap((t) => t.clips || []).find((c) => c.id === id) as Record<string, unknown> | undefined;
const span = (s: RSeq, id: string) => { const c = clip(s, id); return c ? [c.timeline_start, c.timeline_end] : null; };
let n = 0;
const newId = () => `n${++n}`;

// 1. 置いた所が重なるなら、重ならない段へ逃がす（下にあった物を消さない）
{
  const { seq, lanes } = mk();
  // 絵 P1 を 21-25 へ: 段1は空いている → そのまま
  let m = resolveFree(seq, new Map([['P1', { timeline_start: 21, timeline_end: 25 }]]), lanes);
  assert.equal(m.get('P1')!.layer ?? 1, 1);
  // 字幕 capB を capC の上（22-24）へ: 段2は capC がいる → 段3へ
  m = resolveFree(seq, new Map([['capB', { timeline_start: 22, timeline_end: 24 }]]), lanes);
  assert.equal(m.get('capB')!.layer, 3);
  const out = overwriteMoved(seq, m, lanes);
  assert.deepEqual(span(out, 'capC'), [22, 25]); // 消えていない
  // メインの B を A の上（3-13）へ: 段0は A・C、段1は P1(2-6) → 段2は capB(12-14) と重なる → 段3
  m = resolveFree(seq, new Map([['B', { timeline_start: 3, timeline_end: 13, layer: 0 }]]), lanes);
  assert.equal(m.get('B')!.layer, 3);
  // 使えない段（鍵）は飛ばす
  m = resolveFree(seq, new Map([['capB', { timeline_start: 22, timeline_end: 24 }]]), lanes, { locked: new Set(['visual-3']) });
  assert.equal(m.get('capB')!.layer, 4);
  // 音声は下の段へ（声 b を c の所へ → 段0は c、段1は bgm → 段2）
  m = resolveFree(seq, new Map([['b', { timeline_start: 21, timeline_end: 31 }]]), lanes);
  assert.equal(m.get('b')!.layer, 2);
}
// 2. 割り込み: 途中の B を先頭へ写す → 全部が10秒後ろへ、BGM はそのまま
{
  const { seq, lanes } = mk();
  const r = insertBlock(seq, [{ id: 'blur', start: 12, end: 13 }], 0, 10, lanes, 0, newId);
  assert.deepEqual(span(r.seq, 'A'), [10, 20]);
  assert.deepEqual(span(r.seq, 'a'), [10, 20]);
  assert.deepEqual(span(r.seq, 'capB'), [22, 24]);
  assert.deepEqual(span(r.seq, 'bgm'), [0, 30]);
  assert.deepEqual([r.anns[0].start, r.anns[0].end], [22, 23]);
  // クリップの途中に割り込む: B を 15 で切って右側を後ろへ
  const r2 = insertBlock(seq, [], 15, 4, lanes, 0, newId);
  assert.deepEqual(span(r2.seq, 'B'), [10, 15]);
  const right = (r2.seq.tracks || []).flatMap((t) => t.clips || []).filter((c) => String(c.id).startsWith('B__s_'));
  assert.equal(right.length, 1);
  assert.deepEqual([right[0].timeline_start, right[0].timeline_end, right[0].source_start], [19, 24, 205]);
  const rightA = (r2.seq.tracks || []).flatMap((t) => t.clips || []).filter((c) => String(c.id).startsWith('b__s_'));
  assert.equal(rightA.length, 1); // 相方の声も切って一緒に
  assert.equal(rightA[0].link_id, right[0].link_id);
  assert.deepEqual(span(r2.seq, 'C'), [24, 34]);
}
// 3. まとめて並べ替え: B と C を先頭へ（B, C の順のまま）
{
  const { seq, lanes } = mk();
  const pts = insertPoints(seq, ['B'], lanes, 0, ['B', 'C']);
  assert.deepEqual(pts, [0, 10]);
  const r = rippleMoveGroups(seq, [], [['B', 'b'], ['C', 'c']], 0, lanes, 0);
  assert.deepEqual(span(r.seq, 'B'), [0, 10]);
  assert.deepEqual(span(r.seq, 'C'), [10, 20]);
  assert.deepEqual(span(r.seq, 'A'), [20, 30]);
  assert.deepEqual(span(r.seq, 'capB'), [2, 4]);
  assert.deepEqual(span(r.seq, 'capC'), [12, 15]);
  assert.deepEqual(span(r.seq, 'P1'), [22, 26]); // A に乗っている絵も A と一緒
  assert.deepEqual(span(r.seq, 'bgm'), [0, 30]);
}
// 4. ロール: A と B のつなぎ目を +2 → A は 0-12、B は 12-20（中身は 202 から）
{
  const { seq } = mk();
  const r = applyRoll(seq, ['A', 'a'], ['B', 'b'], 2, () => 1000);
  assert.equal(r.d, 2);
  assert.deepEqual(span(r.seq, 'A'), [0, 12]);
  assert.equal(clip(r.seq, 'A')!.source_end, 112);
  assert.deepEqual(span(r.seq, 'B'), [12, 20]);
  assert.equal(clip(r.seq, 'B')!.source_start, 202);
  assert.deepEqual(span(r.seq, 'b'), [12, 20]);
  // 素材の終わりまでしか伸ばせない
  const r2 = applyRoll(seq, ['A'], ['B'], 5, () => 111);
  assert.equal(r2.d, 1);
}
// 5. スリップ: 置き場所はそのまま、中身だけ
{
  const { seq } = mk();
  const r = applySlip(seq, ['B', 'b'], 3, () => 1000);
  assert.deepEqual(span(r.seq, 'B'), [10, 20]);
  assert.deepEqual([clip(r.seq, 'B')!.source_start, clip(r.seq, 'B')!.source_end], [197, 207]);
  const r2 = applySlip(seq, ['P1'], 3, () => 4);
  assert.equal(r2.d, 0); // 素材の頭（0）より前は無い
}
// 6. スライド: B を +3 → A は 0-13、B は 13-23、C は 23-30
{
  const { seq } = mk();
  const r = applySlide(seq, ['B', 'b'], ['A', 'a'], ['C', 'c'], 3, () => 1000, { minStart: 0, maxEnd: Infinity });
  assert.deepEqual(span(r.seq, 'A'), [0, 13]);
  assert.deepEqual(span(r.seq, 'B'), [13, 23]);
  assert.deepEqual(span(r.seq, 'C'), [23, 30]);
  assert.equal(clip(r.seq, 'C')!.source_start, 303);
}
// 7. 端を伸ばせる所・1コマずつ動かせる所・隣
{
  const { seq, lanes } = mk();
  assert.deepEqual(trimRoom(seq, 'capB', lanes, new Set(['capB'])), { minStart: 0, maxEnd: 22 });
  assert.equal(nudgeRoom(seq, ['capB'], 100, lanes), 8);
  assert.equal(nudgeRoom(seq, ['B', 'b'], 1, lanes), 0); // C に付いている
  assert.equal(touchingNeighbor(seq, 'B', 'end', lanes)!.id, 'C');
  assert.equal(touchingNeighbor(seq, 'P1', 'end', lanes), null);
  assert.deepEqual(withPartners(seq, ['B']).sort(), ['B', 'b']);
  assert.deepEqual(editPoints(seq), [0, 2, 6, 10, 12, 14, 20, 22, 25, 30]);
}
// 8. 切る: 動きのキーも右側の頭からの秒に直す
{
  const s: RSeq = { tracks: [{ type: 'video', clips: [{ id: 'K', timeline_start: 0, timeline_end: 10, source_start: 0, source_end: 10, motion_keys: [{ t: 6 }] }] }] };
  const r = splitAt(s, 4, () => true, newId);
  const right = (r.tracks || [])[0].clips!.find((c) => c.id !== 'K')!;
  assert.deepEqual((right.motion_keys || []).map((k) => k.t), [2]);
}
// 9. 何本か選んで端をまとめて伸び縮み（2026-11-26 本人）
{
  const s: RSeq = { tracks: [
    { type: 'video', clips: [
      { id: 'X', asset_id: 'v', timeline_start: 0, timeline_end: 5, source_start: 10, source_end: 15, link_id: 'lx' },
      { id: 'Y', asset_id: 'v', timeline_start: 10, timeline_end: 15, source_start: 2, source_end: 7 },
      { id: 'G', asset_id: 'g', timeline_start: 20, timeline_end: 25, source_start: 0, source_end: 5, layer: 1 },
    ] },
    { type: 'audio', clips: [
      { id: 'x', asset_id: 'v', timeline_start: 0, timeline_end: 5, source_start: 10, source_end: 15, link_id: 'lx', layer: 0 },
      { id: 'M', asset_id: 'm', role: 'bgm', timeline_start: 0, timeline_end: 6, source_start: 0, source_end: 6, layer: 1 },
      { id: 'M2', asset_id: 'm', role: 'bgm', timeline_start: 6, timeline_end: 12, source_start: 0, source_end: 6, layer: 1 },
    ] },
  ] };
  const lanes = new Map<string, RLane>([
    ['X', { zone: 'visual', layer: 0 }], ['Y', { zone: 'visual', layer: 0 }], ['G', { zone: 'visual', layer: 1 }],
    ['x', { zone: 'audio', layer: 0 }], ['M', { zone: 'audio', layer: 1 }], ['M2', { zone: 'audio', layer: 1 }],
  ]);
  const dur = (c: { asset_id?: unknown }) => (c.asset_id === 'g' ? Infinity : c.asset_id === 'm' ? 6 : 100);
  // 終わりを +2: X と相方 x、Y、絵 G が全部 2 秒伸びる（素材の時刻も付いてくる）
  let m = multiTrimMoved(s, ['X', 'x', 'Y', 'G'], 'end', 2, dur, lanes);
  assert.deepEqual([m.get('X')!.timeline_end, m.get('x')!.timeline_end, m.get('Y')!.timeline_end, m.get('G')!.timeline_end], [7, 7, 17, 27]);
  assert.equal(m.get('X')!.source_end, 17);
  assert.equal(m.get('Y')!.source_end, 9);
  // 終わりを +8: X は選んだ Y の手前（10）で止まり、Y・G はそのまま 8 秒
  m = multiTrimMoved(s, ['X', 'x', 'Y', 'G'], 'end', 8, dur, lanes);
  assert.equal(m.get('X')!.timeline_end, 10);
  assert.equal(m.get('x')!.timeline_end, 10); // 組は同じだけ
  assert.equal(m.get('Y')!.timeline_end, 23);
  // 頭を -3: X は 0 より前へ出ない（動かない）、Y は素材の頭（2秒分）まで
  m = multiTrimMoved(s, ['X', 'x', 'Y'], 'start', -3, dur, lanes);
  assert.equal(m.has('X'), false);
  assert.deepEqual([m.get('Y')!.timeline_start, m.get('Y')!.source_start], [8, 0]);
  // 縮める: 0.1 秒より短くならない
  m = multiTrimMoved(s, ['M', 'M2'], 'end', -10, dur, lanes);
  assert.deepEqual([m.get('M')!.timeline_end, m.get('M2')!.timeline_end], [0.1, 6.1]);
  // 音の素材の終わり（6秒）より先へは伸ばせない
  m = multiTrimMoved(s, ['M2'], 'end', 3, dur, lanes);
  assert.equal(m.has('M2'), false);
}
console.log('timeline-ops ok');

// A caption and its question card share the dragged edge. The neighbour keeps
// touching the caption even when trimming both layers from the left.
{
  const clips = [
    { id: 'previous', timeline_start: 0, timeline_end: 3 },
    { id: 'caption', timeline_start: 3, timeline_end: 6 },
    { id: 'card', kind: 'image', source_start: 0, source_end: 3, timeline_start: 3, timeline_end: 6 },
  ];
  const seq = { tracks: [{ clips }] };
  const lanes = new Map<string, RLane>(clips.map(c => [c.id, { zone: 'visual', layer: c.id === 'card' ? 1 : 2 }]));
  const group = selectionRoll(seq, ['caption', 'card'], 'card', 'start', lanes, false, () => false, [])!;
  const edit = applyRoll(seq, group.prevIds, group.nextIds, -1, () => Infinity);
  assert.deepEqual(edit.seq.tracks[0].clips.map(c => [c.timeline_start, c.timeline_end]), [[0, 2], [2, 6], [2, 6]]);
  const join = selectionRoll(seq, ['previous', 'caption'], 'previous', 'end', lanes, false, () => false, [])!;
  assert.deepEqual(join.prevIds, ['previous']);
  assert.deepEqual(join.nextIds, ['caption']);
}
