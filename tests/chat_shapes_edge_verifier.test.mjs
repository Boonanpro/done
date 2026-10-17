// 確かめる役（GPT-6、2026-10-17 の独立検証 scratch/chat-shape/verify/edge.test.mjs）が書いた境界の試験。
// 作業ツリーに取り込むにあたり、import の場所と、答えの照合の呼び方（照合情報 answer_to になった）だけを直した。
// それ以外の中身と期待は確かめる役の物のまま。
// 実行: node --experimental-strip-types --test tests/chat_shapes_edge_verifier.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { splitShapeSegments } from '../frontend/src/lib/chat-shapes/split.ts';
import { findChoiceAnswer, findInputAnswer, partKey } from '../frontend/src/lib/chat-shapes/answers.ts';
import { ChoiceProps, ChartProps } from '../frontend/src/lib/chat-shapes/schema.ts';
const code = 'root = Choice("進め方", ["A", "B"])';
const fence = '```openui-lang\n' + code + '\n```';
test('all prefixes split without throwing', () => { for (let i = 0; i <= fence.length; i++) assert.doesNotThrow(() => splitShapeSegments(fence.slice(0, i), { streaming: true })); });
test('plain text and ordinary code stay byte identical', () => { for (const s of ['説明だけです', '```python\nprint(1)\n```', '```proposal\nplan.json\n```', '[確認: test]', '[送信案: test]']) assert.deepEqual(splitShapeSegments(s), [{ kind: 'markdown', text: s }]); });
test('unclosed final block stays code', () => assert.equal(splitShapeSegments(fence.slice(0, -3))[0].kind, 'markdown'));
test('tilde fenced example must not become interactive', () => assert.equal(splitShapeSegments('~~~markdown\n' + fence + '\n~~~').filter((s) => s.kind === 'shape').length, 0));
test('fence with extra info must protect contents', () => assert.equal(splitShapeSegments('````markdown title="example"\n' + fence + '\n````').filter((s) => s.kind === 'shape').length, 0));
test('CRLF shape should render', () => assert.equal(splitShapeSegments(fence.replaceAll('\n', '\r\n')).filter((s) => s.kind === 'shape').length, 1));
// 元: findChoiceAnswer(u, '進め方', ['A','B'], 100) — 後の返事（at=300）への答えを古い返事の答えにしない。
// 今は照合情報（返事の id + 部品の鍵）で結ぶので、別の返事 id への答えは当たらない
test('same question from a later card must not answer an older card', () => {
  const u = [{ text: '進め方 → A', at: 300, answerTo: { message_id: 'later', part: partKey(code), kind: 'choice', value: 'A' } }];
  assert.equal(findChoiceAnswer(u, 'older', partKey(code)), null);
});
// 元: findInputAnswer([{text:'予算 → まだ決めていません。相談したいです。', at:200}], '予算', 100) — 普通の発言は答えにしない
test('ordinary statement with matching prefix must not submit input', () => assert.equal(findInputAnswer([{ text: '予算 → まだ決めていません。相談したいです。', at: 200 }], 'm', 'p'), null));
test('choice requires between two and six options', () => { for (const n of [0, 1, 7]) assert.equal(ChoiceProps.safeParse({ question: 'Q', options: Array.from({ length: n }, (_, i) => String(i)) }).success, false); });
test('chart must not accept missing values as zero', () => assert.equal(ChartProps.safeParse({ kind: 'line', labels: ['a', 'b'], series: [{ name: 'x', values: [10] }] }).success, false));
