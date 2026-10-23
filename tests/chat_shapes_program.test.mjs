// 部品の組み合わせ（1つのブロックに複数の文・入れ子。2026-10-23）の試験。
// - 読み手 plain.ts parseShapeProgram が、Web の画面が使う lang-core と同じ木を読むか
// - 完成時の検証 schema.ts checkShapeProgram の決まり（中に部品を置けるのは Card・Row・Column だけ、答えの部品は1つまで、深さ、輪）
// - 部品を描けない画面の文章化と、アプリの写し（mobile/chat-shapes-plain.ts）が同じ出力か
// 実行: node --experimental-strip-types --test tests/chat_shapes_program.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

import { ShapeNode, parseShapeProgram, programDepth, safeLinkUrl, shapeToPlainMarkdown } from '../frontend/src/lib/chat-shapes/plain.ts';
import * as mobile from '../mobile/chat-shapes-plain.ts';
import { SHAPE_SPECS, checkShapeProgram } from '../frontend/src/lib/chat-shapes/schema.ts';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { createLibrary, defineComponent, createParser } = require('@openuidev/lang-core');
const lib = createLibrary({ components: SHAPE_SPECS.map((s) => defineComponent({ name: s.name, description: s.description, props: s.props, component: null })) });
const parser = createParser(lib.toJSONSchema());

/** 自前の木を lang-core の形（typeName と名前つきの props）にして比べる */
function asLangCore(v) {
  if (v instanceof ShapeNode) {
    const keys = Object.keys(SHAPE_SPECS.find((s) => s.name === v.name).props.shape);
    return { typeName: v.name, props: Object.fromEntries(v.args.map((a, i) => [keys[i], asLangCore(a)])) };
  }
  if (Array.isArray(v)) return v.map(asLangCore);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, asLangCore(x)]));
  return v;
}
function trimLangCore(v) {
  if (Array.isArray(v)) return v.map(trimLangCore);
  if (v && typeof v === 'object' && v.type === 'element') return { typeName: v.typeName, props: trimLangCore(v.props) };
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, trimLangCore(x)]));
  return v;
}

const ORDER = `root = Card([head, Row([total, eta]), Facts([{label: "店", value: "マクドナルド 尼崎駅前店"}, {label: "支払い", value: "Amex 末尾3004"}]), Row([Badge("注文済み", "good"), Button("注文を見る", "https://www.ubereats.com/orders")], "between")], "注文")
head = Heading("ビッグマックセット", "ポテトM・コーラM")
total = Stat("合計", 1135, "円")
eta = Stat("到着", "14:08〜14:19")`;

const PROGRAMS = [
  ORDER,
  'root = Choice("進め方", ["A", "B"])',
  'root = Column([Text("1行目"), "文字だけの子", Divider(), Steps(["a", "b"], "手順")])',
  'eta = Stat("到着", "14:08")\nroot = Card([eta, Choice("どれにする？", [{label: "赤", color: "#ff0000"}, "青"])])',
  "root = Card([Text('it\\'s'), Image(\"/api/v1/files/a.png\", \"写真\", \"square\")], \"題\", \"/api/v1/files/b.png\")",
];

test('lang-core と同じ木を読む（文の順・参照・入れ子・文字の子）', () => {
  for (const code of PROGRAMS) {
    const mine = parseShapeProgram(code);
    assert.ok(mine, code);
    const theirs = parser.parse(code);
    assert.deepEqual(theirs.meta.errors, [], code);
    assert.deepEqual(asLangCore(mine), trimLangCore(theirs.root), code);
  }
});

test('読めない書き方は null（同じ名前2つ・知らない名前・輪・root が無い・部品でない root）', () => {
  for (const code of [
    'root = Card([a])', 'root = Card([a])\na = Card([root])', 'root = Text("a")\nroot = Text("b")', 'x = Text("a")',
    'root = "ただの文字"', 'root = Card([Text("a")]', 'root = Card([$x])', 'root = @Each(1)',
  ]) assert.equal(parseShapeProgram(code), null, code);
});

test('大きすぎる組み合わせは読まない（同じ文を何度も指して増やす書き方）', () => {
  const lines = ['root = Column([a, a, a, a, a, a, a, a, a, a])', 'a = Row([b, b, b, b, b, b, b, b, b, b])', 'b = Text("x")'];
  assert.equal(parseShapeProgram(lines.join('\n')), null);
});

test('完成時の検証: 組み合わせの決まり', () => {
  assert.equal(checkShapeProgram(ORDER).ok, true);
  const cases = [
    ['root = Text(Badge("x"))', /部品は書けない/],
    ['root = Facts([{label: Badge("x"), value: "1"}])', /部品は書けない/],
    ['root = Card([Choice("a", ["x", "y"]), Input("b")])', /1つまで/],
    ['root = Card([])', /中身が無い/],
    ['root = Card([1, 2])', /部品か文字/],
    ['root = Nope("x")', /知らない部品/],
    ['root = Stat("合計")', /value/],
    ['root = Card([Card([Card([Card([Card([Card([Card([Text("深い")])])])])])])])', /深すぎる/],
  ];
  for (const [code, why] of cases) {
    const r = checkShapeProgram(code);
    assert.equal(r.ok, false, code);
    assert.match(r.reason, why, code);
  }
  assert.equal(programDepth(parseShapeProgram('root = Card([Row([Text("a")])])')), 3);
});

test('ボタンの行き先は https:// とこのサイトの道だけ', () => {
  for (const ok of ['https://example.com/a?b=1', '/artifacts/x', '/api/v1/files/a.pdf']) assert.equal(safeLinkUrl(ok), ok);
  for (const ng of ['javascript:alert(1)', 'http://example.com', '//evil.example', 'https://user:pw@example.com', 'data:text/html,x', '/a b', '/a\\b'])
    assert.equal(safeLinkUrl(ng), null, ng);
});

test('部品を描けない画面の文章: 組み合わせの中身を順に、アプリの写しも同じ', () => {
  const plain = shapeToPlainMarkdown(ORDER);
  assert.match(plain, /^\*\*注文\*\*/);
  assert.match(plain, /合計: \*\*1,135円\*\*　／　到着: \*\*14:08〜14:19\*\*/);
  assert.match(plain, /- 支払い: Amex 末尾3004/);
  assert.match(plain, /\[注文を見る\]\(https:\/\/www\.ubereats\.com\/orders\)/);
  assert.equal(shapeToPlainMarkdown('root = Button("押す", "javascript:alert(1)")'), '押す');
  for (const code of PROGRAMS) assert.equal(mobile.shapeToPlainMarkdown(code), shapeToPlainMarkdown(code), code);
});

test('アプリの答えの写しは本体と同じ中身', async () => {
  const { readFileSync } = await import('node:fs');
  const body = readFileSync(new URL('../frontend/src/lib/chat-shapes/answers.ts', import.meta.url), 'utf8');
  const copy = readFileSync(new URL('../mobile/chat-shapes-answers.ts', import.meta.url), 'utf8');
  assert.equal(copy.split('\n').slice(3).join('\n'), body);
});
