/**
 * インスペクタ編集モデル
 *
 * 設計: docs/proposals/inspector_redesign.md
 *
 * 編集対象 1 つにつき、以下の構造でデータを保持する。
 * 「画面の HTML をそのまま保存」ではなく、
 * 「テキスト本体」と「装飾の指示」を分けて保持し、
 * 画面はこの 2 つから毎回組み立てる。
 *
 * これにより、部分テキスト装飾（例: "（吉川特装）" だけ大きく）が
 * span を DOM に注入する必要がなくなり、要素識別子が壊れない。
 */

export type CSSStyle = Record<string, string>;

/** 部分テキスト装飾。文字位置（start/end, UTF-16 code unit 基準）で範囲指定。 */
export interface InlineSpan {
  start: number;
  end: number;
  style: CSSStyle;
}

/** 編集モデル（v2）。inspector_overrides.attrs に格納される。 */
export interface EditModel {
  v: 2;
  /** 要素の純粋なテキスト内容。span 等 HTML は含まない。 */
  text: string | null;
  /** 要素全体に適用する装飾。 */
  blockStyle: CSSStyle;
  /** 部分装飾。空配列なら全体装飾のみ。 */
  spans: InlineSpan[];
  /** リンク要素の href 等、特殊属性。 */
  attrs: CSSStyle;
  /**
   * 初回編集時に捕捉した「編集前の状態」。Reset（編集前に戻す）で元へ復元するために保持。
   * text=元テキスト, blockStyle=ユーザーが編集した各プロパティの元の computed 値。
   * 一度だけ捕捉し以後上書きしない（真の原状を保つため）。
   */
  orig?: { text: string | null; blockStyle: CSSStyle };
}

/** 旧形式（v1）。後方互換のため読み取り専用で扱う。 */
export interface LegacyAttrs {
  html?: string;
  text?: string;
  [key: string]: string | undefined;
}

/** 空モデルの生成。 */
export function emptyModel(): EditModel {
  return { v: 2, text: null, blockStyle: {}, spans: [], attrs: {} };
}

/** モデルが「実質空」（保存しなくてよい）か。 */
export function isEmptyModel(m: EditModel): boolean {
  return (
    m.text === null &&
    Object.keys(m.blockStyle).length === 0 &&
    m.spans.length === 0 &&
    Object.keys(m.attrs).length === 0
  );
}

/** API 保存用に attrs フィールドへ詰め込む形に変換。 */
export function modelToAttrsField(m: EditModel): Record<string, unknown> {
  return {
    v: m.v,
    text: m.text,
    spans: m.spans,
    blockStyle: m.blockStyle,
    extraAttrs: m.attrs,
  };
}

/** API レスポンスから EditModel を読み取る。v2 でなければ null（呼び出し側で migrate）。 */
export function readModelFromAttrs(attrs: Record<string, unknown> | null | undefined): EditModel | null {
  if (!attrs) return null;
  const v = attrs['v'];
  if (v !== 2) return null;
  return {
    v: 2,
    text: typeof attrs['text'] === 'string' ? (attrs['text'] as string) : null,
    blockStyle: (attrs['blockStyle'] as CSSStyle) || {},
    spans: (attrs['spans'] as InlineSpan[]) || [],
    attrs: (attrs['extraAttrs'] as CSSStyle) || {},
  };
}

/**
 * テキスト編集時に spans の文字位置を補正する。
 * 例: "abc[span:def]ghi" の "abc" 位置に "X" を挿入 → spans の start/end を +1。
 *
 * @param spans 補正対象
 * @param oldText 編集前テキスト
 * @param newText 編集後テキスト
 * @returns 補正済み spans。範囲が完全に潰れた span は除外。
 */
export function adjustSpansForTextChange(
  spans: InlineSpan[],
  oldText: string,
  newText: string
): InlineSpan[] {
  // 共通プレフィックス長
  let prefix = 0;
  const min = Math.min(oldText.length, newText.length);
  while (prefix < min && oldText[prefix] === newText[prefix]) prefix++;

  // 共通サフィックス長
  let suffix = 0;
  while (
    suffix < min - prefix &&
    oldText[oldText.length - 1 - suffix] === newText[newText.length - 1 - suffix]
  ) {
    suffix++;
  }

  // 変更範囲: oldText[prefix .. oldText.length - suffix] が
  //          newText[prefix .. newText.length - suffix] に置き換わった
  const oldEnd = oldText.length - suffix;
  const newEnd = newText.length - suffix;
  const delta = newEnd - oldEnd; // newText が長ければ正、短ければ負

  const out: InlineSpan[] = [];
  for (const s of spans) {
    let { start, end } = s;
    // 編集範囲より前: 変化なし
    // 編集範囲より後: delta だけ平行移動
    // 編集範囲に重なる: クランプ（部分削除に対応）
    if (end <= prefix) {
      // 完全に編集前
      out.push({ ...s });
      continue;
    }
    if (start >= oldEnd) {
      // 完全に編集後
      out.push({ ...s, start: start + delta, end: end + delta });
      continue;
    }
    // 編集範囲に重なる: 編集範囲の外側部分だけを残す
    const newStart = start < prefix ? start : prefix;
    const newEndAdjusted = end > oldEnd ? end + delta : newEnd;
    if (newEndAdjusted > newStart) {
      out.push({ ...s, start: newStart, end: newEndAdjusted });
    }
    // 完全に潰れたら除外
  }
  return out;
}

/**
 * 同じ範囲・同じプロパティの span をマージする。
 * 例: 8-11 を red にした後、同じ範囲を再度 red+bold にした場合、
 *     2 つの span ではなく 1 つにまとめる。
 */
export function upsertSpan(spans: InlineSpan[], next: InlineSpan): InlineSpan[] {
  if (next.end <= next.start) return spans;
  const out: InlineSpan[] = [];
  let merged = false;
  for (const s of spans) {
    if (s.start === next.start && s.end === next.end) {
      out.push({ ...s, style: { ...s.style, ...next.style } });
      merged = true;
    } else {
      out.push(s);
    }
  }
  if (!merged) out.push(next);
  return out;
}

/** style プロパティを部分範囲に適用する高レベル API。 */
export function applyInlineStyle(
  model: EditModel,
  start: number,
  end: number,
  property: string,
  value: string
): EditModel {
  if (start >= end) return model;
  const next = upsertSpan(model.spans, { start, end, style: { [property]: value } });
  return { ...model, spans: next };
}

/** 全体スタイル適用。 */
export function applyBlockStyle(
  model: EditModel,
  property: string,
  value: string
): EditModel {
  return { ...model, blockStyle: { ...model.blockStyle, [property]: value } };
}

/** テキスト全体差し替え（spans は文字位置補正される）。 */
export function applyText(model: EditModel, newText: string): EditModel {
  const oldText = model.text ?? '';
  const spans = adjustSpansForTextChange(model.spans, oldText, newText);
  return { ...model, text: newText, spans };
}
