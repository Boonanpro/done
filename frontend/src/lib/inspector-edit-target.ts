/**
 * 編集対象の統一判定（EditModel v2）。
 *
 * 原則: text 編集の対象は「data-edit-id を持ち、子 Element を持たない leaf」のみ。
 *
 * 理由:
 *   EditModel v2 は `text + spans` の分離設計で、HTML タグそのものを表現できない。
 *   子 Element（<strong> / <em> / <a> / 子 div など）を含む要素を text 編集すると
 *   保存時に innerText で平坦化され、再描画で `<strong>` などの構造が消える。
 *
 * 結果として:
 *   - select は誰でも可能（box-style や block-style 系の編集は破壊的でないため、
 *     applyModelToElement 側で blockStyle / attrs のみ反映される）
 *   - text / inline-style の **書き込み** は leaf のみが対象
 *
 * 装飾を後から編集したい場合は、artifact 側で
 *   <strong data-edit-id="..."> や <span data-edit-id="..."> のように
 *   装飾部分を独立した編集単位に分割する責任を artifact が持つ。
 */
const TEXTUAL_TAGS = new Set([
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'span', 'a', 'li', 'label', 'button', 'strong', 'em',
  'td', 'th', 'figcaption', 'dt', 'dd', 'b',
]);

const INLINE_TEXT_TAGS = new Set([
  'a', 'abbr', 'b', 'bdi', 'bdo', 'br', 'cite', 'code', 'del', 'em',
  'i', 'ins', 'kbd', 'mark', 'q', 's', 'small', 'span', 'strong', 'sub',
  'sup', 'time', 'u', 'var', 'wbr',
]);

function hasOnlyInlineTextContent(el: Element): boolean {
  return Array.from(el.children).every((child) =>
    INLINE_TEXT_TAGS.has(child.tagName.toLowerCase()) && hasOnlyInlineTextContent(child)
  );
}

/**
 * A text edit may replace the element's HTML. It is therefore safe only for
 * one text unit: a leaf element or a generated `data-edit-id` wrapper that
 * contains inline text only. A paragraph containing an emphasized word is not
 * one text unit; generated pages must mark its separately editable fragments.
 */
export function isEditableTextLeaf(el: Element | null | undefined): boolean {
  if (!el) return false;
  const tag = el.tagName.toLowerCase();
  if (el.getAttribute?.('data-edit-id')) return hasOnlyInlineTextContent(el);
  return TEXTUAL_TAGS.has(tag) && hasOnlyInlineTextContent(el);
}
