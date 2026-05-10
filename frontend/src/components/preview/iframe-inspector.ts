'use client';

import { usePreviewStore } from '@/stores/preview-store';
import { computeElementKey, resolveEditUnit } from '@/components/dan/inspector-runtime';

const HOVER_OVERLAY_ID = 'dan-inspector-hover';
const ACTIVE_OVERLAY_ID = 'dan-inspector-active';

// インライン編集対象外タグ (フォーム要素や置換要素は触らない)
const INLINE_EDIT_BLOCKED_TAGS = new Set([
  'input', 'textarea', 'select', 'option', 'optgroup',
  'img', 'video', 'audio', 'iframe', 'canvas', 'svg', 'embed', 'object',
  'script', 'style', 'meta', 'link', 'br', 'hr',
  'html', 'body', 'head',
]);

const INLINE_TEXT_TAGS = new Set([
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'span', 'a', 'li', 'label', 'button', 'strong', 'em',
  'td', 'th', 'figcaption',
]);

type Handlers = {
  move: (e: Event) => void;
  click: (e: Event) => void;
  dblclick: (e: Event) => void;
  keydown: (e: Event) => void;
  scroll: (e: Event) => void;
  resize: (e: Event) => void;
  selectionchange: (e: Event) => void;
};

type Overlays = {
  hover: HTMLDivElement;
  active: HTMLDivElement;
  activeTarget: Element | null;
};

const registry = new WeakMap<HTMLIFrameElement, Handlers>();
const overlayRegistry = new WeakMap<HTMLIFrameElement, Overlays>();

function getDoc(iframe: HTMLIFrameElement): Document | null {
  try {
    return iframe.contentDocument;
  } catch {
    return null;
  }
}

function createOverlay(
  doc: Document,
  id: string,
  borderColor: string,
  fillColor: string,
  zIndex: number,
  extraShadow?: string
): HTMLDivElement {
  const el = doc.createElement('div');
  el.id = id;
  el.style.cssText = [
    'position: absolute',
    'pointer-events: none',
    `border: 2px solid ${borderColor}`,
    `background: ${fillColor}`,
    `z-index: ${zIndex}`,
    'display: none',
    'box-sizing: border-box',
    'transition: none',
    'border-radius: 2px',
    extraShadow ? `box-shadow: ${extraShadow}` : '',
  ]
    .filter(Boolean)
    .join(';');
  doc.body.appendChild(el);
  return el;
}

function positionTo(overlay: HTMLDivElement, doc: Document, target: Element) {
  const rect = target.getBoundingClientRect();
  const scrollX = doc.defaultView?.scrollX ?? 0;
  const scrollY = doc.defaultView?.scrollY ?? 0;
  overlay.style.display = 'block';
  overlay.style.left = `${rect.left + scrollX}px`;
  overlay.style.top = `${rect.top + scrollY}px`;
  overlay.style.width = `${rect.width}px`;
  overlay.style.height = `${rect.height}px`;
}

function hideOverlay(overlay: HTMLDivElement) {
  overlay.style.display = 'none';
}

export function attachInspector(iframe: HTMLIFrameElement) {
  const doc = getDoc(iframe);
  if (!doc) return;

  detachInspector(iframe);

  const hover = createOverlay(
    doc,
    HOVER_OVERLAY_ID,
    'rgba(59, 130, 246, 0.9)',
    'rgba(59, 130, 246, 0.12)',
    2147483646
  );
  const active = createOverlay(
    doc,
    ACTIVE_OVERLAY_ID,
    'rgb(34, 197, 94)',
    'rgba(34, 197, 94, 0.1)',
    2147483647,
    '0 0 0 4px rgba(34, 197, 94, 0.2)'
  );
  const overlays: Overlays = { hover, active, activeTarget: null };
  overlayRegistry.set(iframe, overlays);

  // iframe 内カーソルを crosshair に（選択可能性を視覚的に示す）
  doc.body.style.cursor = 'crosshair';

  const isOverlay = (el: Element | null): boolean =>
    el === hover || el === active || (!!el?.id && (el.id === HOVER_OVERLAY_ID || el.id === ACTIVE_OVERLAY_ID));

  const isEditing = (el: Element | null): boolean =>
    !!el && el.getAttribute('data-dan-editing') === '1';

  const move = (ev: Event) => {
    const e = ev as MouseEvent;
    const target = e.target as Element | null;
    if (!target || isOverlay(target)) return;
    // インライン編集中の要素にはホバー overlay を出さない (邪魔)
    if (isEditing(target)) {
      hideOverlay(hover);
      return;
    }
    positionTo(hover, doc, target);
  };

  const click = (ev: Event) => {
    const e = ev as MouseEvent;
    const initialTarget = e.target as Element | null;
    if (!initialTarget || isOverlay(initialTarget)) return;
    // 編集中の要素ならネイティブ click を通す (キャレット位置調整・テキスト選択のため)
    if (isEditing(initialTarget)) return;
    e.preventDefault();
    e.stopPropagation();

    // z-stack drill: 同じ場所を続けて click or Alt+click で下の要素にドリル
    const stackTarget = pickFromStack(doc, e, isOverlay) || initialTarget;

    // Alt+クリックでドリル中なら stack のまま、通常クリックは edit-unit に揃える
    // （data-edit-id を持つ祖先があれば論理的編集単位を選ぶ）
    const target = e.altKey ? stackTarget : resolveEditUnit(stackTarget);

    overlays.activeTarget = target;
    positionTo(active, doc, target);

    const rect = target.getBoundingClientRect();
    const tagName = target.tagName.toLowerCase();
    const text = (target.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120);
    const outerHtmlSnippet = (target.outerHTML || '').slice(0, 2000);

    const ancestors: string[] = [];
    let cursor: Element | null = target.parentElement;
    for (let depth = 0; depth < 3 && cursor && cursor.tagName.toLowerCase() !== 'body'; depth++) {
      const tag = cursor.tagName.toLowerCase();
      const cls = cursor.getAttribute('class') || '';
      ancestors.push(cls ? `${tag}.${cls.split(/\s+/).slice(0, 3).join('.')}` : tag);
      cursor = cursor.parentElement;
    }

    const computed = iframe.contentWindow?.getComputedStyle(target);
    const bgColor = computed?.backgroundColor || '';
    const classAttr = target.getAttribute('class') || '';

    const elementKey = computeElementKey(target);

    // スタック情報も記録 (UI ヒント表示用)
    const stackInfo = stackState.get(doc);
    const stackHint =
      stackInfo && stackInfo.stack.length > 1
        ? { index: stackInfo.index, total: stackInfo.stack.length }
        : undefined;

    usePreviewStore.getState().selectElement(
      {
        tagName,
        text,
        outerHtmlSnippet,
        rect: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
        className: classAttr,
        ancestors,
        bgColor,
        elementKey,
        stackHint,
      },
      target
    );

    // インライン編集はシングルクリックでは起動しない (見た目が変わる副作用回避)。
    // ダブルクリック (下の dblclick handler) で明示的に編集モード突入する設計。
  };

  // ダブルクリックで初めてインライン編集モードに入る
  const dblclick = (ev: Event) => {
    const e = ev as MouseEvent;
    const initialTarget = e.target as Element | null;
    if (!initialTarget || isOverlay(initialTarget)) return;
    if (isEditing(initialTarget)) return;

    // クリック位置のテキストノードから、本当に編集すべき leaf 要素を見つける。
    // wrapper div を edit すると innerText が全子要素を連結したり、
    // textContent 書き戻しで <span>/<strong> 等の構造が消える致命バグになる。
    let editTarget: HTMLElement = initialTarget as HTMLElement;
    try {
      const range = (doc as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null })
        .caretRangeFromPoint?.(e.clientX, e.clientY);
      const node = range?.startContainer;
      if (node && node.nodeType === Node.TEXT_NODE && node.parentElement) {
        editTarget = node.parentElement;
      } else if (node && node.nodeType === Node.ELEMENT_NODE) {
        editTarget = node as HTMLElement;
      }
    } catch {
      /* fallback: initialTarget */
    }
    // data-edit-id を持つ祖先があればそれを編集単位とする
    // （部分テキストの span や子要素ではなく、論理的なまとまり全体を編集対象に）
    editTarget = resolveEditUnit(editTarget) as HTMLElement;

    // 致命防御: editTarget 自身に data-edit-id が無く、配下に data-edit-id 持ちの
    // 子孫が存在する wrapper（h2 と p 両方を包む div など）に inline edit を許すと、
    // contentEditable 化で plaintext 化されて子要素の構造が破壊される。
    // → ブロックして、ユーザーに具体的な子（h2 か p か）を選び直させる。
    if (
      !editTarget.getAttribute('data-edit-id') &&
      editTarget.querySelector?.('[data-edit-id]')
    ) {
      // 警告だけ出してリターン。アクティブオーバーレイは出す（クリック自体は通常通り選択扱い）
      console.warn(
        '[inspector] inline-edit blocked: clicked a wrapper that contains data-edit-id descendants. ' +
        'Click directly on the heading or paragraph instead.'
      );
      return;
    }

    const tagName = editTarget.tagName.toLowerCase();
    if (INLINE_EDIT_BLOCKED_TAGS.has(tagName)) return;
    if (!INLINE_TEXT_TAGS.has(tagName)) {
      console.warn('[inspector] inline-edit blocked: target is not a text element.', tagName);
      return;
    }
    e.preventDefault();
    e.stopPropagation();

    // 重要: selection を edit 対象に揃える (setLiveText の保存先 = liveTarget が
    // edit 対象と一致しないと、編集反映と保存が別要素に対して起きる)。
    const rect = editTarget.getBoundingClientRect();
    const elementKey = computeElementKey(editTarget);
    usePreviewStore.getState().selectElement(
      {
        tagName,
        text: (editTarget.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120),
        outerHtmlSnippet: (editTarget.outerHTML || '').slice(0, 2000),
        rect: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
        className: editTarget.getAttribute('class') || '',
        ancestors: [],
        bgColor: '',
        elementKey,
      },
      editTarget
    );
    overlays.activeTarget = editTarget;
    positionTo(active, doc, editTarget);

    enableInlineEdit(editTarget, doc, hover, active, overlays);
  };

  const keydown = (ev: Event) => {
    const e = ev as KeyboardEvent;
    if (e.key === 'Escape') {
      hideOverlay(active);
      overlays.activeTarget = null;
      usePreviewStore.getState().clearSelection();
    }
  };

  const repositionActive = () => {
    if (overlays.activeTarget && doc.contains(overlays.activeTarget)) {
      positionTo(active, doc, overlays.activeTarget);
    }
  };

  const scroll = () => {
    hideOverlay(hover);
    repositionActive();
  };

  const resize = () => {
    repositionActive();
  };

  // 選択範囲 (mouse drag で text を選択) を store に同期。
  // setLiveStyle が selectedRange を見て、部分テキストへの style 適用を可能にする。
  //
  // Sticky 仕様: 一度選択された範囲は、新しい非空の選択が入るか、liveTarget が
  // 変わるか、明示的にクリアされるまで保持する。
  // → 右ペインのスライダーを掴んで iframe からフォーカスが外れた瞬間に
  //    Selection が collapsed になっても、選択を維持して部分適用を継続できる。
  const selectionchange = () => {
    const sel = doc.defaultView?.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
      // 空 / 折りたたみ → 何もしない（前の選択を保持）
      return;
    }
    const range = sel.getRangeAt(0);
    if (range.toString().length === 0) {
      // 文字数 0 → 何もしない（前の選択を保持）
      return;
    }
    // 非空の新規選択が入ったら更新（liveTarget 内であろうとなかろうと、
    //   setLiveStyle 側で contains() ガードしてあるので問題ない）
    usePreviewStore.setState({ selectedRange: range.cloneRange() });
  };

  doc.addEventListener('mousemove', move, true);
  doc.addEventListener('click', click, true);
  doc.addEventListener('dblclick', dblclick, true);
  doc.addEventListener('keydown', keydown, true);
  doc.addEventListener('scroll', scroll, true);
  doc.addEventListener('selectionchange', selectionchange);
  doc.defaultView?.addEventListener('resize', resize);

  registry.set(iframe, { move, click, dblclick, keydown, scroll, resize, selectionchange });
}

/**
 * クリック位置の z-stack から「次に選ぶべき要素」を決定する。
 * - 通常クリック → 一番上の要素 (常に同じ動作、繰り返しクリックでもドリルしない)
 * - Alt+クリック → ドリル (明示的に下に潜る)
 *
 * 使い方: 元の click handler から target を選んだ直後に呼んで上書き。
 */
const stackState = new WeakMap<
  Document,
  { x: number; y: number; index: number; stack: Element[] }
>();

function pickFromStack(
  doc: Document,
  e: MouseEvent,
  isOverlay: (el: Element | null) => boolean
): Element | null {
  const x = e.clientX;
  const y = e.clientY;
  const altKey = e.altKey;

  // elementsFromPoint は pointer-events:none の要素を自動的に除外する。
  // build スキルのルールで overlay div には pointer-events-none を必須化したので、
  // 適切に書かれた成果物では overlay は自然に透過してクリックが下の媒体に届く。
  const stack = (doc.elementsFromPoint(x, y) as Element[])
    .filter((el) => !isOverlay(el))
    .filter((el) => el.tagName.toLowerCase() !== 'html');

  if (stack.length === 0) return null;

  let index = 0;
  if (altKey) {
    // Alt+click はスタックの下にドリル (連続で更に下へ)
    const prev = stackState.get(doc);
    const samePoint =
      prev && Math.abs(x - prev.x) <= 10 && Math.abs(y - prev.y) <= 10;
    if (samePoint) {
      index = (prev.index + 1) % stack.length;
    }
  }

  stackState.set(doc, { x, y, index, stack });
  return stack[index] ?? null;
}

export function detachInspector(iframe: HTMLIFrameElement) {
  const doc = getDoc(iframe);
  if (!doc) return;

  const h = registry.get(iframe);
  if (h) {
    doc.removeEventListener('mousemove', h.move, true);
    doc.removeEventListener('click', h.click, true);
    doc.removeEventListener('dblclick', h.dblclick, true);
    doc.removeEventListener('keydown', h.keydown, true);
    doc.removeEventListener('scroll', h.scroll, true);
    doc.removeEventListener('selectionchange', h.selectionchange);
    doc.defaultView?.removeEventListener('resize', h.resize);
    registry.delete(iframe);
  }

  doc.getElementById(HOVER_OVERLAY_ID)?.remove();
  doc.getElementById(ACTIVE_OVERLAY_ID)?.remove();
  overlayRegistry.delete(iframe);

  doc.body.style.cursor = '';
}

/**
 * テキスト要素をインライン編集可能にする。
 * - contentEditable=plaintext-only で plain text 入力に限定
 * - クリック位置にキャレット移動・自動 focus
 * - blur で commit (setLiveText で永続化)
 * - Escape でキャンセル (元のテキストに戻す)
 * - Enter は改行として通常通り入る
 */
function enableInlineEdit(
  el: HTMLElement,
  doc: Document,
  hover: HTMLDivElement,
  active: HTMLDivElement,
  overlays: Overlays
) {
  if (el.getAttribute('data-dan-editing') === '1') return; // 既に編集中
  const original = el.textContent ?? '';

  // contentEditable plaintext-only は Chromium / WebKit でサポート、Firefox は true で代替
  el.setAttribute('contenteditable', 'plaintext-only');
  // フォールバック: plaintext-only 未対応時は true (HTML 入力可だが visually 同じ)
  if (el.contentEditable !== 'plaintext-only') {
    el.setAttribute('contenteditable', 'true');
  }
  el.setAttribute('data-dan-editing', '1');
  el.style.setProperty('outline', '2px dashed rgb(34, 197, 94)', 'important');
  el.style.setProperty('outline-offset', '2px', 'important');
  el.style.setProperty('cursor', 'text', 'important');
  // 改行を保持できるよう pre-wrap を最初から当てておく
  el.style.setProperty('white-space', 'pre-wrap', 'important');

  // 編集中はオーバーレイを邪魔にならないよう非表示
  hideOverlay(hover);
  hideOverlay(active);

  el.focus();
  // 文字列末尾にキャレット移動
  try {
    const sel = doc.defaultView?.getSelection();
    const range = doc.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel?.removeAllRanges();
    sel?.addRange(range);
  } catch {
    /* ignore */
  }

  let cancelled = false;

  // <a>/<button> 等のデフォルト動作 (ナビゲーション・サブミット) を一時的に無効化。
  // click イベント preventDefault は contentEditable のキャレット移動も阻害するので使わない。
  // 代わりに href / type を一時退避して元に戻す。
  const savedHref = el.tagName === 'A' ? el.getAttribute('href') : null;
  const savedTarget = el.tagName === 'A' ? el.getAttribute('target') : null;
  const savedType = el.tagName === 'BUTTON' ? el.getAttribute('type') : null;
  if (el.tagName === 'A') {
    el.removeAttribute('href');
    el.removeAttribute('target');
  }
  if (el.tagName === 'BUTTON') {
    el.setAttribute('type', 'button'); // submit を防ぐ
  }

  const cleanup = () => {
    el.removeAttribute('contenteditable');
    el.removeAttribute('data-dan-editing');
    el.style.removeProperty('outline');
    el.style.removeProperty('outline-offset');
    el.style.removeProperty('cursor');
    el.style.removeProperty('white-space'); // ★ leak fix: pre-wrap を必ず元に戻す
    el.removeEventListener('blur', onBlur, true);
    el.removeEventListener('keydown', onKeyDown, true);
    // <a>/<button> の attrs を復元
    if (savedHref !== null) el.setAttribute('href', savedHref);
    if (savedTarget !== null) el.setAttribute('target', savedTarget);
    if (savedType !== null) el.setAttribute('type', savedType);
    // active overlay を再表示
    if (overlays.activeTarget === el && doc.contains(el)) {
      positionTo(active, doc, el);
    }
  };

  const commit = () => {
    if (cancelled) return;
    const newText = el.innerText ?? el.textContent ?? '';
    if (newText !== original) {
      // setLiveText を呼ぶ (元の選択 + liveTarget が一致してる前提)
      usePreviewStore.getState().setLiveText(newText);
    }
  };

  const onBlur = () => {
    commit();
    cleanup();
  };

  const onKeyDown = (ev: Event) => {
    const e = ev as KeyboardEvent;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      cancelled = true;
      el.textContent = original;
      el.blur();
    }
    // Enter は改行として通常通り処理 (preventDefault しない)
    // Cmd/Ctrl+Enter で確定したい場合はここに追加可能
  };

  el.addEventListener('blur', onBlur, true);
  el.addEventListener('keydown', onKeyDown, true);
}

export function clearActiveHighlight(iframe: HTMLIFrameElement) {
  const doc = getDoc(iframe);
  if (!doc) return;
  const active = doc.getElementById(ACTIVE_OVERLAY_ID);
  if (active) (active as HTMLDivElement).style.display = 'none';
  const ov = overlayRegistry.get(iframe);
  if (ov) ov.activeTarget = null;
}
