// 期待値: Web の文章の描画（react-markdown＋remark-gfm）と同じ remark-parse＋remark-gfm（micromark）の構文木の、
// 文書の一番外側のフェンスのコードブロック（``` / ~~~。字下げコードは除く）。{ gfm: false } で CommonMark だけ
// （remark-parse だけ）の答えも出せる。比べる形は plain.ts topLevelFences に合わせる:
// { line: 開きの行（0始まり）, closed: 閉じのフェンスまであるか, shape: 部品の言語名か, code: 中身, lang: 言語名 }
// lang は plain.ts の言語名に名前の文字参照（&amp; など）が残っている時だけ比べない（plain.ts は名前の文字参照を
// 解かない。解いても openui-lang / openui にはならないので shape は同じ。shape は必ず比べる）。
import { unified } from '../../frontend/node_modules/unified/index.js';
import remarkParse from '../../frontend/node_modules/remark-parse/index.js';
import remarkGfm from '../../frontend/node_modules/remark-gfm/index.js';
import { isShapeLang, topLevelFences } from '../../frontend/src/lib/chat-shapes/plain.ts';

const NAMED_REFERENCE = /&[0-9A-Za-z]{1,31};/;

const OPEN = /^ {0,3}(`{3,}|~{3,})/;

/** 文書の各行の始まりの位置（\n・\r\n・\r で区切る。先頭の BOM は飛ばす＝micromark と同じ位置の数え方） */
function lineStarts(text) {
  const starts = [text.charCodeAt(0) === 0xfeff ? 1 : 0];
  for (let i = starts[0]; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c === 13 && text.charCodeAt(i + 1) === 10) { starts.push(i + 2); i++; } else if (c === 10 || c === 13) starts.push(i + 1);
  }
  return starts;
}

function sourceLine(text, starts, line) {
  const s = starts[line];
  if (s === undefined) return '';
  const e = line + 1 < starts.length ? starts[line + 1] : text.length;
  return text.slice(s, e).replace(/\r\n$|\r$|\n$/, '');
}

export function remarkFences(text, { gfm = true } = {}) {
  const proc = gfm ? unified().use(remarkParse).use(remarkGfm) : unified().use(remarkParse);
  const tree = proc.parse(text);
  const starts = lineStarts(text);
  const out = [];
  for (const n of tree.children) {
    if (n.type !== 'code') continue;
    const first = n.position.start.line - 1;
    const open = sourceLine(text, starts, first).match(OPEN);
    if (!open) continue;   // 字下げコード
    const last = n.position.end.line - 1;
    const close = sourceLine(text, starts, last).match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);
    const closed = last > first && !!close && close[1][0] === open[1][0] && close[1].length >= open[1].length;
    out.push({ line: first, closed, shape: isShapeLang(n.lang || ''), code: n.value, lang: n.lang || '' });
  }
  return out;
}

/** 同じ形にした plain.ts の結果 */
export function oursFences(text) {
  const starts = lineStarts(text);
  return topLevelFences(text).map((f) => ({ line: starts.indexOf(f.start), closed: f.closed, shape: isShapeLang(f.lang), code: f.code, lang: f.lang }));
}

/** 比べる形（言語名に名前の文字参照が残る物は lang を比べない） */
export function comparable(ours, theirs) {
  const pick = (a, keepLang) => ({ line: a.line, closed: a.closed, shape: a.shape, code: a.code, ...(keepLang ? { lang: a.lang } : {}) });
  const keep = ours.map((f) => !NAMED_REFERENCE.test(f.lang));
  return [JSON.stringify(ours.map((f, k) => pick(f, keep[k]))), JSON.stringify(theirs.map((f, k) => pick(f, keep[k] ?? true)))];
}
