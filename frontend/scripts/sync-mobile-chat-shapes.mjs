// 部品（チャットの ```openui-lang）の共有の決まりを、スマホのアプリへ写す。アプリは別のパッケージなので frontend の
// ファイルを取り込めない。PC とスマホで読み手・検査・答えの送信・グラフの形が同じになるよう、写しはこの道具だけが作る
// （2026-10-23。手で写していた時は、スマホだけ検査が無い・折れ線が棒になる、と差が出た）。
//
// 実行（frontend で）: npm run sync:mobile-shapes
//   = node scripts/sync-mobile-chat-shapes.mjs
// 確認: tests/chat_shapes_program.test.mjs が「写しが今の中身と同じ」かを見る。
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, '../src/lib/chat-shapes');
const DST = resolve(HERE, '../../mobile');

/** frontend のファイル名 → スマホの写しの名前 */
export const COPIES = {
  'plain.ts': 'chat-shapes-plain.ts',
  'answers.ts': 'chat-shapes-answers.ts',
  'schema.ts': 'chat-shapes-schema.ts',
  'answer-sends.ts': 'chat-shapes-answer-sends.ts',
  'use-answer-send.ts': 'chat-shapes-use-answer-send.ts',
  'chart-geometry.ts': 'chat-shapes-chart-geometry.ts',
  'job-report.ts': 'chat-shapes-job-report.ts',
};

/** 写しの中身: 頭の3行の説明＋同じ本文（同じフォルダの読み込みだけ写しの名前に替える） */
export function mobileCopy(name) {
  const body = readFileSync(resolve(SRC, name), 'utf8').replace(/\r\n/g, '\n').replace(
    /(['"])\.\/(plain|answers|schema|answer-sends|use-answer-send|chart-geometry|job-report)(?:\.ts)?\1/g,
    (_, q, base) => `${q}./${COPIES[`${base}.ts`].replace(/\.ts$/, '')}${q}`,
  );
  return [
    `// スマホのアプリ用の写し: frontend/src/lib/chat-shapes/${name} と同じ中身（同じフォルダの読み込みの名前だけ違う）。`,
    '// frontend/scripts/sync-mobile-chat-shapes.mjs が作る。手で直さず、元を直して写し直す',
    '// （tests/chat_shapes_program.test.mjs が同じ中身かを見る）。',
    body,
  ].join('\n');
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  for (const [name, copy] of Object.entries(COPIES)) {
    writeFileSync(resolve(DST, copy), mobileCopy(name), 'utf8');
    console.log(`wrote mobile/${copy}`);
  }
}
