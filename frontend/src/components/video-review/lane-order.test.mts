// 段の上下 = 前後（2026-11-18 本人）。node --experimental-strip-types で動かす。
import { byLane, stackBands, visualLane } from './lane-order.ts';
import assert from 'node:assert/strict';

// 段: 自分の段 → 字幕のトラック（2より下にしない）→ 効果3 → 重ねる1 → トラックの順
assert.equal(visualLane('caption', {}, 0), 2);
assert.equal(visualLane('caption', { layer: 0 }, 6), 0);
assert.equal(visualLane('video', {}, 4), 4);
assert.equal(visualLane('video', { composition: 'pip' }, 4), 1);

// 作品に入った順ではなく段で並ぶ（後ろ→前）
assert.deepEqual(byLane([{ id: 'up', l: 5 }, { id: 'low', l: 1 }, { id: 'mid', l: 3 }], (x) => x.l).map((x) => x.id), ['low', 'mid', 'up']);

// テロップ(7) < 絵(10) < テロップ(11): 絵はテロップ7の上の canvas、テロップ11はその上
const s = stackBands([
  { kind: 'cap', layer: 11, id: 'capTop' },
  { kind: 'pic', layer: 0, id: 'base' },
  { kind: 'cap', layer: 7, id: 'capLow' },
  { kind: 'pic', layer: 10, id: 'picMid' },
]);
assert.deepEqual(s.bands.map((b) => [b.kind, [...b.ids]]), [['pic', ['base']], ['cap', ['capLow']], ['pic', ['picMid']], ['cap', ['capTop']]]);
assert.equal(s.canvasOf.get('base'), 0);
assert.equal(s.canvasOf.get('picMid'), 1);
assert.equal(s.canvases, 2);
// テロップだけが上なら canvas は1枚のまま
assert.equal(stackBands([{ kind: 'pic', layer: 0, id: 'a' }, { kind: 'cap', layer: 2, id: 'c' }]).canvases, 1);
// 下の段へ動かしたテロップは、入った順が後でも後ろの層
const t = stackBands([{ kind: 'cap', layer: 7, id: 'upper' }, { kind: 'cap', layer: 6, id: 'movedDown' }]);
assert.deepEqual([...t.bands[1].ids], ['movedDown', 'upper']);
console.log('lane-order ok');
