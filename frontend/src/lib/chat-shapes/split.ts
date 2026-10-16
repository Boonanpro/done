/**
 * ダンの返事の文章から「部品」（OpenUI Lang のコードブロック）を切り出す。
 *
 * 部品の区切りは、OpenUI の流儀（inline mode）と同じ ```openui-lang のコードブロック。
 * どこからどこまでが部品かは plain.ts の shapeFences（Markdown の読み手 remark-parse＝micromark と同じ手順で、
 * 文書の一番外側にある言語名 openui-lang / openui のコードブロック。アプリの文章変換とサーバーの鍵の確かめも同じ手順）:
 * - 別の言語のコードブロック（~~~markdown や ````markdown title="x" など）の中の ```openui-lang は
 *   そのコードブロックの中身なので部品にしない
 * - HTML ブロック（<!-- コメント --> や見出しの後の単独のタグなど）、引用・箇条書きの中、字下げコードの中の
 *   ```openui-lang も部品にしない
 * 文章側には元の文字（CR を含む）をそのまま残す。
 *
 * 生成の途中（閉じがまだ無い）でも、届いた分を部品として返す（complete=false）。
 * 保存済みの返事で閉じが無い場合は壊れた書き方なので、文章（コードブロック）に戻す。
 *
 * 依存は plain.ts だけ（拡張子つきで読み込む: node:test からも Next からも同じ形で読める。tsconfig allowImportingTsExtensions）。
 */
import { shapeFences } from './plain.ts';

export type ShapeSegment =
  | { kind: 'markdown'; text: string }
  | { kind: 'shape'; code: string; complete: boolean; index: number };

export function hasShapeFence(text: string | null | undefined): boolean {
  return !!text && shapeFences(text, { streaming: true }).length > 0;
}

/**
 * @param text 返事の本文（途中まででもよい）
 * @param opts.streaming 生成の途中なら true。閉じていない部品を「部品（未完）」として返す
 */
export function splitShapeSegments(
  text: string,
  opts: { streaming?: boolean } = {},
): ShapeSegment[] {
  const fences = text ? shapeFences(text, { streaming: !!opts.streaming }) : [];
  if (fences.length === 0) return [{ kind: 'markdown', text: text || '' }];
  const out: ShapeSegment[] = [];
  const pushMd = (s: string) => { if (s.trim()) out.push({ kind: 'markdown', text: s }); };
  let prev = 0;
  fences.forEach((f, index) => {
    // ブロックの前の文章（ブロックの開きの行の直前の改行 \n は文章に含めない）
    const before = text.slice(prev, f.start);
    pushMd(before.endsWith('\n') ? before.slice(0, -1) : before);
    out.push({ kind: 'shape', code: f.code, complete: f.closed, index });
    prev = f.next;
  });
  pushMd(text.slice(prev));
  return out;
}
