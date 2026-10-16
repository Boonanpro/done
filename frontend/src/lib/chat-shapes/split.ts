/**
 * ダンの返事の文章から「部品」（OpenUI Lang のコードブロック）を切り出す。
 *
 * 部品の区切りは、OpenUI の流儀（inline mode）と同じ ```openui-lang のコードブロック。
 * コードブロックと HTML ブロックの見つけ方は plain.ts の scanBlocks（Markdown＝CommonMark のフェンス構文と
 * HTML ブロック。アプリの文章変換と同じ読み手）:
 * - 開きは行頭（字下げ3つまで）の ``` か ~~~（3つ以上）。続く情報文字列の最初の語が言語名
 * - 閉じは同じ文字で、開きと同じ本数以上、後ろは空白だけ。行末の CR（CRLF）は無視する
 * - 別の言語のコードブロック（~~~markdown や ````markdown title="x" など）の中の ```openui-lang は
 *   そのコードブロックの中身なので部品にしない
 * - HTML ブロック（<!-- コメント --> など）の中の ```openui-lang はコメントの一部なので部品にしない
 * 文章側には元の文字（CR を含む）をそのまま残す。
 *
 * 生成の途中（閉じがまだ無い）でも、届いた分を部品として返す（complete=false）。
 * 保存済みの返事で閉じが無い場合は壊れた書き方なので、文章（コードブロック）に戻す。
 *
 * 依存は plain.ts だけ（拡張子つきで読み込む: node:test からも Next からも同じ形で読める。tsconfig allowImportingTsExtensions）。
 */
import { SHAPE_FENCE_RE, isShapeLang, scanBlocks } from './plain.ts';

export type ShapeSegment =
  | { kind: 'markdown'; text: string }
  | { kind: 'shape'; code: string; complete: boolean; index: number };

export function hasShapeFence(text: string | null | undefined): boolean {
  if (!text) return false;
  return SHAPE_FENCE_RE.test(text);
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
  for (const b of scanBlocks(lines)) {
    md.push(...lines.slice(i, b.start));
    if (b.kind === 'fence' && isShapeLang(b.fence.lang) && (b.closed || streaming)) {
      // 部品のブロック（閉じまで届いた物。生成中は届いた分まで）
      flushMd();
      out.push({ kind: 'shape', code: b.body.join('\n'), complete: b.closed, index: shapeIndex++ });
    } else {
      // 別の言語のコードブロック・HTML ブロック・保存済みで閉じの無い壊れた部品: 文章側にそのまま残す
      md.push(...lines.slice(b.start, b.end));
    }
    i = b.end;
  }
  md.push(...lines.slice(i));
  flushMd();
  if (out.length === 0) return [{ kind: 'markdown', text }];
  return out;
}
