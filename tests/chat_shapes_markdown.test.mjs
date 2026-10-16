// 部品のコードブロックの読み手（plain.ts topLevelFences / shapeFences。split.ts と mobile の写しも同じ）を、
// Web の文章の描画（react-markdown＋remark-gfm）と同じ Markdown の読み手 remark-parse＋remark-gfm（micromark）の
// 構文木と突き合わせる。
// - 確かめる役の27入力（HTML の境界・空白の定義）: Web の切り出し・mobile の文章変換・remark が同じ部品を見る
// - 段落・入れ物・HTML・空白・タブ・改行・言語名・GFM の表と脚注の境目を狙った入力と、種つきの乱数で並べた入力:
//   一番外側のフェンスのコードブロック（位置・閉じ・言語名・中身）が remark と一致する
// サーバー（app/agent/chat_shapes.py）は tests/fixtures/chat_shapes_markdown_corpus.json で同じ答えを見る
// （test_chat_shapes_markdown.py。見本の書き直しは tests/fixtures/make_chat_shapes_markdown_corpus.mjs）。
// 実行: node --experimental-strip-types --test tests/chat_shapes_markdown.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { splitShapeSegments } from '../frontend/src/lib/chat-shapes/split.ts';
import { partKeys } from '../frontend/src/lib/chat-shapes/answers.ts';
import { replaceShapeBlocks, topLevelFences } from '../frontend/src/lib/chat-shapes/plain.ts';
import { replaceShapeBlocks as mobileReplace, topLevelFences as mobileFences } from '../mobile/chat-shapes-plain.ts';
import { verifierCases, targetedCases, generatedCases } from './fixtures/chat_shapes_markdown_cases.mjs';
import { remarkFences, oursFences, comparable } from './fixtures/chat_shapes_markdown_oracle.mjs';

const remarkShapeCodes = (text) => remarkFences(text).filter((f) => f.shape && f.closed).map((f) => f.code);
const webShapeCodes = (text) => splitShapeSegments(text).filter((s) => s.kind === 'shape').map((s) => s.code);

test('確かめる役の27入力: Web の切り出し・mobile の文章変換・remark-parse が同じ部品を見る（鍵も同じ）', () => {
  const cases = verifierCases();
  assert.equal(cases.length, 27);
  for (const { name, text } of cases) {
    const want = remarkShapeCodes(text);
    assert.deepEqual(webShapeCodes(text), want, name);
    assert.deepEqual(partKeys(webShapeCodes(text)), partKeys(want), name);
    assert.equal(mobileReplace(text), replaceShapeBlocks(text), name);
    assert.deepEqual(mobileFences(text), topLevelFences(text), name);
  }
});

test('HTML の境界: 見出し・閉じたフェンス・コメント・字下げコードの後の単独タグは HTML ブロック（中の部品は描かない）', () => {
  const byName = Object.fromEntries(verifierCases().map((c) => [c.name, c.text]));
  for (const name of ['htmlAfterHeading', 'htmlAfterFence', 'htmlAfterComment', 'indented', 'comment', 'pre', 'div']) {
    assert.deepEqual(webShapeCodes(byName['verifier:' + name]), [], name);
  }
  // 段落の途中の単独タグは段落の続き（部品は描く）
  assert.equal(webShapeCodes(byName['verifier:htmlParagraph']).length, 1);
});

test('空白は半角スペースとタブだけ: NEL・BOM・NBSP・U+2028/2029・全角空白はタグの区切りにならない（部品を描く）。タブはなる', () => {
  const byName = Object.fromEntries(verifierCases().map((c) => [c.name, c.text]));
  for (const w of ['nbsp', 'bom', 'nel', 'ls', 'ps', 'ideographic']) assert.equal(webShapeCodes(byName['verifier:html-ws-' + w]).length, 1, w);
  assert.equal(webShapeCodes(byName['verifier:html-ws-tab']).length, 0);
});

test('狙った入力: 一番外側のフェンスのコードブロックが remark-parse＋remark-gfm と一致する', () => {
  const cases = targetedCases();
  assert.ok(cases.length >= 90);
  for (const { name, text } of cases) {
    const [ours, theirs] = comparable(oursFences(text), remarkFences(text));
    assert.equal(ours, theirs, name);
  }
});

test('種つきの乱数で並べた3000の入力: remark-parse＋remark-gfm と一致する', () => {
  let shapes = 0;
  for (const { name, text } of generatedCases(20261017, 3000)) {
    const theirs = remarkFences(text);
    const [a, b] = comparable(oursFences(text), theirs);
    assert.equal(a, b, name + ' ' + JSON.stringify(text));
    shapes += theirs.filter((f) => f.shape).length;
  }
  assert.ok(shapes > 300, `部品のブロックを含む入力が十分にある (${shapes})`);
});

test('サーバーが読む見本（chat_shapes_markdown_corpus.json）は今の読み手と remark-parse＋remark-gfm の答えのまま', () => {
  const rows = JSON.parse(readFileSync(new URL('./fixtures/chat_shapes_markdown_corpus.json', import.meta.url), 'utf8'));
  assert.ok(rows.length > 600);
  for (const row of rows) {
    const theirs = remarkFences(row.text);
    assert.deepEqual(row.fences, theirs.map((f) => ({ closed: f.closed, shape: f.shape, code: f.code })), row.name);
    assert.deepEqual(row.shape_codes, webShapeCodes(row.text), row.name);
    assert.deepEqual(row.keys, partKeys(row.shape_codes), row.name);
  }
});

const PART = '```openui-lang\nroot = Choice("Q", ["A", "B"])\n```';
const indent = (n, s) => ' '.repeat(n) + s.replaceAll('\n', '\n' + ' '.repeat(n));

test('GFM の表（VERIFY4 P2-5）: Web が実際に描く remark-gfm と同じく、表の直後の単独タグは HTML（中の部品は描かない。4か所とも）', () => {
  const verifier = '| a |\n| - |\n<span>\n' + PART + '\n</span>';      // 確かめる役の再現
  assert.equal(remarkFences(verifier).length, 0);
  assert.equal(remarkFences(verifier, { gfm: false }).length, 1);       // CommonMark だけなら部品（前の読み手の答え）
  assert.deepEqual(webShapeCodes(verifier), []);
  assert.deepEqual(mobileFences(verifier), []);
  assert.equal(mobileReplace(verifier), verifier);                     // スマホも部品として書き換えない
  // 表の後に空行がある・表の直後がフェンス・表の行の後のフェンスなら部品（GFM でも同じ）
  for (const t of ['| a |\n| - |\n\n' + PART, '| a |\n| - |\n' + PART, '| a |\n| - |\n| b |\n※税込\n' + PART]) {
    assert.equal(webShapeCodes(t).length, 1, t);
  }
  // 表は段落を切る。表の後は単独タグが HTML を始め（空行まで）、2. や空の項目の箇条書きも始まる（字下げした部品はその中）
  for (const t of ['text\n| a |\n| - |\n<span>\n' + PART, '| a |\n| - |\n2. x\n\n' + indent(3, PART),
    '| a |\n| - |\n-\n' + indent(2, PART), '| a |\n| - |\n<span>\n# h\n' + PART, 'x\n<span>\n| - |\n<i>\n' + PART]) {
    assert.deepEqual(webShapeCodes(t), [], t);
    assert.equal(remarkFences(t).filter((f) => f.shape).length, 0, t);
  }
});

test('GFM の脚注の定義は入れ物: 4列字下げの部品はその中（一番外側ではない）。段落の途中でも始まる', () => {
  for (const t of ['[^1]: note\n' + indent(4, PART), 'text\n[^1]: note\n' + indent(4, PART), '[^1]: note\n\n' + indent(4, PART)]) {
    assert.deepEqual(webShapeCodes(t), [], t);
    assert.equal(remarkFences(t).length, 0, t);
  }
  assert.equal(webShapeCodes('[^1]: note\n' + indent(2, PART)).length, 1);   // 字下げが4列でなければ外
});
