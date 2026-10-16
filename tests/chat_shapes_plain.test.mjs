// 部品を読める文章にする（frontend/src/lib/chat-shapes/plain.ts と、その写し mobile/chat-shapes-plain.ts）の試験。
// アプリは別のパッケージなので同じ中身の写しを持つ。両方が同じ出力を返すことをここで見る。
// 実行: node --experimental-strip-types --test tests/chat_shapes_plain.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as web from '../frontend/src/lib/chat-shapes/plain.ts';
import * as app from '../mobile/chat-shapes-plain.ts';

const SAMPLE = [
  '結論です。',
  '',
  '```openui-lang',
  'root = Compare(["観点", "ベーシック", "プレミアム"], [["月額", "368円", "980円"], ["広告", "あり", "なし"]], "プランの違い")',
  '```',
  '',
  'どちらにしますか？',
  '',
  '```openui-lang',
  'root = Choice("プラン", ["ベーシック", "プレミアム"])',
  '```',
  '',
  '```openui-lang',
  'root = Input("月の予算", "number", "万円", "例: 3")',
  '```',
  '',
  '```openui-lang',
  'root = Steps(["アプリを開く", "予約を確認する"], "当日の流れ")',
  '```',
  '',
  '```openui-lang',
  'root = Chart("line", ["9/8", "9/9"], [{name: "広告費", values: [1200, 980]}, {name: "登録", values: [1, 0]}], "円", "日別")',
  '```',
  '',
  '以上です。',
].join('\n');

test('5部品が読める文章（表・番号つき・手順・数字の表）になる。前後の文章はそのまま', () => {
  const out = web.replaceShapeBlocks(SAMPLE);
  assert.equal(out.includes('```openui'), false);
  assert.match(out, /^結論です。/);
  assert.match(out, /以上です。$/);
  assert.match(out, /\| 観点 \| ベーシック \| プレミアム \|\n\|---\|---\|---\|\n\| 月額 \| 368円 \| 980円 \|/);
  assert.match(out, /\*\*プラン\*\*\n1\. ベーシック\n2\. プレミアム/);
  assert.match(out, /「プラン → …」/);
  assert.match(out, /\*\*月の予算\*\*: 数値（万円）を1つ送ってください（例: 3）/);   // 入力例「例: 3」の「例: 」は二重にしない
  assert.match(out, /\*\*当日の流れ\*\*\n1\. アプリを開く\n2\. 予約を確認する/);
  assert.match(out, /\*\*日別\*\*\n\n\| \| 広告費 \| 登録 \|\n\|---\|---\|---\|\n\| 9\/8 \| 1,200円 \| 1円 \|\n\| 9\/9 \| 980円 \| 0円 \|/);   // 単位は部品に1つ（画面のグラフも全系列に同じ単位）
});

test('壊れた部品・知らない部品・閉じていないブロック・別の言語のブロックはそのまま', () => {
  const broken = '```openui-lang\nroot = Choice("x"\n```\n後ろ';
  assert.equal(web.replaceShapeBlocks(broken), broken);
  const unknown = '```openui-lang\nroot = Gauge("x", 3)\n```';
  assert.equal(web.replaceShapeBlocks(unknown), unknown);
  const open = '```openui-lang\nroot = Choice("x", ["a", "b"])';
  assert.equal(web.replaceShapeBlocks(open), open);
  const python = '```python\nprint(1)\n```';
  assert.equal(web.replaceShapeBlocks(python), python);
  assert.equal(web.replaceShapeBlocks('部品なし'), '部品なし');
  // 説明用のコード例（~~~markdown の中）は触らない
  const example = '~~~markdown\n```openui-lang\nroot = Choice("x", ["a", "b"])\n```\n~~~';
  assert.equal(web.replaceShapeBlocks(example), example);
});

test('CRLF の返事でも読める文章になる', () => {
  const out = web.replaceShapeBlocks(SAMPLE.replaceAll('\n', '\r\n'));
  assert.equal(out.includes('```openui'), false);
  assert.match(out, /1\. ベーシック/);
});

test('アプリの写しは本体と同じ中身・同じ出力', () => {
  for (const text of [SAMPLE, '```openui-lang\nroot = Choice("x"\n```', 'そのまま']) {
    assert.equal(app.replaceShapeBlocks(text), web.replaceShapeBlocks(text));
  }
  const webSrc = readFileSync(new URL('../frontend/src/lib/chat-shapes/plain.ts', import.meta.url), 'utf8');
  const appSrc = readFileSync(new URL('../mobile/chat-shapes-plain.ts', import.meta.url), 'utf8');
  assert.ok(appSrc.endsWith(webSrc), 'mobile/chat-shapes-plain.ts は見出し3行 + frontend の plain.ts と同じ中身');
});
