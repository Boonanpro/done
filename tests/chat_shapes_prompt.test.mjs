// 指示文（app/agent/chat_shapes_prompt.md）が今の部品定義（schema.ts）から作り直した物と一致するか。
// ずれていたら frontend で `npm run generate:shapes` を実行して md を書き直す。
// 実行: node --experimental-strip-types --test tests/chat_shapes_prompt.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildChatShapesPrompt, readWrittenPrompt, shapeSignatureLines,
} from '../frontend/scripts/generate-chat-shapes-prompt.mjs';
import { SHAPE_NAMES } from '../frontend/src/lib/chat-shapes/schema.ts';

test('書かれている指示文は、部品定義から作った物と同じ', () => {
  assert.equal(readWrittenPrompt().replace(/\r\n/g, '\n'), buildChatShapesPrompt());
});

// 長さの上限: 比べる質問の一文と「実物を出す」の段落を足した時（2026-10-17）に 2,500 → 3,400 字、
// 組み合わせる小さな部品11個と組み方・例を足した時（2026-10-23）に 3,400 → 5,400 字
test('部品17個の名前が全部、指示文の一覧に出ている。長さは7KB以内', () => {
  const lines = shapeSignatureLines();
  assert.deepEqual(lines.map((l) => l.split('(')[0]), [...SHAPE_NAMES]);
  assert.equal(SHAPE_NAMES.length, 17);
  const text = buildChatShapesPrompt();
  assert.ok(text.includes('```openui-lang'));
  assert.ok(text.length <= 7000, `prompt is ${text.length} chars`);   // 2026-10-25: Flow and its icon names
});
