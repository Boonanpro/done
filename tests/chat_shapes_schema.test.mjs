// 完成した部品の検証（frontend/src/lib/chat-shapes/schema.ts）と、OpenUI Lang の読み手（plain.ts）の試験。
// 実行: node --experimental-strip-types --test tests/chat_shapes_schema.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ChartProps, ChoiceProps, CompareProps, InputProps, StepsProps, SHAPE_SPECS, normalizeOptions, validateComplete,
} from '../frontend/src/lib/chat-shapes/schema.ts';
import { parseShapeCall } from '../frontend/src/lib/chat-shapes/plain.ts';

test('選択肢は空と重複を除いて2〜6個（完成時）', () => {
  for (const n of [0, 1, 7]) {
    assert.equal(ChoiceProps.safeParse({ question: 'Q', options: Array.from({ length: n }, (_, i) => String(i)) }).success, false, `${n} options`);
  }
  for (const n of [2, 6]) {
    assert.equal(ChoiceProps.safeParse({ question: 'Q', options: Array.from({ length: n }, (_, i) => String(i)) }).success, true, `${n} options`);
  }
  assert.equal(ChoiceProps.safeParse({ question: 'Q', options: ['A', ' A ', '', 'B'] }).success, true);   // 整えると2個
  assert.equal(ChoiceProps.safeParse({ question: 'Q', options: ['A', 'A', ''] }).success, false);       // 整えると1個
  assert.equal(ChoiceProps.safeParse({ question: '  ', options: ['A', 'B'] }).success, false);
  assert.deepEqual(normalizeOptions(['A', ' A ', '', 'B', 'B']), ['A', 'B']);
});

test('グラフ: 欠けた値を受け付けない（0 に補わない）。系列名の重複・label も不可', () => {
  assert.equal(ChartProps.safeParse({ kind: 'line', labels: ['a', 'b'], series: [{ name: 'x', values: [10] }] }).success, false);
  assert.equal(ChartProps.safeParse({ kind: 'line', labels: ['a', 'b'], series: [{ name: 'x', values: [10, 20] }] }).success, true);
  assert.equal(ChartProps.safeParse({ kind: 'bar', labels: ['a'], series: [{ name: 'x', values: [1] }, { name: 'x', values: [2] }] }).success, false);
  assert.equal(ChartProps.safeParse({ kind: 'bar', labels: ['a'], series: [{ name: 'label', values: [1] }] }).success, false);
  assert.equal(ChartProps.safeParse({ kind: 'bar', labels: [], series: [] }).success, false);
  assert.equal(ChartProps.safeParse({ kind: 'bar', labels: ['a'], series: [{ name: 'x', values: [Number.NaN] }] }).success, false);
});

test('表: 列は2つ以上、行は1つ以上、列より多いセルは不可（足りないセルは空欄で描く）', () => {
  assert.equal(CompareProps.safeParse({ columns: ['観点', 'A', 'B'], rows: [['費用', '1', '2'], ['速さ']] }).success, true);
  assert.equal(CompareProps.safeParse({ columns: ['観点'], rows: [['費用']] }).success, false);
  assert.equal(CompareProps.safeParse({ columns: ['観点', 'A'], rows: [] }).success, false);
  assert.equal(CompareProps.safeParse({ columns: ['観点', 'A'], rows: [['費用', '1', '余分']] }).success, false);
  assert.equal(CompareProps.safeParse({ columns: ['観点', ' '], rows: [['費用', '1']] }).success, false);
});

test('手順・入力欄', () => {
  assert.equal(StepsProps.safeParse({ steps: ['a'] }).success, true);
  assert.equal(StepsProps.safeParse({ steps: [' '] }).success, false);
  assert.equal(InputProps.safeParse({ label: '月の予算', kind: 'number', unit: '万円' }).success, true);
  assert.equal(InputProps.safeParse({ label: '' }).success, false);
});

test('validateComplete は知らない部品名と検証の理由を返す', () => {
  assert.deepEqual(validateComplete('Choice', { question: 'Q', options: ['A', 'B'] }), { ok: true });
  assert.equal(validateComplete('Unknown', {}).ok, false);
  const r = validateComplete('Chart', { kind: 'line', labels: ['a', 'b'], series: [{ name: 'x', values: [10] }] });
  assert.equal(r.ok, false);
  assert.match(r.reason, /値の数/);
  assert.equal(SHAPE_SPECS.length, 16);
  // 位置引数の順（refine を足しても zod の shape の順は変わらない＝lang-core の位置引数の順）
  assert.deepEqual(Object.keys(ChartProps.shape), ['kind', 'labels', 'series', 'unit', 'title']);
  assert.deepEqual(Object.keys(ChoiceProps.shape), ['question', 'options']);
});

test('OpenUI Lang の読み手: 文字列・数値・配列・{name: ...} の引数、壊れた書き方は null', () => {
  assert.deepEqual(parseShapeCall('root = Choice("進め方", ["A", "B"])'), { name: 'Choice', args: ['進め方', ['A', 'B']] });
  assert.deepEqual(
    parseShapeCall('root = Chart("line", ["a","b"], [{name: "x", values: [1, 2.5]}, {"name": "y", values: [-1, 0]}], "円")'),
    { name: 'Chart', args: ['line', ['a', 'b'], [{ name: 'x', values: [1, 2.5] }, { name: 'y', values: [-1, 0] }], '円'] },
  );
  assert.deepEqual(parseShapeCall('root = Input("予算", "number", "円", "例: 1500")'), { name: 'Input', args: ['予算', 'number', '円', '例: 1500'] });
  assert.deepEqual(parseShapeCall('  root=Steps(["a\\"b", "c"], "題")  '), { name: 'Steps', args: [['a"b', 'c'], '題'] });
  assert.equal(parseShapeCall('root = Choice("進め方", ["A", "B'), null);
  assert.equal(parseShapeCall('Choice("x", ["a","b"])'), null);
  assert.equal(parseShapeCall('root = Choice("x", ["a","b"]) extra'), null);
  assert.equal(parseShapeCall('root = Choice(question: "x", options: ["a"])'), null);
});
