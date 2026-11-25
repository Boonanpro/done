// メインの段を詰めて直す（2026-11-25 本人）。node --experimental-strip-types で動かす。
import assert from 'node:assert/strict';
import { closeMainGaps, insertPoints, mainGapAt, mainLayerOf, rippleDeleteMain, rippleMove, rippleTrim, type RLane, type RSeq } from './ripple-edit.ts';

// メイン: A[0-10] B[10-20] C[20-30]（声つき）。字幕: B の上 12-14、C の上 22-25。BGM 0-30。モザイク 15-18（B の上）。
const mk = (): { seq: RSeq; lanes: Map<string, RLane> } => {
  const seq: RSeq = {
    tracks: [
      { type: 'video', clips: [
        { id: 'A', asset_id: 'x', timeline_start: 0, timeline_end: 10, source_start: 100, source_end: 110, link_id: 'la' },
        { id: 'B', asset_id: 'x', timeline_start: 10, timeline_end: 20, source_start: 200, source_end: 210, link_id: 'lb' },
        { id: 'C', asset_id: 'x', timeline_start: 20, timeline_end: 30, source_start: 300, source_end: 310, link_id: 'lc' },
      ] },
      { type: 'audio', clips: [
        { id: 'a', asset_id: 'x', timeline_start: 0, timeline_end: 10, source_start: 100, source_end: 110, link_id: 'la', layer: 0 },
        { id: 'b', asset_id: 'x', timeline_start: 10, timeline_end: 20, source_start: 200, source_end: 210, link_id: 'lb', layer: 0 },
        { id: 'c', asset_id: 'x', timeline_start: 20, timeline_end: 30, source_start: 300, source_end: 310, link_id: 'lc', layer: 0 },
        { id: 'bgm', asset_id: 'm', role: 'music', timeline_start: 0, timeline_end: 30, source_start: 0, source_end: 30, layer: 1 },
      ] },
      { type: 'caption', clips: [
        { id: 'capB', text: 'B', timeline_start: 12, timeline_end: 14, source_start: 0, source_end: 0 },
        { id: 'capC', text: 'C', timeline_start: 22, timeline_end: 25, source_start: 0, source_end: 0 },
      ] },
    ],
  };
  const lanes = new Map<string, RLane>([
    ['A', { zone: 'visual', layer: 0 }], ['B', { zone: 'visual', layer: 0 }], ['C', { zone: 'visual', layer: 0 }],
    ['a', { zone: 'audio', layer: 0 }], ['b', { zone: 'audio', layer: 0 }], ['c', { zone: 'audio', layer: 0 }],
    ['bgm', { zone: 'audio', layer: 1 }], ['capB', { zone: 'visual', layer: 2 }], ['capC', { zone: 'visual', layer: 2 }],
  ]);
  return { seq, lanes };
};
const anns = [{ id: 'mz', start: 15, end: 18, data: { keyframes: [{ t: 15, x: 0 }, { t: 18, x: 1 }] } }];
const clip = (s: RSeq, id: string) => (s.tracks || []).flatMap((t) => t.clips || []).find((c) => c.id === id);
const span = (s: RSeq, id: string) => { const c = clip(s, id); return c ? [c.timeline_start, c.timeline_end] : null; };

{
  const { seq, lanes } = mk();
  assert.equal(mainLayerOf(seq.tracks || [], lanes), 0);
}

// B の終わりを 4 秒縮める → B[10-16]、C と字幕C は 4 秒前へ、BGM は 26 まで、隙間なし。モザイク15-18は16で切れる。
{
  const { seq, lanes } = mk();
  const r = rippleTrim(seq, anns, ['B', 'b'], 'end', -4, lanes, 0);
  assert.deepEqual(span(r.seq, 'B'), [10, 16]);
  assert.equal(clip(r.seq, 'B')!.source_end, 206);
  assert.deepEqual(span(r.seq, 'b'), [10, 16]);
  assert.deepEqual(span(r.seq, 'C'), [16, 26]);
  assert.deepEqual(span(r.seq, 'c'), [16, 26]);
  assert.deepEqual(span(r.seq, 'capC'), [18, 21]);
  assert.deepEqual(span(r.seq, 'capB'), [12, 14]);
  assert.deepEqual(span(r.seq, 'bgm'), [0, 26]);
  assert.equal(clip(r.seq, 'bgm')!.source_end, 26);
  assert.deepEqual([r.anns[0].start, r.anns[0].end], [15, 16]);
  assert.equal(r.seq.duration, 26);
}

// B の頭を 3 秒縮める（Premiere のリップル）→ B は 10 から始まり中身は 203 から、字幕B(12-14)は抜けた区間の後ろなので 9-11
{
  const { seq, lanes } = mk();
  const r = rippleTrim(seq, anns, ['B', 'b'], 'start', 3, lanes, 0);
  assert.deepEqual(span(r.seq, 'B'), [10, 17]);
  assert.equal(clip(r.seq, 'B')!.source_start, 203);
  assert.deepEqual(span(r.seq, 'capB'), [10, 11]); // 12-14 のうち 10-13 を抜く → 頭が切れて 10-11
  assert.deepEqual(span(r.seq, 'C'), [17, 27]);
  assert.deepEqual([r.anns[0].start, r.anns[0].end], [12, 15]);
  assert.deepEqual(r.anns[0].data.keyframes.map((k: { t: number }) => k.t), [12, 15]);
}

// 字幕の中だけの区間を縮めると、その字幕は消える
{
  const { seq, lanes } = mk();
  const r = rippleTrim(seq, [], ['C', 'c'], 'start', 6, lanes, 0);
  assert.equal(clip(r.seq, 'capC'), undefined);
}

// A の終わりを 2 秒伸ばす → B 以降が 2 秒後ろ、BGM はそのまま（A の終わりをまたぐ）
{
  const { seq, lanes } = mk();
  const r = rippleTrim(seq, anns, ['A', 'a'], 'end', 2, lanes, 0);
  assert.deepEqual(span(r.seq, 'A'), [0, 12]);
  assert.deepEqual(span(r.seq, 'B'), [12, 22]);
  assert.deepEqual(span(r.seq, 'capB'), [14, 16]);
  assert.deepEqual(span(r.seq, 'bgm'), [0, 30]);
  assert.deepEqual([r.anns[0].start, r.anns[0].end], [17, 20]);
}

// 並べ替え: C を A の前（0）へ → C[0-10] A[10-20] B[20-30]。字幕C・字幕B・モザイクは自分のクリップと一緒に動く。BGM は動かない。
{
  const { seq, lanes } = mk();
  assert.deepEqual(insertPoints(seq, ['C', 'c'], lanes, 0), [0, 10, 20]);
  const r = rippleMove(seq, anns, ['C', 'c'], 0, lanes, 0);
  assert.deepEqual(span(r.seq, 'C'), [0, 10]);
  assert.deepEqual(span(r.seq, 'c'), [0, 10]);
  assert.deepEqual(span(r.seq, 'A'), [10, 20]);
  assert.deepEqual(span(r.seq, 'B'), [20, 30]);
  assert.deepEqual(span(r.seq, 'capC'), [2, 5]);
  assert.deepEqual(span(r.seq, 'capB'), [22, 24]);
  assert.deepEqual(span(r.seq, 'bgm'), [0, 30]);
  assert.deepEqual([r.anns[0].start, r.anns[0].end], [25, 28]);
}

// 並べ替え: A を B と C の間（詰めた後の 10）へ → B[0-10] A[10-20] C[20-30]
{
  const { seq, lanes } = mk();
  const r = rippleMove(seq, anns, ['A', 'a'], 10, lanes, 0);
  assert.deepEqual(span(r.seq, 'B'), [0, 10]);
  assert.deepEqual(span(r.seq, 'A'), [10, 20]);
  assert.deepEqual(span(r.seq, 'C'), [20, 30]);
  assert.deepEqual(span(r.seq, 'capB'), [2, 4]);
  assert.deepEqual(span(r.seq, 'capC'), [22, 25]);
}

// メインのクリップを消して詰める → 全部の段が詰まり、消したクリップの上の字幕も消える
{
  const { seq, lanes } = mk();
  void lanes;
  const r = rippleDeleteMain(seq, anns, ['B', 'b']);
  assert.equal(clip(r.seq, 'B'), undefined);
  assert.equal(clip(r.seq, 'capB'), undefined);
  assert.deepEqual(span(r.seq, 'C'), [10, 20]);
  assert.deepEqual(span(r.seq, 'capC'), [12, 15]);
  assert.deepEqual(span(r.seq, 'bgm'), [0, 20]);
  assert.equal(r.anns.length, 0);
}

// 隙間: B を消して隙間を残した後、その隙間を詰める。隙間の中の字幕は頭へ寄せて残す
{
  const { seq, lanes } = mk();
  const holed: RSeq = { ...seq, tracks: (seq.tracks || []).map((t) => ({ ...t, clips: (t.clips || []).filter((c) => c.id !== 'B' && c.id !== 'b') })) };
  assert.deepEqual(mainGapAt(holed, 15, lanes, 0), [10, 20]);
  assert.equal(mainGapAt(holed, 5, lanes, 0), null);
  const r = closeMainGaps(holed, [], lanes, 0);
  assert.equal(r.closed, 10);
  assert.deepEqual(span(r.seq, 'C'), [10, 20]);
  assert.deepEqual(span(r.seq, 'capB'), [10, 12]);
  assert.deepEqual(span(r.seq, 'capC'), [12, 15]);
}
console.log('ripple-edit ok');
