// 本物の中身を見せる部品（地図・写真の札・引用・出どころ・動画のコマ・前後）の決まり（2026-11-12）
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { checkShapeProgram, timeSeconds } = await import('../frontend/src/lib/chat-shapes/schema.ts');
const { shapeToPlainMarkdown } = await import('../frontend/src/lib/chat-shapes/plain.ts');
const { mapView, project, fitZoom } = await import('../frontend/src/lib/chat-shapes/map-geometry.ts');
const { pointText, findLastPoint, readAnswerTo } = await import('../frontend/src/lib/chat-shapes/answers.ts');

const MAP = `root = Column([m, Row([a, b])])
m = Map([{label: "Personal Care", lat: 34.736736, lng: 135.419586, sub: "徒歩15分"}, {label: "らんまん堂", lat: 34.824421, lng: 135.557968}], "近くの鍼灸院", {lat: 34.73308, lng: 135.42829, label: "今"})
a = Item("Personal Care 鍼灸整体院", "JR尼崎駅から徒歩15分", "https://example.com/a.jpg", ["鍼灸・PNF"], "https://personalcare-acupuncture.net/", "1")
b = Item("らんまん堂", "茨木", null, ["長野式"], null, "2")`;

test('地図・札・引用・出どころ・コマ・前後が1つのブロックで組める', () => {
  assert.equal(checkShapeProgram(MAP).ok, true);
  assert.equal(checkShapeProgram('root = Quote("院長 仲江政史", "仲江鍼灸院 院長ごあいさつ", "https://nakaesinkyuin.com/", ["仲江政史"])').ok, true);
  assert.equal(checkShapeProgram('root = Sources([{title: "院長ごあいさつ", url: "https://nakaesinkyuin.com/", note: "名前と長野式"}])').ok, true);
  assert.equal(checkShapeProgram('root = Frames([{src: "/api/v1/files/a.jpg", time: "9:41", label: "時計の図解"}], "特典 v13", "17:47")').ok, true);
  assert.equal(checkShapeProgram('root = BeforeAfter("/api/v1/files/a.png", "/api/v1/files/b.png", "字幕を大きく")').ok, true);
});

test('座標の無い地図・場所が多すぎる地図・時刻の無いコマは通さない', () => {
  assert.equal(checkShapeProgram('root = Map([{label: "x"}])').ok, false);
  const many = Array.from({ length: 13 }, (_, i) => `{label: "p${i}", lat: 34, lng: 135}`).join(', ');
  assert.equal(checkShapeProgram(`root = Map([${many}])`).ok, false);
  assert.equal(checkShapeProgram('root = Frames([{src: "/api/v1/files/a.jpg"}])').ok, false);
  assert.equal(checkShapeProgram('root = Map([{label: "x", lat: 95, lng: 135}])').ok, false);
});

test('部品を描けない画面では読める文章になる', () => {
  const t = shapeToPlainMarkdown(MAP);
  assert.match(t, /1\. Personal Care（徒歩15分）/);
  assert.match(t, /\*\*Personal Care 鍼灸整体院\*\*（\[ページ\]\(https:\/\/personalcare-acupuncture\.net\/\)）/);
  assert.match(shapeToPlainMarkdown('root = Quote("院長 仲江政史", "院長ごあいさつ", "https://nakaesinkyuin.com/")'), /^> 院長 仲江政史\n\n— \[院長ごあいさつ\]/);
  assert.match(shapeToPlainMarkdown('root = Frames([{src: "/api/v1/files/a.jpg", time: "9:41", label: "時計"}])'), /- 9:41 時計/);
});

test('地図: 全部の点が枠に入り、日本の中は地理院タイル', () => {
  const pl = [{ lat: 34.736736, lng: 135.419586 }, { lat: 34.824421, lng: 135.557968 }];
  const v = mapView(pl, { lat: 34.73308, lng: 135.42829 }, 358, 258);
  for (const p of [...v.points, v.here]) {
    assert.ok(p.left > 0 && p.left < 358 && p.top > 0 && p.top < 258, JSON.stringify(p));
  }
  assert.match(v.tiles[0].url, /cyberjapandata\.gsi\.go\.jp\/xyz\/pale\//);
  assert.equal(v.credit, '地理院タイル');
  const paris = mapView([{ lat: 48.8566, lng: 2.3522 }], null, 358, 258);
  assert.match(paris.tiles[0].url, /tile\.openstreetmap\.org/);
  assert.equal(paris.zoom, 15);
  assert.ok(fitZoom(pl, 358, 258) >= 9);
  assert.ok(Math.abs(project({ lat: 0, lng: 0 }, 0).x - 128) < 1e-9);
});

test('押した物は「題 → 押した物」で届き、最後に押した物が選ばれた物', () => {
  assert.equal(pointText('地図', '1 Personal Care'), '地図 → 1 Personal Care');
  const at = (v) => ({ text: '', at: 0, answerTo: readAnswerTo({ answer_to: { message_id: 'm', part: 'p00000000', kind: 'point', value: v } }) });
  assert.equal(findLastPoint([at('A'), at('B')], 'm', 'p00000000'), 'B');
  assert.equal(findLastPoint([at('A')], 'm', 'p11111111'), null);
});

test('時刻の文字を秒に', () => {
  assert.equal(timeSeconds('9:41'), 581);
  assert.equal(timeSeconds('1:02:03'), 3723);
  assert.equal(timeSeconds('581.9'), 581.9);
  assert.equal(timeSeconds('abc'), null);
});
