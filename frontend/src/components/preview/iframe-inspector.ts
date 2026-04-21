'use client';

import { usePreviewStore } from '@/stores/preview-store';

const STYLE_ID = 'dan-inspector-style';
const HOVER_ATTR = 'data-dan-hover';
const ACTIVE_ATTR = 'data-dan-active';

const INSPECTOR_CSS = `
  [${HOVER_ATTR}] {
    outline: 2px solid rgba(59, 130, 246, 0.85) !important;
    outline-offset: 1px !important;
    cursor: crosshair !important;
  }
  [${ACTIVE_ATTR}] {
    outline: 2px solid rgb(34, 197, 94) !important;
    outline-offset: 1px !important;
    box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.15) !important;
  }
`;

type Handlers = {
  move: (e: Event) => void;
  click: (e: Event) => void;
  keydown: (e: Event) => void;
};

const registry = new WeakMap<HTMLIFrameElement, Handlers>();

function getDoc(iframe: HTMLIFrameElement): Document | null {
  try {
    return iframe.contentDocument;
  } catch {
    return null;
  }
}

export function attachInspector(iframe: HTMLIFrameElement) {
  const doc = getDoc(iframe);
  if (!doc) return;

  detachInspector(iframe);

  if (!doc.getElementById(STYLE_ID)) {
    const styleEl = doc.createElement('style');
    styleEl.id = STYLE_ID;
    styleEl.textContent = INSPECTOR_CSS;
    doc.head.appendChild(styleEl);
  }

  let currentHover: Element | null = null;

  const move = (ev: Event) => {
    const e = ev as MouseEvent;
    const target = e.target as Element | null;
    if (!target || target === currentHover) return;
    if (currentHover) currentHover.removeAttribute(HOVER_ATTR);
    currentHover = target;
    target.setAttribute(HOVER_ATTR, '');
  };

  const click = (ev: Event) => {
    const e = ev as MouseEvent;
    e.preventDefault();
    e.stopPropagation();
    const target = e.target as Element | null;
    if (!target) return;

    doc.querySelectorAll(`[${ACTIVE_ATTR}]`).forEach((el) => el.removeAttribute(ACTIVE_ATTR));
    target.setAttribute(ACTIVE_ATTR, '');

    const rect = target.getBoundingClientRect();
    const tagName = target.tagName.toLowerCase();
    const text = (target.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    const outerHtmlSnippet = (target.outerHTML || '').slice(0, 400);

    usePreviewStore.getState().selectElement({
      tagName,
      text,
      outerHtmlSnippet,
      rect: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
    });
  };

  const keydown = (ev: Event) => {
    const e = ev as KeyboardEvent;
    if (e.key === 'Escape') {
      doc.querySelectorAll(`[${ACTIVE_ATTR}]`).forEach((el) => el.removeAttribute(ACTIVE_ATTR));
      usePreviewStore.getState().clearSelection();
    }
  };

  doc.addEventListener('mousemove', move, true);
  doc.addEventListener('click', click, true);
  doc.addEventListener('keydown', keydown, true);

  registry.set(iframe, { move, click, keydown });
}

export function detachInspector(iframe: HTMLIFrameElement) {
  const doc = getDoc(iframe);
  if (!doc) return;

  const h = registry.get(iframe);
  if (h) {
    doc.removeEventListener('mousemove', h.move, true);
    doc.removeEventListener('click', h.click, true);
    doc.removeEventListener('keydown', h.keydown, true);
    registry.delete(iframe);
  }

  doc.querySelectorAll(`[${HOVER_ATTR}], [${ACTIVE_ATTR}]`).forEach((el) => {
    el.removeAttribute(HOVER_ATTR);
    el.removeAttribute(ACTIVE_ATTR);
  });

  const styleEl = doc.getElementById(STYLE_ID);
  if (styleEl) styleEl.remove();
}

export function clearActiveHighlight(iframe: HTMLIFrameElement) {
  const doc = getDoc(iframe);
  if (!doc) return;
  doc.querySelectorAll(`[${ACTIVE_ATTR}]`).forEach((el) => el.removeAttribute(ACTIVE_ATTR));
}
