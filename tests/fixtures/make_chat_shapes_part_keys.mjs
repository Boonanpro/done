// tests/fixtures/chat_shapes_part_keys.json を書く: 返事の本文 → 画面が作る部品の鍵（split.ts + answers.ts partKeys）。
// サーバー（app/agent/chat_shapes.py part_keys / shape_codes）が同じ鍵を作ることを tests/test_chat_shapes_answer_to.py が見る。
// 書き直す時: node --experimental-strip-types tests/fixtures/make_chat_shapes_part_keys.mjs
import { writeFileSync } from 'node:fs';
import { splitShapeSegments } from '../../frontend/src/lib/chat-shapes/split.ts';
import { partKeys } from '../../frontend/src/lib/chat-shapes/answers.ts';

const BS = '\\';
const fence = (code, lang = 'openui-lang') => '```' + lang + '\n' + code + '\n```';
const CHOICE = 'root = Choice("予算", ["5万円", "10万円"])';
const STEPS = 'root = Steps(["アプリを開く", "予約を確認する"], "当日の流れ")';
const CHART = 'root = Chart("line", ["9/8", "9/9"], [{name: "広告費", values: [1200, 980]}], "円")';

const cases = [
  { name: 'one part', text: `予算は？\n\n${fence(CHOICE)}\n\n決まったら進めます。` },
  { name: 'two parts, one repeated (ordinal)', text: `${fence(CHOICE)}\n${fence(STEPS)}\n${fence(CHOICE)}` },
  { name: 'whitespace differences normalize to the same key', text: `${fence('  root =   Choice("予算",\t["5万円",  "10万円"])  ')}` },
  { name: 'CRLF reply', text: `前の文\r\n${fence(CHOICE).replaceAll('\n', '\r\n')}\r\n後の文` },
  { name: 'tilde fence and openui alias', text: `~~~openui-lang\n${STEPS}\n~~~\n\`\`\`openui\n${CHART}\n\`\`\`` },
  { name: 'example inside another code block is not a part', text: `例:\n\`\`\`\`markdown\n${fence(CHOICE)}\n\`\`\`\`\n本物:\n${fence(STEPS)}` },
  { name: 'HTML comment hides a part', text: `<!--\n${fence(CHOICE)}\n-->\n\n${fence(STEPS)}` },
  { name: 'div block hides a part until the blank line', text: `<div>\n${fence(CHOICE)}\n</div>\n\n${fence(CHART)}` },
  { name: 'blockquote lines are not fences', text: `> ${fence(CHOICE).replaceAll('\n', '\n> ')}\n\n${fence(STEPS)}` },
  { name: 'unclosed saved block is prose', text: `${fence(STEPS)}\n\`\`\`openui-lang\n${CHOICE}` },
  { name: 'unicode escapes stay in the code (key is over the code, not the value)', text: fence(`root = Steps(["${BS}u65e5${BS}u672c", "a${BS}rb"])`) },
  { name: 'ideographic space and NBSP collapse like JS whitespace', text: fence(`root　= Choice("予算", ["5万円", "10万円"])`) },
  { name: 'surrogate pair in code', text: fence('root = Choice("絵文字😀", ["👍", "👎"])') },
  { name: 'indented 4 is not a fence; indented 3 is', text: `    ${fence(CHOICE).replaceAll('\n', '\n    ')}\n\n   ${fence(STEPS).replaceAll('\n', '\n   ')}` },
  { name: 'type-7 html after paragraph does not start a block', text: `説明\n<span>\n${fence(CHOICE)}\n\n<span>\n${fence(STEPS)}` },
];

const out = cases.map(({ name, text }) => {
  const segs = splitShapeSegments(text);
  const codes = segs.filter((s) => s.kind === 'shape').map((s) => s.code);
  return { name, text, codes, keys: partKeys(codes) };
});
writeFileSync(new URL('./chat_shapes_part_keys.json', import.meta.url), JSON.stringify(out, null, 2) + '\n', 'utf8');
console.log(`wrote ${out.length} cases`);
for (const c of out) console.log(c.name, '→', c.keys);
