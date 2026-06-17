/**
 * Inspector iframe-side agent（成果物ページ＝iframe の中で動く）。
 *
 * 設計: docs/proposals/inspector_cross_origin.md
 *
 * 旧 `components/preview/iframe-inspector.ts`（親がiframeのDOMを直いじり）の相互作用
 * ロジックを「iframe自身の document/window で動く」形に移植し、選択・編集intentを
 * 親へ postMessage で通知する。iframe は backend に書き込まない（保存は親が代行）。
 *
 * DOM を触るのはこのファイル（iframe内）だけ。親はシリアライズ可能なメッセージのみ扱う。
 */
'use client';

import {
  wrapInspectorMessage,
  isInspectorEnvelope,
  isAllowedInspectorOrigin,
  type IframeToParentMessage,
  type ParentToIframeMessage,
  type SelectionSnapshot,
  type SerializableRect,
  type InspectorMode,
  type AncestorInfo,
  type MediaInfo,
} from './inspector-protocol';
import { computeElementKey, resolveEditUnit, findElementByKey } from '@/components/dan/inspector-runtime';
import { isEditableTextLeaf } from './inspector-edit-target';
import { applyModelToElement, selectionToTextRange } from './inspector-render';
import { readModelFromAttrs } from './inspector-model';
import type { EditModel } from './inspector-model';

const HOVER_OVERLAY_ID = 'dan-inspector-hover';
const ACTIVE_OVERLAY_ID = 'dan-inspector-active';

const INLINE_EDIT_BLOCKED_TAGS = new Set([
  'input', 'textarea', 'select', 'option', 'optgroup',
  'img', 'video', 'audio', 'iframe', 'canvas', 'svg', 'embed', 'object',
  'script', 'style', 'meta', 'link', 'br', 'hr', 'html', 'body', 'head',
]);
const INLINE_TEXT_TAGS = new Set([
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'span', 'a', 'li', 'label', 'button', 'strong', 'em',
  'td', 'th', 'figcaption', 'div',
]);

/** パネルが必要とする computedStyle のキー（snapshot に載せる分）。
 *  inspector-panel.tsx / image-section.tsx / video-section.tsx が読む実キーに合わせる。 */
const SNAPSHOT_STYLE_KEYS = [
  'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'color', 'textAlign', 'fontFamily',
  'width', 'height', 'aspectRatio',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
  'marginTop', 'marginBottom',
  'borderTopLeftRadius', 'borderTopWidth', 'borderTopColor', 'opacity',
  'backgroundColor', 'backgroundImage', 'backgroundSize', 'backgroundPosition',
  'objectFit', 'objectPosition', 'filter',
] as const;

let initialized = false;
let slug = '';
let parentOrigin = '*';
let allowedOrigins: string[] = [];
let mode: InspectorMode = 'off';
let activeTarget: Element | null = null;
let gotParentMessage = false;

// ---------------------------------------------------------------------------
// メッセージ送信
// ---------------------------------------------------------------------------

function post(msg: IframeToParentMessage): void {
  try {
    window.parent?.postMessage(wrapInspectorMessage(msg), parentOrigin);
  } catch {
    /* parent 不在/クロスオリジン拒否は無視 */
  }
}

// ---------------------------------------------------------------------------
// オーバーレイ（iframe 自身の document に描く）
// ---------------------------------------------------------------------------

function createOverlay(id: string, border: string, fill: string, z: number, shadow?: string): HTMLDivElement {
  const existing = document.getElementById(id);
  if (existing) return existing as HTMLDivElement;
  const el = document.createElement('div');
  el.id = id;
  el.setAttribute('data-dan-preview-ui', '1');
  el.style.cssText = [
    'position:absolute', 'pointer-events:none', `border:2px solid ${border}`,
    `background:${fill}`, `z-index:${z}`, 'display:none', 'box-sizing:border-box',
    'transition:none', 'border-radius:2px', shadow ? `box-shadow:${shadow}` : '',
  ].filter(Boolean).join(';');
  document.body.appendChild(el);
  return el;
}

function getOverlay(id: string): HTMLDivElement | null {
  return document.getElementById(id) as HTMLDivElement | null;
}

function positionTo(overlay: HTMLDivElement | null, target: Element): void {
  if (!overlay) return;
  const r = target.getBoundingClientRect();
  overlay.style.display = 'block';
  overlay.style.left = `${r.left + window.scrollX}px`;
  overlay.style.top = `${r.top + window.scrollY}px`;
  overlay.style.width = `${r.width}px`;
  overlay.style.height = `${r.height}px`;
}

function hide(overlay: HTMLDivElement | null): void {
  if (overlay) overlay.style.display = 'none';
}

// ---------------------------------------------------------------------------
// 判定ヘルパ
// ---------------------------------------------------------------------------

function isOverlay(el: Element | null): boolean {
  return !!el?.id && (el.id === HOVER_OVERLAY_ID || el.id === ACTIVE_OVERLAY_ID);
}
function isEditing(el: Element | null): boolean {
  return !!el && el.getAttribute('data-dan-editing') === '1';
}
function isPreviewUi(el: Element | null): boolean {
  return !!el && typeof el.closest === 'function' && !!el.closest('[data-dan-preview-ui]');
}

function toRect(el: Element): SerializableRect {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, width: r.width, height: r.height };
}

function buildSnapshot(target: Element): SelectionSnapshot {
  const tagName = target.tagName.toLowerCase();
  const win = target.ownerDocument.defaultView;
  const cs = win ? win.getComputedStyle(target) : null;
  const computedStyles: Record<string, string> = {};
  if (cs) {
    for (const k of SNAPSHOT_STYLE_KEYS) {
      const v = (cs as unknown as Record<string, string>)[k];
      if (v != null) computedStyles[k] = String(v);
    }
  }
  const ancestors: AncestorInfo[] = [];
  let cursor: Element | null = target.parentElement;
  for (let d = 0; d < 3 && cursor && cursor.tagName.toLowerCase() !== 'body'; d++) {
    ancestors.push({
      tagName: cursor.tagName.toLowerCase(),
      className: cursor.getAttribute('class') || '',
      elementKey: cursor.getAttribute('data-edit-id') ? `@${cursor.getAttribute('data-edit-id')}` : null,
    });
    cursor = cursor.parentElement;
  }
  let media: MediaInfo | undefined;
  if (tagName === 'img') {
    media = { kind: 'img', src: target.getAttribute('src'), alt: target.getAttribute('alt'),
      objectFit: computedStyles.objectFit, objectPosition: computedStyles.objectPosition };
  } else if (tagName === 'video') {
    media = { kind: 'video', src: target.getAttribute('src'), poster: target.getAttribute('poster'),
      objectFit: computedStyles.objectFit, objectPosition: computedStyles.objectPosition };
  }
  return {
    elementKey: computeElementKey(target),
    tagName,
    rect: toRect(target),
    text: (target.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120),
    className: target.getAttribute('class') || '',
    outerHtmlSnippet: (target.outerHTML || '').slice(0, 2000),
    ancestors,
    computedStyles,
    bgColor: computedStyles.backgroundColor || null,
    isTextLeaf: isEditableTextLeaf(target),
    media,
  };
}

// ---------------------------------------------------------------------------
// z-stack drill（移植元 pickFromStack 相当）
// ---------------------------------------------------------------------------

let stackState: { x: number; y: number; index: number; stack: Element[] } | null = null;

function pickFromStack(e: MouseEvent): Element | null {
  const x = e.clientX, y = e.clientY;
  const stack = (document.elementsFromPoint(x, y) as Element[])
    .filter((el) => !isOverlay(el))
    .filter((el) => el.tagName.toLowerCase() !== 'html');
  if (stack.length === 0) return null;
  let index = 0;
  if (e.altKey) {
    const prev = stackState;
    if (prev && Math.abs(x - prev.x) <= 10 && Math.abs(y - prev.y) <= 10) {
      index = (prev.index + 1) % stack.length;
    }
  }
  stackState = { x, y, index, stack };
  return stack[index] ?? null;
}

// ---------------------------------------------------------------------------
// 相互作用ハンドラ
// ---------------------------------------------------------------------------

function onMove(ev: Event): void {
  const e = ev as MouseEvent;
  const t = e.target as Element | null;
  if (!t || isOverlay(t)) return;
  if (isPreviewUi(t) || isEditing(t)) { hide(getOverlay(HOVER_OVERLAY_ID)); return; }
  positionTo(getOverlay(HOVER_OVERLAY_ID), t);
}

function onClick(ev: Event): void {
  const e = ev as MouseEvent;
  const initial = e.target as Element | null;
  if (!initial || isOverlay(initial)) return;
  if (isPreviewUi(initial)) return; // プレビューUI(画面切替等)はネイティブ通す
  if (isEditing(initial)) return;
  e.preventDefault();
  e.stopPropagation();
  const stackTarget = pickFromStack(e) || initial;
  const target = e.altKey ? stackTarget : resolveEditUnit(stackTarget);
  activeTarget = target;
  positionTo(getOverlay(ACTIVE_OVERLAY_ID), target);
  post({ type: 'inspector:selected', payload: buildSnapshot(target) });
}

function onDblClick(ev: Event): void {
  const e = ev as MouseEvent;
  const initial = e.target as Element | null;
  if (!initial || isOverlay(initial) || isPreviewUi(initial) || isEditing(initial)) return;

  let editTarget: HTMLElement = initial as HTMLElement;
  try {
    const range = (document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null })
      .caretRangeFromPoint?.(e.clientX, e.clientY);
    const node = range?.startContainer;
    if (node && node.nodeType === Node.TEXT_NODE && node.parentElement) editTarget = node.parentElement;
    else if (node && node.nodeType === Node.ELEMENT_NODE) editTarget = node as HTMLElement;
  } catch { /* fallback initial */ }

  const localLeaf = editTarget.children.length === 0 && !!editTarget.getAttribute('data-edit-id');
  if (!localLeaf) editTarget = resolveEditUnit(editTarget) as HTMLElement;

  const tagName = editTarget.tagName.toLowerCase();
  if (INLINE_EDIT_BLOCKED_TAGS.has(tagName) || !INLINE_TEXT_TAGS.has(tagName)) return;
  if (!isEditableTextLeaf(editTarget)) return;

  e.preventDefault();
  e.stopPropagation();
  activeTarget = editTarget;
  positionTo(getOverlay(ACTIVE_OVERLAY_ID), editTarget);
  post({ type: 'inspector:selected', payload: buildSnapshot(editTarget) });
  enableInlineEdit(editTarget);
}

function onKeyDown(ev: Event): void {
  const e = ev as KeyboardEvent;
  if (e.key === 'Escape') {
    hide(getOverlay(ACTIVE_OVERLAY_ID));
    activeTarget = null;
    post({ type: 'inspector:selection-range', payload: { elementKey: null } });
  }
}

function repositionActive(): void {
  if (activeTarget && document.contains(activeTarget)) positionTo(getOverlay(ACTIVE_OVERLAY_ID), activeTarget);
}
function onScroll(): void { hide(getOverlay(HOVER_OVERLAY_ID)); repositionActive(); }
function onResize(): void { repositionActive(); }

function onSelectionChange(): void {
  const sel = document.defaultView?.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;
  const range = sel.getRangeAt(0);
  if (range.toString().length === 0) return;
  // 選択範囲を、選択を含む edit-unit 内の文字オフセットに変換して親へ通知。
  const unit = activeTarget && activeTarget.contains(range.commonAncestorContainer)
    ? (activeTarget as HTMLElement)
    : (resolveEditUnit(range.commonAncestorContainer.parentElement || range.commonAncestorContainer as Element) as HTMLElement);
  if (!unit) return;
  try {
    const tr = selectionToTextRange(unit, range);
    if (tr) post({ type: 'inspector:selection-range', payload: { elementKey: computeElementKey(unit), start: tr.start, end: tr.end } });
  } catch { /* ignore */ }
}

// ---------------------------------------------------------------------------
// インライン編集（移植元 enableInlineEdit 相当。commit で親へ通知）
// ---------------------------------------------------------------------------

function enableInlineEdit(el: HTMLElement): void {
  if (el.getAttribute('data-dan-editing') === '1') return;
  const original = el.textContent ?? '';
  const key = computeElementKey(el);

  el.setAttribute('contenteditable', 'plaintext-only');
  if (el.contentEditable !== 'plaintext-only') el.setAttribute('contenteditable', 'true');
  el.setAttribute('data-dan-editing', '1');
  el.style.setProperty('outline', '2px dashed rgb(34,197,94)', 'important');
  el.style.setProperty('outline-offset', '2px', 'important');
  el.style.setProperty('cursor', 'text', 'important');
  el.style.setProperty('white-space', 'pre-wrap', 'important');
  hide(getOverlay(HOVER_OVERLAY_ID));
  hide(getOverlay(ACTIVE_OVERLAY_ID));
  el.focus();
  try {
    const sel = document.defaultView?.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel?.removeAllRanges();
    sel?.addRange(range);
  } catch { /* ignore */ }

  let cancelled = false;
  const savedHref = el.tagName === 'A' ? el.getAttribute('href') : null;
  const savedTarget = el.tagName === 'A' ? el.getAttribute('target') : null;
  const savedType = el.tagName === 'BUTTON' ? el.getAttribute('type') : null;
  if (el.tagName === 'A') { el.removeAttribute('href'); el.removeAttribute('target'); }
  if (el.tagName === 'BUTTON') el.setAttribute('type', 'button');

  const cleanup = () => {
    el.removeAttribute('contenteditable');
    el.removeAttribute('data-dan-editing');
    el.style.removeProperty('outline');
    el.style.removeProperty('outline-offset');
    el.style.removeProperty('cursor');
    el.style.removeProperty('white-space');
    el.removeEventListener('blur', onBlur, true);
    el.removeEventListener('keydown', onKey, true);
    if (savedHref !== null) el.setAttribute('href', savedHref);
    if (savedTarget !== null) el.setAttribute('target', savedTarget);
    if (savedType !== null) el.setAttribute('type', savedType);
    if (activeTarget === el && document.contains(el)) positionTo(getOverlay(ACTIVE_OVERLAY_ID), el);
  };
  const commit = () => {
    if (cancelled) return;
    const newText = el.innerText ?? el.textContent ?? '';
    console.log('[DAN-INSP] agent.commit', { key, changed: newText !== original, parentOrigin });
    if (newText !== original) {
      // 親へ「テキスト編集確定」を通知（生テキスト）。model 構築・保存は親が行う。
      post({ type: 'inspector:text-committed', payload: { elementKey: key, text: newText } });
      console.log('[DAN-INSP] agent.post text-committed ->', parentOrigin);
    }
  };
  const onBlur = () => { commit(); cleanup(); };
  const onKey = (ev2: Event) => {
    const e2 = ev2 as KeyboardEvent;
    if (e2.key === 'Escape') { e2.preventDefault(); e2.stopPropagation(); cancelled = true; el.textContent = original; el.blur(); }
  };
  el.addEventListener('blur', onBlur, true);
  el.addEventListener('keydown', onKey, true);
}

// ---------------------------------------------------------------------------
// モード切替（リスナ/オーバーレイの ON/OFF）
// ---------------------------------------------------------------------------

function attach(): void {
  createOverlay(HOVER_OVERLAY_ID, 'rgba(59,130,246,0.9)', 'rgba(59,130,246,0.12)', 2147483646);
  createOverlay(ACTIVE_OVERLAY_ID, 'rgb(34,197,94)', 'rgba(34,197,94,0.1)', 2147483647, '0 0 0 4px rgba(34,197,94,0.2)');
  document.body.style.cursor = 'crosshair';
  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  document.addEventListener('dblclick', onDblClick, true);
  document.addEventListener('keydown', onKeyDown, true);
  document.addEventListener('scroll', onScroll, true);
  document.addEventListener('selectionchange', onSelectionChange);
  window.addEventListener('resize', onResize);
}

function detach(): void {
  document.removeEventListener('mousemove', onMove, true);
  document.removeEventListener('click', onClick, true);
  document.removeEventListener('dblclick', onDblClick, true);
  document.removeEventListener('keydown', onKeyDown, true);
  document.removeEventListener('scroll', onScroll, true);
  document.removeEventListener('selectionchange', onSelectionChange);
  window.removeEventListener('resize', onResize);
  getOverlay(HOVER_OVERLAY_ID)?.remove();
  getOverlay(ACTIVE_OVERLAY_ID)?.remove();
  document.body.style.cursor = '';
  activeTarget = null;
}

function setMode(next: InspectorMode): void {
  if (next === mode) return;
  if (mode !== 'off') detach();
  mode = next;
  if (mode === 'edit' || mode === 'comment') attach();
}

// ---------------------------------------------------------------------------
// 親 → iframe コマンド適用
// ---------------------------------------------------------------------------

function applyDanInspector(key: string, styles: Record<string, string>, attrs: Record<string, unknown>): void {
  // ランタイムが公開する API（あれば）を優先。無ければ自前で適用。
  const api = (window as unknown as { __DAN_INSPECTOR__?: { applyOverride: (k: string, s: Record<string, string>, a: Record<string, unknown>) => void } }).__DAN_INSPECTOR__;
  if (api?.applyOverride) { api.applyOverride(key, styles, attrs); return; }
  const el = findElementByKey(document, key) as HTMLElement | null;
  if (!el) return;
  const model = readModelFromAttrs(attrs);
  if (model) applyModelToElement(el, model);
  for (const [k, v] of Object.entries(styles || {})) el.style.setProperty(k, v, 'important');
}

function handleParentMessage(msg: ParentToIframeMessage): void {
  switch (msg.type) {
    case 'inspector:set-mode':
      setMode(msg.payload.mode);
      break;
    case 'inspector:apply': {
      const { elementKey, model, styles, attrs } = msg.payload;
      if (model) {
        // model も __DAN_INSPECTOR__ のキャッシュに載せる（MutationObserver が React 再描画
        // やクライアント遷移後にも再適用できるようにする）。直接 applyModelToElement だと
        // キャッシュに入らず、ページ遷移で編集が消える。
        applyDanInspector(elementKey, {}, { model_v2: JSON.stringify(model) });
      } else {
        applyDanInspector(elementKey, styles || {}, attrs || {});
      }
      if (activeTarget) positionTo(getOverlay(ACTIVE_OVERLAY_ID), activeTarget);
      break;
    }
    case 'inspector:apply-overrides':
      console.log('[DAN-INSP] agent.apply-overrides count=', (msg.payload.overrides || []).length);
      for (const row of msg.payload.overrides || []) {
        applyDanInspector(row.element_key, (row.styles as Record<string, string>) || {}, (row.attrs as Record<string, unknown>) || {});
      }
      break;
    case 'inspector:clear-selection':
      hide(getOverlay(ACTIVE_OVERLAY_ID));
      activeTarget = null;
      break;
    case 'inspector:request-snapshot': {
      const el = findElementByKey(document, msg.payload.elementKey);
      if (el) post({ type: 'inspector:selected', payload: buildSnapshot(el) });
      break;
    }
  }
}

// ---------------------------------------------------------------------------
// 初期化
// ---------------------------------------------------------------------------

/** 成果物ページ(iframe内)で1度だけ呼ぶ。inspector-runtime から起動する。 */
export function initInspectorIframeAgent(opts: { slug: string; allowedOrigins?: string[] }): void {
  if (initialized) return;
  if (typeof window === 'undefined') return;
  // iframe でない（トップレベル公開閲覧）なら何もしない。
  let inIframe = false;
  try { inIframe = window.top !== window.self; } catch { inIframe = true; }
  if (!inIframe) return;

  initialized = true;
  slug = opts.slug;
  allowedOrigins = (opts.allowedOrigins || []).map((o) => o.replace(/\/+$/, ''));
  // 親オリジンの初期推定（referrer）。受信時に refine する。
  try { if (document.referrer) parentOrigin = new URL(document.referrer).origin; } catch { /* keep '*' */ }

  window.addEventListener('message', (event: MessageEvent) => {
    if (!isInspectorEnvelope(event.data)) return;
    if (!isAllowedInspectorOrigin(event.origin, window.location.origin, allowedOrigins)) return;
    gotParentMessage = true; // 親のリスナが立った＝ready再送を止めてよい
    parentOrigin = event.origin; // 以後の送信先を確定
    console.log('[DAN-INSP] agent.recv', (event.data as { type?: string }).type);
    handleParentMessage(event.data as ParentToIframeMessage);
  });

  // ready を「親から最初のメッセージが来るまで」数回再送する。
  // ナビゲーション直後は親がリスナを張り直すまで時間差があり、1回だと取りこぼす。
  let tries = 0;
  const announce = () => {
    if (gotParentMessage || tries >= 8) return;
    tries++;
    post({ type: 'inspector:ready', payload: { slug } });
    setTimeout(announce, 400);
  };
  console.log('[DAN-INSP] agent.init (inIframe) slug=', slug);
  announce();
}
