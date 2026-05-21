/**
 * モデル → HTML レンダ
 *
 * EditModel.text + spans から innerHTML 文字列を生成する。
 * 出力は「フラットな <span> 列」で、ネストしない。
 * 同じ文字位置に複数 span が重なる場合は、その範囲だけスタイルをマージして 1 つの span にする。
 *
 * これにより、保存→再描画→再保存を繰り返しても DOM 構造が肥大化せず、
 * 要素識別子も保たれる。
 */

import type { EditModel, CSSStyle, InlineSpan } from './inspector-model';
import { isEditableTextLeaf } from './inspector-edit-target';

const HTML_ESCAPE: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => HTML_ESCAPE[c]);
}

/**
 * HTML エスケープ + 改行を <br> に変換。
 * 出力 HTML 内で \n をそのまま残すと白space:normal で空白に潰されるので、
 * テキスト出力時は必ずこちらを使う。
 */
function escapeHtmlWithBr(s: string): string {
  return escapeHtml(s).replace(/\n/g, '<br>');
}

function styleToString(style: CSSStyle): string {
  return Object.entries(style)
    .map(([k, v]) => `${k}: ${escapeAttr(v)}`)
    .join('; ');
}

function escapeAttr(v: string): string {
  return v.replace(/"/g, '&quot;');
}

/**
 * 各文字位置における「重なっている全 span のスタイルマージ結果」を計算し、
 * 連続して同じスタイルになる範囲を 1 セグメントとして出力する。
 *
 * テキスト分離問題対策:
 * - 空 style のセグメントは <span> でラップしない（プレーンテキストとして連結）
 * - 隣接セグメントは start/end 連続性関係なく、最終的にプレーン同士を bridge できるよう
 *   出力時に「連続する装飾なし」を 1 つの文字列に統合する
 */
export function renderToHtml(model: EditModel): string {
  const text = model.text ?? '';
  if (!text) return '';

  const spans = model.spans;
  if (spans.length === 0) {
    return escapeHtmlWithBr(text);
  }

  // 文字位置 → そこに重なる span のリスト（インデックス）
  // パフォーマンス: spans 数が少ない（数十）ので O(n*m) で十分
  const segments: { start: number; end: number; style: CSSStyle }[] = [];

  // セグメント境界は全 span の start/end の集合
  const boundarySet = new Set<number>();
  boundarySet.add(0);
  boundarySet.add(text.length);
  for (const s of spans) {
    boundarySet.add(Math.max(0, Math.min(text.length, s.start)));
    boundarySet.add(Math.max(0, Math.min(text.length, s.end)));
  }
  const boundaries = Array.from(boundarySet).sort((a, b) => a - b);

  for (let i = 0; i < boundaries.length - 1; i++) {
    const segStart = boundaries[i];
    const segEnd = boundaries[i + 1];
    if (segStart === segEnd) continue;

    // この範囲に重なる span を全部マージ（後に来る span が優先）
    const mergedStyle: CSSStyle = {};
    for (const sp of spans) {
      if (sp.start <= segStart && sp.end >= segEnd) {
        // 空文字 / null/undefined のキーは無視（"消去" 表現）
        for (const [k, v] of Object.entries(sp.style)) {
          if (typeof v === 'string' && v.length > 0) mergedStyle[k] = v;
        }
      }
    }
    segments.push({ start: segStart, end: segEnd, style: mergedStyle });
  }

  // 連続する同一スタイル（または両方空）を連結
  const merged: { start: number; end: number; style: CSSStyle }[] = [];
  for (const seg of segments) {
    const last = merged[merged.length - 1];
    if (last && stylesEqual(last.style, seg.style) && last.end === seg.start) {
      last.end = seg.end;
    } else {
      merged.push({ ...seg });
    }
  }

  // 出力: 空 style は <span> 化せずプレーン化。連続するプレーンは結合される。
  const parts: string[] = [];
  for (const seg of merged) {
    const segText = escapeHtmlWithBr(text.slice(seg.start, seg.end));
    if (Object.keys(seg.style).length === 0) {
      parts.push(segText);
    } else {
      parts.push(`<span data-dan-edit="1" style="${styleToString(seg.style)}">${segText}</span>`);
    }
  }
  return parts.join('');
}

function stylesEqual(a: CSSStyle, b: CSSStyle): boolean {
  const ak = Object.keys(a);
  const bk = Object.keys(b);
  if (ak.length !== bk.length) return false;
  for (const k of ak) if (a[k] !== b[k]) return false;
  return true;
}

/**
 * 要素にモデルを反映する。
 * - text/spans があれば innerHTML を再構築
 * - blockStyle は要素の inline style に !important で適用
 * - extraAttrs は href/src 等の属性に適用
 *
 * 統一原則 (isEditableTextLeaf): text/spans の innerHTML 反映は
 * 「data-edit-id 持ち & 子 Element 無し」の leaf のみ。
 * 子 Element を持つ要素（wrapper や <strong> を含む段落）は構造破壊を防ぐため skip。
 * blockStyle / attrs は非破壊なので、子持ち要素にも常に適用 OK。
 */
export function applyModelToElement(el: HTMLElement, model: EditModel): void {
  if (model.text !== null && isEditableTextLeaf(el)) {
    const html = renderToHtml(model);
    if (el.innerHTML !== html) {
      el.innerHTML = html;
    }
  }

  // 全体装飾（非破壊なので wrapper でも適用 OK）
  for (const [prop, val] of Object.entries(model.blockStyle)) {
    try {
      el.style.setProperty(prop, val, 'important');
    } catch {
      /* ignore */
    }
  }

  // 特殊属性 (href, src, etc.)
  for (const [name, val] of Object.entries(model.attrs)) {
    try {
      el.setAttribute(name, val);
      if (name === 'src' && el.tagName === 'VIDEO') {
        (el as HTMLVideoElement).load();
      }
    } catch {
      /* ignore */
    }
  }
}

/**
 * 要素から現在のテキスト位置を取り出すヘルパー。
 * iframe 内の Selection から start/end の文字位置（model.text 基準）を計算する。
 */
export function selectionToTextRange(
  el: Element,
  range: Range
): { start: number; end: number } | null {
  if (!el.contains(range.startContainer) || !el.contains(range.endContainer)) {
    return null;
  }
  const start = textOffsetWithin(el, range.startContainer, range.startOffset);
  const end = textOffsetWithin(el, range.endContainer, range.endOffset);
  if (start === -1 || end === -1) return null;
  return { start: Math.min(start, end), end: Math.max(start, end) };
}

function textOffsetWithin(root: Element, target: Node, offset: number): number {
  // root を起点にした target の textContent オフセットを計算
  let acc = 0;
  let found = -1;
  const walker = root.ownerDocument!.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node: Node | null = walker.nextNode();
  while (node) {
    if (node === target) {
      found = acc + offset;
      break;
    }
    acc += node.textContent?.length ?? 0;
    node = walker.nextNode();
  }
  // target が要素ノード（offset = 子要素 index）の場合
  if (found === -1 && target.nodeType === Node.ELEMENT_NODE) {
    const elTarget = target as Element;
    let acc2 = 0;
    const walker2 = root.ownerDocument!.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n: Node | null = walker2.nextNode();
    while (n) {
      if (elTarget.contains(n)) {
        // offset 番目までの子要素内テキストを足し込む
        // 簡易: target の最初の text node に到達したらそこまでの acc2 を返す
        return acc2;
      }
      acc2 += n.textContent?.length ?? 0;
      n = walker2.nextNode();
    }
    return acc2;
  }
  return found;
}
