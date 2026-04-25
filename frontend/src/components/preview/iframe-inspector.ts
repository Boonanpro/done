'use client';

import { usePreviewStore } from '@/stores/preview-store';
import { computeElementKey } from '@/components/dan/inspector-runtime';

const HOVER_OVERLAY_ID = 'dan-inspector-hover';
const ACTIVE_OVERLAY_ID = 'dan-inspector-active';

// インライン編集対象外タグ (フォーム要素や置換要素は触らない)
const INLINE_EDIT_BLOCKED_TAGS = new Set([
  'input', 'textarea', 'select', 'option', 'optgroup',
  'img', 'video', 'audio', 'iframe', 'canvas', 'svg', 'embed', 'object',
  'script', 'style', 'meta', 'link', 'br', 'hr',
  'html', 'body', 'head',
]);

type Handlers = {
  move: (e: Event) => void;
  click: (e: Event) => void;
  keydown: (e: Event) => void;
  scroll: (e: Event) => void;
  resize: (e: Event) => void;
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
    const target = pickFromStack(doc, e, isOverlay) || initialTarget;

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

    // インライン編集を有効化:
    // - フォーム/置換要素 (img, video, input 等) はスキップ
    // - 子要素を含むものはスキップ (構造破壊防止)
    // - それ以外なら全部対象 (div, section, header の中身など何でも)
    const hasChildElements = target.children.length > 0;
    if (!INLINE_EDIT_BLOCKED_TAGS.has(tagName) && !hasChildElements) {
      enableInlineEdit(target as HTMLElement, doc, hover, active, overlays);
    }
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

  doc.addEventListener('mousemove', move, true);
  doc.addEventListener('click', click, true);
  doc.addEventListener('keydown', keydown, true);
  doc.addEventListener('scroll', scroll, true);
  doc.defaultView?.addEventListener('resize', resize);

  registry.set(iframe, { move, click, keydown, scroll, resize });
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

/**
 * 「装飾的な空 div」 (テキスト無し・interactive 属性無し・子要素無し)
 * の上に重なってる場合、下にある img/video を優先選択するためのヘルパー。
 */
function isDecorativeOverlay(el: Element): boolean {
  if (el.tagName !== 'DIV') return false;
  if (el.children.length > 0) return false;
  const text = (el.textContent || '').trim();
  if (text.length > 0) return false;
  // interactive 要素なら触らない
  if (el.hasAttribute('role') || el.hasAttribute('onclick')) return false;
  if (el.id) return false;
  return true;
}

function pickFromStack(
  doc: Document,
  e: MouseEvent,
  isOverlay: (el: Element | null) => boolean
): Element | null {
  const x = e.clientX;
  const y = e.clientY;
  const altKey = e.altKey;

  const stack = (doc.elementsFromPoint(x, y) as Element[])
    .filter((el) => !isOverlay(el))
    .filter((el) => el.tagName.toLowerCase() !== 'html');

  if (stack.length === 0) return null;

  let index = 0;
  if (altKey) {
    // Alt+click のみドリル動作 (連続 alt+click で更に下へ)
    const prev = stackState.get(doc);
    const samePoint =
      prev && Math.abs(x - prev.x) <= 10 && Math.abs(y - prev.y) <= 10;
    if (samePoint) {
      index = (prev.index + 1) % stack.length;
    }
  } else {
    // 通常クリック: 装飾 overlay はスキップして下の媒体を選ぶ
    // 「上から順に走査、装飾 div が連続したらスキップ、最初の意味ある要素 or 媒体を選択」
    for (let i = 0; i < stack.length; i++) {
      const el = stack[i];
      // img / video が見つかったら即採用 (装飾 div 越しでも見えてるはずなので)
      if (el.tagName === 'IMG' || el.tagName === 'VIDEO') {
        index = i;
        break;
      }
      // 装飾 div ならスキップして次へ
      if (isDecorativeOverlay(el)) {
        continue;
      }
      // それ以外の意味ある要素ならそこで採用
      index = i;
      break;
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
    doc.removeEventListener('keydown', h.keydown, true);
    doc.removeEventListener('scroll', h.scroll, true);
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

  const cleanup = () => {
    el.removeAttribute('contenteditable');
    el.removeAttribute('data-dan-editing');
    el.style.removeProperty('outline');
    el.style.removeProperty('outline-offset');
    el.style.removeProperty('cursor');
    el.removeEventListener('blur', onBlur, true);
    el.removeEventListener('keydown', onKeyDown, true);
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
