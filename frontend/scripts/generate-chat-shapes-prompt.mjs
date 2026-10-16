// ダンの返事に出す部品（frontend/src/lib/chat-shapes/schema.ts）から、ダンの最初の指示に足す文を作り、
// app/agent/chat_shapes_prompt.md に書く。部品の一覧の行は @openuidev/lang-core の prompt() が作る
// （画面の部品定義と指示文がずれない）。それ以外の文は短く固定（生成される全文は長すぎて
// ダッシュボード前提の説明が多いので、使わない）。
//
// 実行（frontend で）: npm run generate:shapes
//   = node --experimental-strip-types scripts/generate-chat-shapes-prompt.mjs
// 確認: tests/chat_shapes_prompt.test.mjs が「書かれている md と今の部品定義が一致する」ことを見る。
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { createLibrary, defineComponent } from '@openuidev/lang-core';
import { ANSWER_QUESTION_MAX, ANSWER_VALUE_MAX, SHAPE_SPECS } from '../src/lib/chat-shapes/schema.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
export const PROMPT_PATH = resolve(HERE, '../../app/agent/chat_shapes_prompt.md');

/** lang-core の prompt() から「部品の一覧」の行だけを取り出す。 */
export function shapeSignatureLines() {
  const lib = createLibrary({
    components: SHAPE_SPECS.map((s) =>
      defineComponent({ name: s.name, description: s.description, props: s.props, component: null }),
    ),
  });
  const full = lib.prompt();
  const start = full.indexOf('## Component Signatures');
  if (start < 0) throw new Error('lang-core prompt has no Component Signatures section');
  const end = full.indexOf('\n## ', start + 1);
  const section = full.slice(start, end < 0 ? undefined : end);
  const names = new Set(SHAPE_SPECS.map((s) => s.name));
  const lines = section
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => names.has(l.split('(')[0]));
  if (lines.length !== SHAPE_SPECS.length) {
    throw new Error(`expected ${SHAPE_SPECS.length} signature lines, got ${lines.length}`);
  }
  return lines;
}

export function buildChatShapesPrompt() {
  const sig = shapeSignatureLines().map((l) => `- ${l}`).join('\n');
  return `## Answer shapes (chat UI parts)

Plain prose is the default. Use a part only when it serves the user better than sentences: comparing candidates side by side (Compare, in place of a Markdown table), letting the user pick one of 2-6 options (Choice), asking for one number or short value (Input), listing steps the user will follow (Steps), or showing numbers over time or by category (Chart). Greetings, explanations, status reports, yes/no questions and ordinary answers stay prose. An irreversible confirmation is confirm_card, a message to someone else is compose_message; never a part.

Write a part as one fenced code block with the language \`openui-lang\` containing one statement \`root = Part(...)\`, placed between your sentences (introduce it in the sentence before). Arguments are positional in the order below; strings use double quotes; trailing optional arguments can be omitted; never use name: value syntax. One part per block; several blocks in one reply are fine. Do not put a part inside another code block, an HTML comment or a list item. Keep a Choice question or Input label within ${ANSWER_QUESTION_MAX} characters and each option within ${ANSWER_VALUE_MAX}.

Parts (generated from the chat UI; ? = optional):
${sig}

When the user presses a Choice or submits an Input, the answer arrives as the user's own chat message in the form \`<question> → <answer>\`. After asking with Choice or Input, end the turn and wait for it; do not guess the answer. A Choice question is answered only through the message; do not restate the options as a list. When the answer hinges on one number only the user knows (a budget, hours per week, a head count), ask for it with Input instead of assuming it.

Example:
どちらで進めますか？

\`\`\`openui-lang
root = Choice("進め方", ["先に見積もりを取る", "今すぐ発注する"])
\`\`\`
`;
}

export function readWrittenPrompt() {
  return readFileSync(PROMPT_PATH, 'utf8');
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const text = buildChatShapesPrompt();
  writeFileSync(PROMPT_PATH, text, 'utf8');
  console.log(`wrote ${PROMPT_PATH} (${text.length} chars)`);
}
