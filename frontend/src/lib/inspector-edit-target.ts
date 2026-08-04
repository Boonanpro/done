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
  'td', 'th', 'figcaption',
]);

// These tags only decorate or break a sentence. A layout or media child is
// intentionally excluded: replacing its parent text could erase page content.
const INLINE_TEXT_TAGS = new Set([
  'a', 'abbr', 'b', 'bdi', 'bdo', 'br', 'cite', 'code', 'del', 'em',
  'i', 'ins', 'kbd', 'mark', 'q', 's', 'small', 'span', 'strong', 'sub',
  'sup', 'time', 'u', 'var', 'wbr',
]);

function hasOnlyInlineTextContent(el: Element): boolean {
  for (const child of Array.from(el.children)) {
    if (!INLINE_TEXT_TAGS.has(child.tagName.toLowerCase())) return false;
    if (!hasOnlyInlineTextContent(child)) return false;
  }
  return true;
}

/**
 * A semantic text element, such as a paragraph containing <strong> or a
 * heading containing <br>, is one editable text unit.  Layout wrappers and
 * media remain excluded, so editing text cannot remove page structure.
 */
export function isEditableTextLeaf(el: Element | null | undefined): boolean {
  if (!el) return false;
  const tag = el.tagName.toLowerCase();
  if (TEXTUAL_TAGS.has(tag)) return hasOnlyInlineTextContent(el);
  return !!el.getAttribute?.('data-edit-id') && el.children.length === 0;
}
