/**
 * ダンの返事の文章から「部品」（OpenUI Lang のコードブロック）を切り出す。
 *
 * 部品の区切りは、OpenUI の流儀（inline mode）と同じ ```openui-lang のコードブロック。
 * それ以外の文字はそのまま Markdown として描く側に渡す。
 *
 * 生成の途中（閉じ ``` がまだ無い）でも、届いた分を部品として返す（complete=false）。
 * 保存済みの返事で閉じが無い場合は壊れた書き方なので、文章（コードブロック）に戻す。
 *
 * 依存なし（node:test から直接読み込んで試験する）。
 */

export type ShapeSegment =
  | { kind: 'markdown'; text: string }
  | { kind: 'shape'; code: string; complete: boolean; index: number };

const SHAPE_FENCE_LANGS = new Set(['openui-lang', 'openui']);

/** ``` で始まる行なら { lang, size } を返す（言語名は小文字化。無ければ ''。size は ` の本数）。 */
function fenceOpen(line: string): { lang: string; size: number } | null {
  const m = line.match(/^[ \t]{0,3}(`{3,})[ \t]*([^`\s]*)[ \t]*$/);
  if (!m) return null;
  return { lang: m[2].toLowerCase(), size: m[1].length };
}

/** 閉じの ``` は、開きと同じ本数以上（CommonMark と同じ。入れ子は本数を増やして書く）。 */
function fenceClose(line: string, size: number): boolean {
  const m = line.match(/^[ \t]{0,3}(`{3,})[ \t]*$/);
  return !!m && m[1].length >= size;
}

export function hasShapeFence(text: string | null | undefined): boolean {
  if (!text) return false;
  return /(^|\n)[ \t]{0,3}`{3,}[ \t]*(openui-lang|openui)[ \t]*(\n|$)/i.test(text);
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
      // 部品のブロック: 閉じ ``` までを集める
      const body: string[] = [];
      let j = i + 1;
      let closed = false;
      while (j < lines.length) {
        if (fenceClose(lines[j], open.size)) {
          closed = true;
          break;
        }
        body.push(lines[j]);
        j++;
      }
      if (closed || streaming) {
        flushMd();
        out.push({ kind: 'shape', code: body.join('\n'), complete: closed, index: shapeIndex++ });
        i = closed ? j + 1 : j;
        continue;
      }
      // 保存済みで閉じが無い＝壊れた書き方。そのまま文章として残す
      md.push(line, ...body);
      i = j;
      continue;
    }
    if (open) {
      // 別の言語のコードブロック: 中に openui-lang と書かれていても部品にしない
      md.push(line);
      let j = i + 1;
      while (j < lines.length && !fenceClose(lines[j], open.size)) {
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
