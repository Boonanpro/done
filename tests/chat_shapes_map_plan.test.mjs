// ダン自身の直す所を指示文の地図に結んで見せる部品 MapPlan（2026-11-27）
// 実行: node --experimental-strip-types --test tests/chat_shapes_map_plan.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { checkShapeProgram } = await import('../frontend/src/lib/chat-shapes/schema.ts');
const { shapeToPlainMarkdown } = await import('../frontend/src/lib/chat-shapes/plain.ts');
const { BOARD_NODES } = await import('../frontend/src/components/prompts/architecture.ts');

const PLAN = `root = MapPlan([{node: "router", title: "問いはその場で答える", now: "「聞いてる？」で22秒黙る", after: "声のダンがすぐ返す", effect: "待ちが22秒→1秒"}, {node: "editorTalk", title: "受け取った中身を一言", now: "「うん」だけ", after: "「3つだね」と返す"}], "声の直す順", "ぼーっとした間が無くなる")`;

test('直す所を地図の箱に結んだ案が通り、文章でも読める', () => {
  assert.equal(checkShapeProgram(PLAN).ok, true);
  const md = shapeToPlainMarkdown(PLAN);
  assert.match(md, /1\. \*\*問いはその場で答える\*\*（router）/);
  assert.match(md, /直した後: 「3つだね」と返す/);
  assert.match(md, /→ ぼーっとした間が無くなる/);
});

test('今か直した後が無い・多すぎる・箱の名前の形が違う案は通さない', () => {
  assert.equal(checkShapeProgram('root = MapPlan([{node: "router", title: "x", now: "", after: "y"}])').ok, false);
  assert.equal(checkShapeProgram('root = MapPlan([{node: "ルーター", title: "x", now: "a", after: "b"}])').ok, false);
  const many = Array.from({ length: 9 }, () => '{node: "chat", title: "x", now: "a", after: "b"}').join(', ');
  assert.equal(checkShapeProgram(`root = MapPlan([${many}])`).ok, false);
});

test('地図の箱の id はどれも部品の決まりの形に合う', () => {
  for (const n of BOARD_NODES) assert.match(n.id, /^[A-Za-z0-9-]{1,40}$/, n.id);
});
