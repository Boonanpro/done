/**
 * ダンの返事の文章から「部品」（OpenUI Lang のコードブロック）を切り出す。
 *
 * 部品の区切りは、OpenUI の流儀（inline mode）と同じ ```openui-lang のコードブロック。
 * Markdown（CommonMark）のフェンス構文どおりに読む:
 * - 開きは行頭（字下げ3つまで）の ``` か ~~~（3つ以上）。続く情報文字列の最初の語が言語名
 *   （バッククォートのフェンスの情報文字列にバッククォートは書けない）
 * - 閉じは同じ文字で、開きと同じ本数以上、後ろは空白だけ
 * - 行末の CR（CRLF）は無視する。文章側には元の文字をそのまま残す
 * 別の言語のコードブロック（~~~markdown や ````markdown title="x" など）の中に書かれた
 * ```openui-lang は、そのコードブロックの中身なので部品にしない。
 *
 * 生成の途中（閉じがまだ無い）でも、届いた分を部品として返す（complete=false）。
 * 保存済みの返事で閉じが無い場合は壊れた書き方なので、文章（コードブロック）に戻す。
 *
 * 依存なし（node:test から直接読み込んで試験する）。
 */

export type ShapeSegment =
  | { kind: 'markdown'; text: string }
  | { kind: 'shape'; code: string; complete: boolean; index: number };

const SHAPE_FENCE_LANGS = new Set(['openui-lang', 'openui']);

type Fence = { char: '`' | '~'; size: number; lang: string };

/** フェンスの開き行なら { char, size, lang }。lang は情報文字列の最初の語（小文字。無ければ ''）。 */
function fenceOpen(rawLine: string): Fence | null {
  const line = rawLine.replace(/\r$/, '');
  const m = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
  if (!m) return null;
  const char = m[1][0] as '`' | '~';
  const info = m[2];
  // CommonMark: バッククォートのフェンスの情報文字列にバッククォートは含められない（その行は開きではない）
  if (char === '`' && info.includes('`')) return null;
  const lang = (info.trim().split(/\s+/)[0] || '').toLowerCase();
  return { char, size: m[1].length, lang };
}

/** 閉じ行: 開きと同じ文字で本数が同じか多く、後ろは空白だけ。 */
function fenceClose(rawLine: string, open: Fence): boolean {
  const line = rawLine.replace(/\r$/, '');
  const m = line.match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);
  return !!m && m[1][0] === open.char && m[1].length >= open.size;
}

export function hasShapeFence(text: string | null | undefined): boolean {
  if (!text) return false;
  return /(^|\n) {0,3}(`{3,}|~{3,})[ \t]*(openui-lang|openui)(?=[ \t\r\n]|$)/i.test(text);
}

/**
 * @param text 返事の本文（途中まででもよい）
 * @param opts.streaming 生成の途中なら true。閉じていない部品を「部品（未完）」として返す
 */
export function splitShapeSegments(
  text: string,
  opts: { streaming?: boolean } = {},
): ShapeSegment[] {
  if (!text || !hasShapeFence(text)) return [{ kind: 'markdown', text: text || '' }];
  const streaming = !!opts.streaming;
  const lines = text.split('\n');
  const out: ShapeSegment[] = [];
  let md: string[] = [];
  let shapeIndex = 0;

  const flushMd = () => {
    const joined = md.join('\n');
    if (joined.trim()) out.push({ kind: 'markdown', text: joined });
    md = [];
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const open = fenceOpen(line);
    if (open && SHAPE_FENCE_LANGS.has(open.lang)) {
      // 部品のブロック: 閉じまでを集める（コードの行末 CR は落とす）
      const body: string[] = [];
      let j = i + 1;
      let closed = false;
      while (j < lines.length) {
        if (fenceClose(lines[j], open)) {
          closed = true;
          break;
        }
        body.push(lines[j].replace(/\r$/, ''));
        j++;
      }
      if (closed || streaming) {
        flushMd();
        out.push({ kind: 'shape', code: body.join('\n'), complete: closed, index: shapeIndex++ });
        i = closed ? j + 1 : j;
        continue;
      }
      // 保存済みで閉じが無い＝壊れた書き方。そのまま文章として残す
      md.push(line, ...lines.slice(i + 1, j));
      i = j;
      continue;
    }
    if (open) {
      // 別の言語のコードブロック: 中に openui-lang と書かれていても部品にしない（閉じまで文章側）
      md.push(line);
      let j = i + 1;
      while (j < lines.length && !fenceClose(lines[j], open)) {
        md.push(lines[j]);
        j++;
      }
      if (j < lines.length) md.push(lines[j]);
      i = j + 1;
      continue;
    }
    md.push(line);
    i++;
  }
  flushMd();
  if (out.length === 0) return [{ kind: 'markdown', text }];
  return out;
}
