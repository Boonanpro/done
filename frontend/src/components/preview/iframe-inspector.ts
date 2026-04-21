'use client';

import { usePreviewStore } from '@/stores/preview-store';

const HOVER_OVERLAY_ID = 'dan-inspector-hover';
const ACTIVE_OVERLAY_ID = 'dan-inspector-active';

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

  const move = (ev: Event) => {
    const e = ev as MouseEvent;
    const target = e.target as Element | null;
    if (!target || isOverlay(target)) return;
    positionTo(hover, doc, target);
  };

  const click = (ev: Event) => {
    const e = ev as MouseEvent;
    e.preventDefault();
    e.stopPropagation();
    const target = e.target as Element | null;
    if (!target || isOverlay(target)) return;

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

    usePreviewStore.getState().selectElement({
      tagName,
      text,
      outerHtmlSnippet,
      rect: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
      className: classAttr,
      ancestors,
      bgColor,
    });
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

export function clearActiveHighlight(iframe: HTMLIFrameElement) {
  const doc = getDoc(iframe);
  if (!doc) return;
  const active = doc.getElementById(ACTIVE_OVERLAY_ID);
  if (active) (active as HTMLDivElement).style.display = 'none';
  const ov = overlayRegistry.get(iframe);
  if (ov) ov.activeTarget = null;
}
