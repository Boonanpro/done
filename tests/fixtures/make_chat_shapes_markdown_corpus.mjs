// tests/fixtures/chat_shapes_markdown_corpus.json を書く: 返事の本文 → remark-parse の一番外側のフェンスのコードブロック
// （閉じ・部品の言語名か・中身）と、画面が作る部品のコードと鍵。サーバー（app/agent/chat_shapes.py）が同じ答えを
// 出すことを tests/test_chat_shapes_markdown.py が見る。書く前に plain.ts が remark と同じ答えであることを確かめる。
// 書き直す時: node --experimental-strip-types tests/fixtures/make_chat_shapes_markdown_corpus.mjs
import { writeFileSync } from 'node:fs';
import { splitShapeSegments } from '../../frontend/src/lib/chat-shapes/split.ts';
import { partKeys } from '../../frontend/src/lib/chat-shapes/answers.ts';
import { verifierCases, targetedCases, generatedCases } from './chat_shapes_markdown_cases.mjs';
import { remarkFences, oursFences, comparable } from './chat_shapes_markdown_oracle.mjs';

const cases = [...verifierCases(), ...targetedCases(), ...generatedCases(20261018, 600, 16)];
const rows = cases.map(({ name, text }) => {
  const theirs = remarkFences(text);
  const [a, b] = comparable(oursFences(text), theirs);
  if (a !== b) throw new Error(`plain.ts と remark-parse が違う: ${name} ${JSON.stringify(text)}`);
  const shapeCodes = splitShapeSegments(text).filter((s) => s.kind === 'shape').map((s) => s.code);
  return { name, text, fences: theirs.map((f) => ({ closed: f.closed, shape: f.shape, code: f.code })), shape_codes: shapeCodes, keys: partKeys(shapeCodes) };
});
writeFileSync(new URL('./chat_shapes_markdown_corpus.json', import.meta.url), JSON.stringify(rows, null, 1) + '\n', 'utf8');
console.log(`wrote ${rows.length} cases (${rows.filter((r) => r.shape_codes.length).length} with parts)`);
