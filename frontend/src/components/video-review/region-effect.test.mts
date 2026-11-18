// 範囲の効果（モザイク等）の見分けと動き。node --experimental-strip-types で動かす。
import { isRegionEffect, regionAt, regionLabel } from './region-effect.ts';
import assert from 'node:assert/strict';

const mosaic = {
  id: 'fx_ag_1', timeline_start: 50, timeline_end: 52, style: 'mosaic',
  region: { x: 0.7, y: 0.9, width: 0.2, height: 0.1 },
  region_keys: [{ t: 0, x: 0.7, y: 0.9, w: 0.2, h: 0.1 }, { t: 2, x: 0.5, y: 0.8, w: 0.1, h: 0.05 }],
};
// 素材が無く範囲を持つ映像の段のクリップは効果（書き出しの Z_FX と同じ）
assert.equal(isRegionEffect(mosaic), true);
assert.equal(regionLabel(mosaic), 'モザイク');
assert.equal(isRegionEffect({ ...mosaic, asset_id: 'a1' }), false);       // 素材があれば絵
assert.equal(isRegionEffect({ ...mosaic, style: 'note' }), false);        // メモは描かない
assert.equal(isRegionEffect({ ...mosaic, text: '字幕' }), false);         // テロップ
assert.equal(isRegionEffect({ ...mosaic, region: { x: 0, y: 0, width: 0, height: 0 } }), false);
assert.equal(isRegionEffect({ id: 'v', timeline_start: 0, timeline_end: 1 }), false);
// 動く範囲: クリップの頭からの秒で直線につなぐ。前後は端の値
assert.deepEqual(regionAt(mosaic, 49), { x: 0.7, y: 0.9, w: 0.2, h: 0.1 });
const mid = regionAt(mosaic, 51)!;
assert.ok(Math.abs(mid.x - 0.6) < 1e-9 && Math.abs(mid.y - 0.85) < 1e-9 && Math.abs(mid.w - 0.15) < 1e-9);
assert.deepEqual(regionAt(mosaic, 60), { x: 0.5, y: 0.8, w: 0.1, h: 0.05 });
// キーの無い範囲はそのまま
assert.deepEqual(regionAt({ ...mosaic, region_keys: null }, 51), { x: 0.7, y: 0.9, w: 0.2, h: 0.1 });
console.log('region-effect ok');
