// 部品の切り出し（frontend/src/lib/chat-shapes/split.ts）と答えの文面（answers.ts）の試験。
// 実行: node --experimental-strip-types --test tests/chat_shapes_split.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { splitShapeSegments, hasShapeFence } from '../frontend/src/lib/chat-shapes/split.ts';
import {
  choiceAnswerText, inputAnswerText, findChoiceAnswer, findInputAnswer,
} from '../frontend/src/lib/chat-shapes/answers.ts';

const CODE = 'root = Choice("予算", ["5万円", "10万円"])';

test('部品が無い返事は文章1つのまま', () => {
  const segs = splitShapeSegments('こんにちは。今日は晴れです。');
  assert.deepEqual(segs, [{ kind: 'markdown', text: 'こんにちは。今日は晴れです。' }]);
  assert.equal(hasShapeFence('```python\nprint(1)\n```'), false);
  assert.deepEqual(splitShapeSegments(''), [{ kind: 'markdown', text: '' }]);
});

test('文章・部品・文章の順に切り出す（閉じたブロック）', () => {
  const text = `予算はどれくらいですか？\n\n\`\`\`openui-lang\n${CODE}\n\`\`\`\n\n決まったら進めます。`;
  const segs = splitShapeSegments(text);
  assert.equal(segs.length, 3);
  assert.equal(segs[0].kind, 'markdown');
  assert.match(segs[0].text, /予算はどれくらい/);
  assert.deepEqual(segs[1], { kind: 'shape', code: CODE, complete: true, index: 0 });
  assert.equal(segs[2].kind, 'markdown');
  assert.match(segs[2].text, /決まったら/);
});

test('生成の途中（閉じが無い）は streaming なら未完の部品として返す', () => {
  const text = `予算は？\n\n\`\`\`openui-lang\nroot = Choice("予算", ["5万`;
  const segs = splitShapeSegments(text, { streaming: true });
  assert.equal(segs.length, 2);
  assert.deepEqual(segs[1], { kind: 'shape', code: 'root = Choice("予算", ["5万', complete: false, index: 0 });
  // 言語名の行だけ届いた時点でも、空の未完の部品になる（崩れない）
  const early = splitShapeSegments('予算は？\n\n```openui-lang', { streaming: true });
  assert.deepEqual(early[1], { kind: 'shape', code: '', complete: false, index: 0 });
  // 言語名が途中（```openui-la）の間はまだ文章のまま
  const half = splitShapeSegments('予算は？\n\n```openui-la', { streaming: true });
  assert.equal(half.length, 1);
  assert.equal(half[0].kind, 'markdown');
});

test('保存済み（streaming でない）で閉じが無いのは壊れた書き方＝文章に戻す', () => {
  const text = `予算は？\n\n\`\`\`openui-lang\n${CODE}`;
  const segs = splitShapeSegments(text);
  assert.equal(segs.length, 1);
  assert.equal(segs[0].kind, 'markdown');
  assert.match(segs[0].text, /```openui-lang/);
});

test('他の言語のコードブロックの中の openui-lang は部品にしない。複数の部品は別々に番号が付く', () => {
  const text = [
    '例:', '````markdown', '```openui-lang', 'root = Choice("x", ["a","b"])', '```', '````',
    '本物:', '```openui-lang', 'root = Steps(["a","b"])', '```', '```openui', 'root = Compare(["a"], [["1"]])', '```',
  ].join('\n');
  const segs = splitShapeSegments(text);
  const shapes = segs.filter((s) => s.kind === 'shape');
  assert.equal(shapes.length, 2);
  assert.deepEqual(shapes.map((s) => s.index), [0, 1]);
  assert.equal(shapes[0].code, 'root = Steps(["a","b"])');
  assert.equal(shapes[1].code, 'root = Compare(["a"], [["1"]])');
  assert.match(segs[0].text, /````markdown/);
});

test('答えの文面と、部屋の記録からの探し直し', () => {
  assert.equal(choiceAnswerText('予算', '10万円'), '予算 → 10万円');
  assert.equal(inputAnswerText('初期費用', '30', '万円'), '初期費用 → 30万円');
  assert.equal(inputAnswerText('初期費用', '30万円', '万円'), '初期費用 → 30万円');
  assert.equal(inputAnswerText('名前', ' 太郎 '), '名前 → 太郎');
  const asked = 1000;
  const utter = [
    { text: '予算 → 10万円', at: 500 },      // 部品より前の発言は数えない
    { text: 'うん', at: 1200 },
    { text: '予算 → 10万円', at: 1500 },
    { text: '初期費用 → 30万円', at: 1600 },
  ];
  assert.equal(findChoiceAnswer(utter.slice(0, 2), '予算', ['5万円', '10万円'], asked), null);
  assert.equal(findChoiceAnswer(utter, '予算', ['5万円', '10万円'], asked), '10万円');
  assert.equal(findChoiceAnswer(utter, '予算', ['5万円'], asked), null);
  assert.equal(findInputAnswer(utter, '初期費用', asked), '30万円');
  assert.equal(findInputAnswer(utter, '月額', asked), null);
});
