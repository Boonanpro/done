// 部品のコードブロックの読み手（plain.ts topLevelFences / shapeFences。split.ts と mobile の写しも同じ）を、
// Web の文章の描画と同じ Markdown の読み手 remark-parse（micromark）の構文木と突き合わせる。
// - 確かめる役の27入力（HTML の境界・空白の定義）: Web の切り出し・mobile の文章変換・remark が同じ部品を見る
// - 段落・入れ物・HTML・空白・タブ・改行・言語名の境目を狙った入力と、種つきの乱数で並べた入力: 一番外側の
//   フェンスのコードブロック（位置・閉じ・言語名・中身）が remark と一致する
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

test('狙った入力: 一番外側のフェンスのコードブロックが remark-parse と一致する', () => {
  const cases = targetedCases();
  assert.ok(cases.length >= 90);
  for (const { name, text } of cases) {
    const [ours, theirs] = comparable(oursFences(text), remarkFences(text));
    assert.equal(ours, theirs, name);
  }
});

test('種つきの乱数で並べた3000の入力: remark-parse と一致する', () => {
  let shapes = 0;
  for (const { name, text } of generatedCases(20261017, 3000)) {
    const theirs = remarkFences(text);
    const [a, b] = comparable(oursFences(text), theirs);
    assert.equal(a, b, name + ' ' + JSON.stringify(text));
    shapes += theirs.filter((f) => f.shape).length;
  }
  assert.ok(shapes > 300, `部品のブロックを含む入力が十分にある (${shapes})`);
});

test('サーバーが読む見本（chat_shapes_markdown_corpus.json）は今の読み手と remark-parse の答えのまま', () => {
  const rows = JSON.parse(readFileSync(new URL('./fixtures/chat_shapes_markdown_corpus.json', import.meta.url), 'utf8'));
  assert.ok(rows.length > 600);
  for (const row of rows) {
    const theirs = remarkFences(row.text);
    assert.deepEqual(row.fences, theirs.map((f) => ({ closed: f.closed, shape: f.shape, code: f.code })), row.name);
    assert.deepEqual(row.shape_codes, webShapeCodes(row.text), row.name);
    assert.deepEqual(row.keys, partKeys(row.shape_codes), row.name);
  }
});

test('既知の違い（Web は remark-gfm も使う）: GFM の表のすぐ後の単独タグの行は、GFM では HTML、CommonMark では段落', () => {
  // この読み手は CommonMark（remark-parse）に合わせる。表の直後に空行なしで単独タグの行とフェンスが続く時だけ、
  // GFM の描画とは違って部品を描く（サーバーも同じ読み手なので、描いた部品の答えは受け付けられる）
  const text = '| a | b |\n|---|---|\n<span>\n```openui-lang\nroot = Choice("Q", ["A", "B"])\n```';
  assert.equal(remarkFences(text).length, 1);
  assert.equal(remarkFences(text, { gfm: true }).length, 0);
  assert.equal(webShapeCodes(text).length, 1);
  // 表の後に空行がある・表の直後がフェンス、ならどちらでも同じ
  for (const t of ['| a | b |\n|---|---|\n\n```openui-lang\nx\n```', '| a | b |\n|---|---|\n```openui-lang\nx\n```']) {
    assert.equal(remarkFences(t, { gfm: true }).length, remarkFences(t).length, t);
  }
});
