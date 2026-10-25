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
import { PROGRAM_DEPTH_MAX } from '../src/lib/chat-shapes/plain.ts';

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
    .filter((l) => names.has(l.split('(')[0]))
    // 子の一覧（Card・Row・Column の children）は lang-core では any[]。読み手に分かるよう「部品の一覧」と書く
    .map((l) => l.replace(/children: any\[\]/g, 'children: (Part | string)[]'));
  if (lines.length !== SHAPE_SPECS.length) {
    throw new Error(`expected ${SHAPE_SPECS.length} signature lines, got ${lines.length}`);
  }
  return lines;
}

export function buildChatShapesPrompt() {
  const sig = shapeSignatureLines().map((l) => `- ${l}`).join('\n');
  return `## Answer shapes (chat UI parts)

Prose is the default. When seeing beats reading, show it with parts instead of more sentences: a result with facts the user will check (an order with its total and arrival time, a booking, a price), candidates side by side, a choice for the user, numbers over time, steps the user will follow. Who sends what to whom, how a thing moves, or where the user is in a process is a Flow (icon boxes with arrows, tone now = here), not a list. Put the one or two sentences you would say first, then the part; do not repeat in prose what the part shows. Facts you looked up keep their sources: give each looked-up item a labelled link (a Button on the item, or links in the sentence after the part), so the user can check them. Greetings, short answers, yes/no questions and explanations stay prose. An irreversible confirmation is confirm_card, a message to someone else is compose_message; never a part. When the user asks which of two or more named things is better or how they differ (「AとBどっちが良い？」), the answer is a Compare of the deciding points followed by your recommendation in prose; prose alone or a Choice alone is not a comparison.

Write parts as one fenced code block with the language \`openui-lang\`, placed between your sentences. A block is a program: \`root = Part(...)\` plus, if you like, more lines \`name = Part(...)\` that root refers to by name (any order). Card, Row and Column take a list of parts (or short strings) as their first argument, so you can compose your own layout: a Card holding a Heading, a Row of Stats, Facts, Badges and a Button, for example. Parts may also be written inline inside that list. Only Card, Row and Column hold parts; at most one Choice or Input per block; nest at most ${PROGRAM_DEPTH_MAX} levels. Arguments are positional in the order below; strings use double quotes; trailing optional arguments can be omitted; never use name: value syntax for arguments (objects such as {label: "店", value: "…"} are values). Several blocks in one reply are fine. Do not put a block inside another code block, an HTML comment or a list item. Keep a Choice question or Input label within ${ANSWER_QUESTION_MAX} characters and each option within ${ANSWER_VALUE_MAX}.

Parts (generated from the chat UI; ? = optional; Part = any part below):
${sig}

When the user presses a Choice or submits an Input, the answer arrives as the user's own chat message in the form \`<question> → <answer>\`. After asking with Choice or Input, end the turn and wait for it; do not guess the answer. A Choice question is answered only through the message; do not restate the options as a list. When the answer hinges on one number only the user knows (a budget, hours per week, a head count), ask for it with Input instead of assuming it.

Show the real thing when the user picks among things that differ by look: give each option its color or image, not just a name. Colors: {label: "ベージュ", color: "#d8c7a8"} with #rgb, #rrggbb or rgb(r, g, b); when you know only the color's name, use your closest value and say the colors are approximate (a color needs no image). Images (Image, Card's image, a Choice option's image) only with an image that really exists in this conversation or room: /api/v1/files/<name> (an attachment [添付画像: …/uploads/<name>] is /api/v1/files/<name>) or an https:// image URL that appeared here (a page you read, a search result). Never invent an image URL; with no real image, leave the image out. A Button opens an https:// URL or a path on this site (/artifacts/…) that you actually know. Compare columns and cells may be {label, color} too. The answer that arrives is the label. In a Chart, a value with no data is null (the line breaks there; no bar).

Examples:
注文できたよ。

\`\`\`openui-lang
root = Card([head, Row([total, eta]), Facts([{label: "店", value: "マクドナルド 尼崎駅前店"}, {label: "支払い", value: "Amex 末尾3004"}])], "注文")
head = Heading("ビッグマックセット", "ポテトM・コーラM")
total = Stat("合計", 1135, "円")
eta = Stat("到着", "14:08〜14:19")
\`\`\`

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
