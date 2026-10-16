// 部品の切り出し（frontend/src/lib/chat-shapes/split.ts）と答えの文面・照合（answers.ts）の試験。
// 実行: node --experimental-strip-types --test tests/chat_shapes_split.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { splitShapeSegments, hasShapeFence } from '../frontend/src/lib/chat-shapes/split.ts';
import {
  choiceAnswerText, inputAnswerText, inputAnswerValue, findChoiceAnswer, findInputAnswer, partKey, partKeys, readAnswerTo,
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
  // 途中まで届いた全ての長さで例外を出さない
  const fence = '```openui-lang\n' + CODE + '\n```';
  for (let i = 0; i <= fence.length; i++) assert.doesNotThrow(() => splitShapeSegments(fence.slice(0, i), { streaming: true }));
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

test('Markdown のフェンス構文: チルダの外側・情報文字列つきの外側・CRLF・チルダの部品・字下げ', () => {
  const fence = `\`\`\`openui-lang\n${CODE}\n\`\`\``;
  // ~~~markdown の中は説明用のコード（部品にしない）
  assert.equal(splitShapeSegments(`~~~markdown\n${fence}\n~~~`).filter((s) => s.kind === 'shape').length, 0);
  // ````markdown title="example" のように情報文字列が続いても外側のフェンスとして読む
  assert.equal(splitShapeSegments(`\`\`\`\`markdown title="example"\n${fence}\n\`\`\`\``).filter((s) => s.kind === 'shape').length, 0);
  // 外側が ~~~ で中が ``` の時、中の ``` は閉じにならない（文字が違う）
  assert.equal(splitShapeSegments(`~~~\n${fence}\n~~~`).filter((s) => s.kind === 'shape').length, 0);
  // CRLF でも部品になり、コードの行末 CR は落ちる。文章側は元の文字を保つ
  const crlf = splitShapeSegments(`前の文\r\n${fence.replaceAll('\n', '\r\n')}\r\n後の文`);
  assert.deepEqual(crlf.filter((s) => s.kind === 'shape'), [{ kind: 'shape', code: CODE, complete: true, index: 0 }]);
  assert.equal(crlf[0].text, '前の文\r');
  assert.equal(hasShapeFence('```openui-lang\r\n'), true);
  // ~~~openui-lang も部品。閉じは同じ文字で同じ本数以上
  assert.equal(splitShapeSegments(`~~~openui-lang\n${CODE}\n~~~`)[0].kind, 'shape');
  assert.equal(splitShapeSegments(`~~~~openui-lang\n${CODE}\n~~~`).filter((s) => s.kind === 'shape').length, 0);
  // 字下げ3つまでは開き。4つはコードブロック（字下げコード）なので部品にしない
  assert.equal(splitShapeSegments(`   \`\`\`openui-lang\n${CODE}\n   \`\`\``)[0].kind, 'shape');
  assert.equal(splitShapeSegments(`    \`\`\`openui-lang\n${CODE}\n    \`\`\``).filter((s) => s.kind === 'shape').length, 0);
  // 情報文字列の最初の語だけが言語名。openui-langx は別物
  assert.equal(splitShapeSegments(`\`\`\`openui-langx\n${CODE}\n\`\`\``).filter((s) => s.kind === 'shape').length, 0);
  assert.equal(splitShapeSegments(`\`\`\`openui-lang  extra words\n${CODE}\n\`\`\``)[0].kind, 'shape');
});

test('普通の文章・コード・既存の目印はそのまま（バイト単位で同じ）', () => {
  for (const s of ['説明だけです', '```python\nprint(1)\n```', '```proposal\nplan.json\n```', '[確認: test]', '[送信案: test]']) {
    assert.deepEqual(splitShapeSegments(s), [{ kind: 'markdown', text: s }]);
  }
});

test('答えの文面と、照合情報（answer_to）による探し直し', () => {
  assert.equal(choiceAnswerText('予算', '10万円'), '予算 → 10万円');
  assert.equal(inputAnswerText('初期費用', '30', '万円'), '初期費用 → 30万円');
  assert.equal(inputAnswerText('初期費用', '30万円', '万円'), '初期費用 → 30万円');
  assert.equal(inputAnswerText('名前', ' 太郎 '), '名前 → 太郎');
  assert.equal(inputAnswerValue('初期費用', '30', '万円'), '30万円');
  const m1 = 'msg-1';
  const p1 = partKey(CODE);
  const utter = [
    // 文面が同じでも照合情報が無い発言（手で打った物）は答えにならない
    { text: '予算 → 10万円', at: 1200 },
    // 別の返事（msg-2）の同じ部品への答えは、msg-1 の答えにならない
    { text: '予算 → 5万円', at: 1300, answerTo: { message_id: 'msg-2', part: p1, kind: 'choice', value: '5万円' } },
    { text: '予算 → 10万円', at: 1500, answerTo: { message_id: m1, part: p1, kind: 'choice', value: '10万円' } },
    { text: '初期費用 → 30万円', at: 1600, answerTo: { message_id: m1, part: 'p-input', kind: 'input', value: '30万円' } },
  ];
  assert.equal(findChoiceAnswer(utter.slice(0, 2), m1, p1), null);
  assert.equal(findChoiceAnswer(utter, m1, p1), '10万円');
  assert.equal(findChoiceAnswer(utter, 'msg-2', p1), '5万円');
  assert.equal(findChoiceAnswer(utter, m1, 'p-other'), null);
  assert.equal(findInputAnswer(utter, m1, 'p-input'), '30万円');
  assert.equal(findInputAnswer(utter, m1, p1), null);   // 種類が違う（choice の答えは input に当てない）
});

test('部品の鍵: コードから決まり、同じコードが2つあれば ordinal で区別する', () => {
  assert.equal(partKey(CODE), partKey(`  ${CODE}  `));
  assert.notEqual(partKey(CODE), partKey('root = Choice("予算", ["5万円", "20万円"])'));
  assert.match(partKey(CODE), /^p[0-9a-f]{8}$/);
  const keys = partKeys([CODE, 'root = Steps(["a"])', CODE]);
  assert.equal(keys[0], partKey(CODE));
  assert.equal(keys[2], `${partKey(CODE)}-1`);
  assert.equal(new Set(keys).size, 3);
});

test('部屋の記録の ai_context から照合情報を読む（壊れた物は無視）', () => {
  assert.deepEqual(readAnswerTo({ answer_to: { message_id: 'm', part: 'p', kind: 'choice', value: 'A' } }), { message_id: 'm', part: 'p', kind: 'choice', value: 'A' });
  assert.deepEqual(readAnswerTo({ answer_to: { message_id: 'm', part: 'p', kind: 'input', value: '3万円', question: '予算' } }), { message_id: 'm', part: 'p', kind: 'input', value: '3万円', question: '予算' });
  assert.equal(readAnswerTo(null), null);
  assert.equal(readAnswerTo({ blocks: [] }), null);
  assert.equal(readAnswerTo({ answer_to: { message_id: 'm', part: 'p', kind: 'other', value: 'A' } }), null);
  assert.equal(readAnswerTo({ answer_to: { message_id: 1, part: 'p', kind: 'choice' } }), null);
});

// --- 直し2回目（確かめる役の指摘7）: HTML ブロック・引用の中はフェンスではない。鍵の見本（fixture）でサーバーと同じ鍵 ---
import { readFileSync } from 'node:fs';

test('HTML コメントの中の openui-lang は部品にしない（コメントの一部。文章側に残る）', () => {
  const fence = `\`\`\`openui-lang\n${CODE}\n\`\`\``;
  const comment = `<!--\n${fence}\n-->`;
  assert.deepEqual(splitShapeSegments(comment), [{ kind: 'markdown', text: comment }]);
  // 1行コメントの後の部品は本物。コメント＋本物の部品
  const mixed = `<!-- メモ -->\n\n${fence}`;
  assert.equal(splitShapeSegments(mixed).filter((s) => s.kind === 'shape').length, 1);
  const both = `${comment}\n\n${fence}`;
  const segs = splitShapeSegments(both);
  assert.equal(segs.filter((s) => s.kind === 'shape').length, 1);
  assert.equal(segs[0].kind, 'markdown');
  assert.ok(segs[0].text.includes('<!--') && segs[0].text.includes('-->'));
  // 閉じていないコメント: 末尾まで HTML ブロック
  assert.deepEqual(splitShapeSegments(`<!--\n${fence}`), [{ kind: 'markdown', text: `<!--\n${fence}` }]);
  // 生成中（streaming）でもコメントの中は部品にしない
  assert.equal(splitShapeSegments(comment, { streaming: true }).filter((s) => s.kind === 'shape').length, 0);
});

test('HTML ブロック: <pre>/<script> は閉じタグまで、<div> などは空行まで。空行の後の単独タグ（種類7）も。段落の途中の <span> は違う', () => {
  const fence = `\`\`\`openui-lang\n${CODE}\n\`\`\``;
  const shapes = (t) => splitShapeSegments(t).filter((s) => s.kind === 'shape').length;
  assert.equal(shapes(`<pre>\n${fence}\n</pre>\n\n${fence}`), 1);
  assert.equal(shapes(`<script>\n${fence}\n</script>`), 0);
  assert.equal(shapes(`<div>\n${fence}\n</div>\n\n${fence}`), 1);
  assert.equal(shapes(`<table>\n<tr><td>\n${fence}\n</td></tr>\n</table>`), 0);
  assert.equal(shapes(`\n<span>\n${fence}\n\n${fence}`), 1);          // 空行の後の単独タグ → 空行まで HTML
  assert.equal(shapes(`説明の段落\n<span>\n${fence}`), 1);             // 段落の途中の単独タグは HTML ブロックにならない
  assert.equal(shapes(`<https://example.com>\n${fence}`), 1);          // 自動リンクはタグではない
  assert.equal(shapes(`<?php\n${fence}\n?>`), 0);
  assert.equal(shapes(`<![CDATA[\n${fence}\n]]>`), 0);
  assert.equal(shapes(`<!DOCTYPE html>\n${fence}`), 1);                 // 1行で終わる種類4
});

test('引用（> ```）はフェンスではない。引用の後の本物の部品は部品', () => {
  const fence = `\`\`\`openui-lang\n${CODE}\n\`\`\``;
  const quoted = `> ${fence.replaceAll('\n', '\n> ')}`;
  assert.deepEqual(splitShapeSegments(quoted), [{ kind: 'markdown', text: quoted }]);
  assert.equal(splitShapeSegments(`${quoted}\n\n${fence}`).filter((s) => s.kind === 'shape').length, 1);
});

test('鍵の見本: tests/fixtures/chat_shapes_part_keys.json は今の split/answers と同じ（サーバー側の試験が同じ見本を読む）', () => {
  const cases = JSON.parse(readFileSync(new URL('./fixtures/chat_shapes_part_keys.json', import.meta.url), 'utf8'));
  assert.ok(cases.length >= 15);
  for (const c of cases) {
    const codes = splitShapeSegments(c.text).filter((s) => s.kind === 'shape').map((s) => s.code);
    assert.deepEqual(codes, c.codes, c.name);
    assert.deepEqual(partKeys(codes), c.keys, c.name);
  }
});
