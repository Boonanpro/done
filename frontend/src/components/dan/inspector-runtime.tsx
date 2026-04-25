'use client';

/**
 * InspectorRuntime
 *
 * デモページに注入されるクライアントコンポーネント。
 * 外部インスペクタ（右ペイン）が記録した overrides をランタイムで DOM に適用する。
 *
 * - マウント時: /api/v1/inspector-overrides から slug 用の overrides をフェッチ → 適用
 * - React 再レンダ時: MutationObserver で DOM 変化を検知 → 再適用
 * - 親ウィンドウから直接呼べる API を window.__DAN_INSPECTOR__ に公開
 *   （preview の iframe として埋め込まれるケース: parent が直接 applyOverride を叩く）
 *
 * 要素識別は DOM ツリー上のパス（e.g. 'div[0]>section[2]>video[0]'）。
 * JSX ファイルには一切触らないので HMR rebuild を誘発しない。
 */

import { useEffect } from 'react';

export type OverrideEntry = {
  styles?: Record<string, string>;
  attrs?: Record<string, string>;
};

const WINDOW_KEY = '__DAN_INSPECTOR__';

export function computeElementKey(el: Element): string {
  if (!el || !el.ownerDocument) return '';
  const root = el.ownerDocument.body;
  if (!root) return '';
  const parts: string[] = [];
  let cur: Element | null = el;
  // body 直下までのパス
  while (cur && cur !== root) {
    const parentEl: Element | null = cur.parentElement;
    if (!parentEl) break;
    const siblings = Array.from(parentEl.children);
    const idx = siblings.indexOf(cur);
    parts.unshift(`${cur.tagName.toLowerCase()}[${idx}]`);
    cur = parentEl;
  }
  return parts.join('>');
}

export function findElementByKey(doc: Document, key: string): Element | null {
  if (!key) return null;
  const parts = key.split('>');
  let cur: Element = doc.body;
  for (const part of parts) {
    const m = part.match(/^(.+?)\[(\d+)\]$/);
    if (!m) return null;
    const [, tag, idxStr] = m;
    const idx = parseInt(idxStr, 10);
    const children = cur.children;
    const child = children[idx];
    if (!child) return null;
    if (child.tagName.toLowerCase() !== tag.toLowerCase()) return null;
    cur = child;
  }
  return cur;
}

function applyToElement(
  el: Element,
  styles: Record<string, string> | undefined,
  attrs: Record<string, string> | undefined
) {
  const htmlEl = el as HTMLElement;
  // 編集中の要素には textContent / src 等の上書きをしない (ユーザー入力を破壊しないため)。
  // styles は無害なので適用しても OK。
  const isEditing = el.getAttribute('data-dan-editing') === '1';

  if (styles) {
    for (const [prop, val] of Object.entries(styles)) {
      try {
        htmlEl.style.setProperty(prop, val, 'important');
      } catch {
        /* ignore */
      }
    }
  }
  if (attrs && !isEditing) {
    // html と text が両方ある場合は html を優先 (text は古い形式)
    const hasHtml = 'html' in attrs;
    for (const [name, val] of Object.entries(attrs)) {
      try {
        // 特殊キー "text" は textContent として扱う。 html がある場合はスキップ。
        if (name === 'text') {
          if (hasHtml) continue;
          if (el.textContent !== val) {
            el.textContent = val;
          }
          continue;
        }
        // 特殊キー "html" は innerHTML として扱う (部分テキスト styling 用)
        if (name === 'html') {
          if (el.innerHTML !== val) {
            el.innerHTML = val;
          }
          continue;
        }
        el.setAttribute(name, val);
        // <video> は src 変更後 load() しないと再ロードされない
        if (name === 'src' && el.tagName === 'VIDEO') {
          (el as HTMLVideoElement).load();
        }
      } catch {
        /* ignore */
      }
    }
  }
}

type DanInspectorApi = {
  slug: string;
  computeKey: (el: Element) => string;
  findByKey: (key: string) => Element | null;
  applyOverride: (key: string, styles: Record<string, string>, attrs: Record<string, string>) => void;
  reapplyAll: () => void;
};

export function InspectorRuntime({ slug }: { slug: string }) {
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const doc = document;
    const cache: Record<string, OverrideEntry> = {};

    const applyAll = () => {
      for (const [key, patch] of Object.entries(cache)) {
        const el = findElementByKey(doc, key);
        if (el) applyToElement(el, patch.styles, patch.attrs);
      }
    };

    const fetchAndApply = async () => {
      try {
        const res = await fetch(
          `/api/v1/inspector-overrides?slug=${encodeURIComponent(slug)}`,
          { credentials: 'include' }
        );
        if (!res.ok) return;
        const rows = (await res.json()) as Array<{
          element_key: string;
          styles: Record<string, string> | null;
          attrs: Record<string, string> | null;
        }>;
        for (const r of rows) {
          cache[r.element_key] = {
            styles: r.styles || {},
            attrs: r.attrs || {},
          };
        }
        applyAll();
        // localStorage を server と同期（次回 pre-paint で使う）
        try {
          const lsKey = `dan-inspector-overrides-${slug}`;
          const mapped = rows.map((r) => ({
            elementKey: r.element_key,
            styles: r.styles || {},
            attrs: r.attrs || {},
          }));
          localStorage.setItem(lsKey, JSON.stringify(mapped));
        } catch {
          /* ignore */
        }
      } catch (e) {
        console.warn('[InspectorRuntime] fetch failed', e);
      }
    };

    // 初回フェッチ & 適用
    fetchAndApply();

    // 親ウィンドウから直接呼べる API
    const api: DanInspectorApi = {
      slug,
      computeKey: computeElementKey,
      findByKey: (key) => findElementByKey(doc, key),
      applyOverride: (key, styles, attrs) => {
        const el = findElementByKey(doc, key);
        if (el) applyToElement(el, styles, attrs);
        // キャッシュ更新（MutationObserver 再描画対策）
        cache[key] = {
          styles: { ...(cache[key]?.styles || {}), ...(styles || {}) },
          attrs: { ...(cache[key]?.attrs || {}), ...(attrs || {}) },
        };
      },
      reapplyAll: applyAll,
    };
    (window as unknown as Record<string, DanInspectorApi>)[WINDOW_KEY] = api;

    // React 再レンダ時に overrides を再適用するための MutationObserver
    let scheduled = false;
    const throttled = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        applyAll();
      });
    };
    const observer = new MutationObserver(throttled);
    observer.observe(doc.body, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      delete (window as unknown as Record<string, DanInspectorApi | undefined>)[WINDOW_KEY];
    };
  }, [slug]);

  return null;
}
