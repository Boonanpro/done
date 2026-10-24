// 部品の組み合わせ（1つのブロックに複数の文・入れ子。2026-10-23）の試験。
// - 読み手 plain.ts parseShapeProgram が、Web の画面が使う lang-core と同じ木を読むか
// - 完成時の検証 schema.ts checkShapeProgram の決まり（中に部品を置けるのは Card・Row・Column だけ、答えの部品は1つまで、深さ、輪）
// - 部品を描けない画面の文章化と、アプリの写し（mobile/chat-shapes-plain.ts）が同じ出力か
// 実行: node --experimental-strip-types --test tests/chat_shapes_program.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, readFileSync } from 'node:fs';

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

test('スマホの写しは、写す道具が今の中身から作る物と同じ（読み手・検査・答えの送信・グラフ・報告の札）', async () => {
  const { readFileSync } = await import('node:fs');
  const { COPIES, mobileCopy } = await import('../frontend/scripts/sync-mobile-chat-shapes.mjs');
  for (const [name, copy] of Object.entries(COPIES)) {
    const written = readFileSync(new URL(`../mobile/${copy}`, import.meta.url), 'utf8').replace(/\r\n/g, '\n');
    assert.equal(written, mobileCopy(name), `mobile/${copy} が古い（frontend で npm run sync:mobile-shapes）`);
  }
});

test('グラフの形: 棒は0の線から上下、折れ線は欠けた値で切れる、種類を取り違えない', async () => {
  const { chartGeometry } = await import('../frontend/src/lib/chat-shapes/chart-geometry.ts');
  const bar = chartGeometry({ kind: 'bar', labels: ['1月', '2月', '3月'], series: [{ name: '損益', values: [30, -20, 10] }], unit: '万円' }, 400);
  assert.equal(bar.kind, 'bar');
  const [b1, b2] = bar.series[0].bars;
  assert.ok(Math.abs(b1.y + b1.h - bar.zeroY) < 0.01, '正の棒は0の線まで');
  assert.ok(Math.abs(b2.y - bar.zeroY) < 0.01, '負の棒は0の線から下へ');
  assert.ok(bar.yTicks.some((t) => t.zero), '0の目盛りがある');
  const line = chartGeometry({ kind: 'line', labels: ['a', 'b', 'c', 'd'], series: [{ name: 'x', values: [1, null, 3, 4] }] }, 400);
  assert.equal(line.kind, 'line');
  assert.equal(line.series[0].points.length, 3);
  assert.equal((line.series[0].path.match(/M/g) || []).length, 2, '欠けた値で線が2本に分かれる');
  const many = chartGeometry({ kind: 'bar', labels: Array.from({ length: 30 }, (_, i) => `ラベル${i}`), series: [{ name: 'x', values: Array(30).fill(1) }] }, 300);
  assert.ok(many.xLabels.length < 30, '重なる名前は間引く');
});

test('並行作業の報告の札: 印つき・印の無い古い報告・止まった知らせ・ふつうの返事', async () => {
  const { readJobReport } = await import('../frontend/src/lib/chat-shapes/job-report.ts');
  const marked = readJobReport({ job_report: { title: '返事の短さの点検', state: 'done' } }, '**【並行作業：あなたは…】**\n\n確認は完了しました。');
  assert.deepEqual(marked, { title: '返事の短さの点検', state: 'done', body: '確認は完了しました。' });
  const old = readJobReport(null, '**【並行作業：検索をDeepSeekに】**\n\n作業を停止しました: Codex error');
  assert.equal(old.title, '検索をDeepSeekに');
  assert.equal(old.state, 'stopped');
  assert.equal(readJobReport(null, '了解、注文するね'), null);
  assert.equal(readJobReport({ blocks: [] }, '並行作業の話をしよう'), null);
});

test('アプリの答えの写しは本体と同じ中身', async () => {
  const { readFileSync } = await import('node:fs');
  const body = readFileSync(new URL('../frontend/src/lib/chat-shapes/answers.ts', import.meta.url), 'utf8');
  const copy = readFileSync(new URL('../mobile/chat-shapes-answers.ts', import.meta.url), 'utf8');
  assert.equal(copy.split('\n').slice(3).join('\n'), body);
});

// 作業中の1行と、押すと開く一覧（2026-10-24。本人「考えています」だけの時間が超長くて遅く感じる」「準備していますはダメ」）
test('作業中の1行: 道具の言葉・思考の要約・返事を書いています・考えています', async () => {
  const L = await import('../frontend/src/lib/chat-shapes/live-line.ts');
  const t0 = Date.parse('2026-10-24T10:00:00');
  assert.equal(L.liveLineText([]), '考えています');
  assert.equal(L.liveLineText([{ kind: 'thinking', text: 'まず画面を確かめる。次に、お店のページを開きます。', at: t0 }]), '次に、お店のページを開きます。');
  // 英語の思考は出さない（前の一歩の言葉のまま）
  assert.equal(L.liveLineText([{ kind: 'tool', activity: 'お店のページを見ています', at: t0 }, { kind: 'thinking', text: 'Let me check.', at: t0 + 1 }]), 'お店のページを見ています');
  assert.equal(L.liveLineText([{ kind: 'tool', activity: '注文の画面を開いています', at: t0 }, { kind: 'text', text: '注文できたよ', at: t0 + 1 }]), '返事を書いています');
  assert.equal(L.elapsedText(t0, t0 + 14_000), '14秒');
  assert.equal(L.elapsedText(t0, t0 + 65_000), '1分05秒');
  assert.equal(L.elapsedText(t0, t0 + 3_725_000), '1時間02分');
  for (const s of [L.liveLineText([]), ...L.liveRows([], t0, t0).map((r) => r.label)]) assert.ok(!s.includes('準備'), s);
});

test('作業中の一覧: 時刻・かかった秒数・同じ言葉はまとめる・書きかけの返事は中身を出さない', async () => {
  const L = await import('../frontend/src/lib/chat-shapes/live-line.ts');
  const t0 = Date.parse('2026-10-24T10:00:00');
  const rows = L.liveRows([
    { kind: 'tool', activity: 'お店のページを見ています', at: t0 + 5_000 },
    { kind: 'tool', activity: 'お店のページを見ています', at: t0 + 9_000 },
    { kind: 'text', text: 'カートを確かめます。', at: t0 + 13_000 },
    { kind: 'tool', activity: '注文の画面を開いています', at: t0 + 14_000 },
    { kind: 'text', text: '注文できたよ。合計1,135円', at: t0 + 20_000 },
  ], t0 + 26_000, t0);
  assert.deepEqual(rows.map((r) => [r.label, r.count, r.seconds, r.now]), [
    ['考えています', 1, 5, false],
    ['お店のページを見ています', 2, 8, false],
    ['カートを確かめます。', 1, 1, false],
    ['注文の画面を開いています', 1, 6, false],
    ['返事を書いています', 1, 6, true],
  ]);
  assert.equal(L.clockText(t0 + 5_000), '10:00:05');
  // 秒数の起点: 最後の返事より後に送った一番早い発言（追い連絡で数え直さない）。30分より前の発言は使わない
  assert.equal(L.liveStartedAt(t0 + 3_000, [t0, t0 + 40_000]), t0);
  assert.equal(L.liveStartedAt(t0 + 3_000, [t0 - 3_600_000]), t0 + 3_000);
  assert.equal(L.liveStartedAt(null, [t0]), t0);
  assert.deepEqual(L.sentSinceReply([
    { sender_type: 'human', created_at: '2026-10-24T09:00:00Z' },
    { sender_type: 'ai', created_at: '2026-10-24T09:01:00Z' },
    { sender_type: 'human', created_at: '2026-10-24T09:05:00Z' },
    { sender_type: 'human', created_at: '2026-10-24T09:05:40Z' },
  ]), [Date.parse('2026-10-24T09:05:00Z'), Date.parse('2026-10-24T09:05:40Z')]);
});

// 2026-10-24 見直し: 日本語の後に続く英語の文がそのまま出ていた・「準備しています」が残っていた
test('作業中の1行: 文ごとに判定し、英語が主の文は出さず、準備・起動の言葉は「考えています」', async () => {
  const L = await import('../frontend/src/lib/chat-shapes/live-line.ts');
  const t0 = Date.parse('2026-10-24T10:00:00');
  assert.equal(L.shownLine('まず画面を確かめる。Let me check the cart first.'), 'まず画面を確かめる。');
  assert.equal(L.shownLine('Let me check. 次に、お店のページを開きます。'), '次に、お店のページを開きます。');
  assert.equal(L.shownLine('Now I will open the 設定 page.'), '');
  assert.equal(L.shownLine('GitHub の PR を作ります。'), 'GitHub の PR を作ります。');
  for (const t of ['準備しています。', '今、準備中です', '起動しています'])
    assert.equal(L.shownLine(t), '考えています', t);
  const ev = (event_type, content, metadata, s) => ({ event_type, content, metadata, created_at: new Date(t0 + s * 1000).toISOString() });
  const events = [
    ev('reasoning', '準備しています。', { kind: 'thinking' }, 1),
    ev('tool_use', null, { activity: 'お店のページを見ています' }, 3),
    ev('reasoning', 'カートを確かめた。Let me open the order page now.', { kind: 'thinking' }, 6),
    ev('reasoning', 'Thinking...', null, 7),
  ];
  const steps = L.liveStepsFromEvents(events);
  assert.equal(steps.length, 3);
  assert.equal(L.liveLineText(steps), 'カートを確かめた。');
  const rows = L.liveRows(steps, t0 + 10_000, t0).map((r) => r.label);
  assert.deepEqual(rows, ['考えています', 'お店のページを見ています', 'カートを確かめた。']);
  for (const r of rows) assert.ok(!/[A-Za-z]{3}/.test(r) && !r.includes('準備'), r);
  // 英語だけの思考なら、1行は前の道具の言葉のまま
  assert.equal(L.liveLineText(L.liveStepsFromEvents([events[1], ev('reasoning', 'Checking the cart.', { kind: 'thinking' }, 8)])), 'お店のページを見ています');
});

test('PC・スマホ・開発室とも、作業中の1行は同じ関数を通る（自前の変換を持たない）', () => {
  const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
  const pc = read('../frontend/src/components/layout/project-chat-panel.tsx');
  assert.match(pc, /from '@\/lib\/chat-shapes\/live-line'/);
  for (const fn of ['liveStepsFromEvents', 'liveStartedAt', 'sentSinceReply', 'liveLineText', 'liveRows']) assert.ok(pc.includes(fn), `PC: ${fn}`);
  const phone = read('../mobile/chatTimeline.ts') + read('../mobile/live-line-view.tsx');
  assert.match(phone, /from '\.\/chat-shapes-live-line'/);
  for (const fn of ['liveStepsFromEvents', 'liveStartedAt', 'sentSinceReply', 'liveLineText', 'liveRows']) assert.ok(phone.includes(fn), `スマホ: ${fn}`);
  for (const src of [pc, phone]) assert.ok(!/function (toLiveSteps|liveStepsOf)\b/.test(src), '自前の変換が残っている');
  // 開発室の画面は git の外（成果物）。この場所にある時だけ見る
  const dev = new URL('../frontend/src/app/artifacts/dev-lead/page-body.tsx', import.meta.url);
  if (existsSync(dev)) {
    const src = readFileSync(dev, 'utf8');
    for (const fn of ['liveStepsFromEvents', 'liveStartedAt', 'sentSinceReply', 'liveLineText', 'liveRows']) assert.ok(src.includes(fn), `開発室: ${fn}`);
    assert.ok(!/function liveStepsOf\b/.test(src), '開発室に自前の変換が残っている');
  }
});
