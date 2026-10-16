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

test('部品5つの名前が全部、指示文の一覧に出ている。長さは2.5KB以内', () => {
  const lines = shapeSignatureLines();
  assert.deepEqual(lines.map((l) => l.split('(')[0]), [...SHAPE_NAMES]);
  assert.equal(SHAPE_NAMES.length, 5);
  const text = buildChatShapesPrompt();
  assert.ok(text.includes('```openui-lang'));
  assert.ok(text.length <= 2500, `prompt is ${text.length} chars`);
});
