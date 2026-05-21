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
export function isEditableTextLeaf(el: Element | null | undefined): boolean {
  if (!el) return false;
  if (!el.getAttribute || !el.getAttribute('data-edit-id')) return false;
  return el.children.length === 0;
}
