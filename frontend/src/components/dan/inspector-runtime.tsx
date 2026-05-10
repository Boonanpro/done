'use client';

/**
 * InspectorRuntime
 *
 * 編集ページに注入されるクライアントコンポーネント。
 * 親ウィンドウのインスペクタが記録した overrides をランタイムで DOM に適用する。
 *
 * 識別子の優先順位:
 *   1) ancestor の data-edit-id 属性 → key = `@${editId}`（推奨。構造変化に強い）
 *   2) DOM ツリーパス → key = `div[0]>section[2]>...`（後方互換、廃止予定）
 *
 * データ形式:
 *   - v2: attrs.model_v2 に EditModel の JSON 文字列。{ text, blockStyle, spans, attrs }
 *   - v1: attrs.html / attrs.text （旧 patch 路線、後方互換のため migrate して読む）
 */

import { useEffect } from 'react';
import { emptyModel, type EditModel } from '@/lib/inspector-model';
import { applyModelToElement } from '@/lib/inspector-render';
import { normalizeToModel } from '@/lib/inspector-migrate';

/** 旧コードとの互換のために残す型エイリアス。 */
export type OverrideEntry = {
  styles?: Record<string, string>;
  attrs?: Record<string, unknown>;
};

const WINDOW_KEY = '__DAN_INSPECTOR__';

/**
 * 要素から識別キーを計算する。
 * - data-edit-id を持つ祖先があればそれを使う（推奨パス）
 * - 無ければ DOM パス（後方互換、生成済み旧ページ用）
 */
export function computeElementKey(el: Element): string {
  if (!el || !el.ownerDocument) return '';
  // 1) data-edit-id を持つ祖先を探す
  let cur: Element | null = el;
  while (cur && cur !== el.ownerDocument.body) {
    const id = cur.getAttribute && cur.getAttribute('data-edit-id');
    if (id) return `@${id}`;
    cur = cur.parentElement;
  }
  // 2) フォールバック: DOM パス
  return computeDomPathKey(el);
}

function computeDomPathKey(el: Element): string {
  const root = el.ownerDocument?.body;
  if (!root) return '';
  const parts: string[] = [];
  let cur: Element | null = el;
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

/**
 * 編集対象として実際に作用させる「edit unit」を返す。
 * - data-edit-id を持つ祖先があればそれを返す
 * - 無ければ自分自身を返す
 *
 * iframe-inspector の click/dblclick で leaf 要素を取った後、これを通して
 * 「論理的な編集単位」に揃える。
 */
export function resolveEditUnit(el: Element): Element {
  let cur: Element | null = el;
  while (cur) {
    if (cur.getAttribute && cur.getAttribute('data-edit-id')) return cur;
    cur = cur.parentElement;
  }
  return el;
}

export function findElementByKey(doc: Document, key: string): Element | null {
  if (!key) return null;
  if (key.startsWith('@')) {
    const id = key.slice(1);
    // CSS attribute selector の値はエスケープが必要
    try {
      return doc.querySelector(`[data-edit-id="${cssEscape(id)}"]`);
    } catch {
      return null;
    }
  }
  // DOM パス
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

function cssEscape(s: string): string {
  // 英数字とハイフン・アンダースコア以外をエスケープ
  return s.replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${c}`);
}

/**
 * 要素または祖先に data-edit-id があるか判定。
 * 「新方式で管理されている要素か」のチェックに使う。
 */
function hasEditIdAncestor(el: Element): boolean {
  let cur: Element | null = el;
  while (cur) {
    if (cur.getAttribute && cur.getAttribute('data-edit-id')) return true;
    cur = cur.parentElement;
  }
  return false;
}

/**
 * 1 行の override を要素に適用する。
 * - attrs.model_v2 があれば v2 モデルとして処理（推奨）
 * - 無ければ legacy（v1）として normalizeToModel で v2 化してから適用
 *
 * `data-dan-editing="1"` の要素には text/innerHTML を上書きしない（編集中保護）。
 */
function applyEntry(
  el: Element,
  styles: Record<string, string> | undefined,
  attrs: Record<string, unknown> | undefined
): void {
  const isEditing = el.getAttribute('data-dan-editing') === '1';

  // v2: model_v2 を最優先
  if (attrs && typeof attrs['model_v2'] === 'string') {
    try {
      const model = JSON.parse(attrs['model_v2'] as string) as EditModel;
      // styles は blockStyle にマージ（過去 row との整合）
      if (styles) {
        for (const [k, v] of Object.entries(styles)) {
          if (typeof v === 'string') model.blockStyle[k] = v;
        }
      }
      if (isEditing) {
        // 編集中はテキスト書き戻しをしない、blockStyle / extraAttrs だけ適用
        const safeModel: EditModel = { ...model, text: null, spans: [] };
        applyModelToElement(el as HTMLElement, safeModel);
      } else {
        applyModelToElement(el as HTMLElement, model);
      }
      return;
    } catch {
      // パース失敗 → legacy フォールバック
    }
  }

  // v1: 旧 attrs を v2 にノーマライズして適用
  const model = normalizeToModel({ styles: styles || {}, attrs: attrs || {} }) || emptyModel();
  if (isEditing) {
    applyModelToElement(el as HTMLElement, { ...model, text: null, spans: [] });
  } else {
    applyModelToElement(el as HTMLElement, model);
  }
  // 旧 v1 の単純属性 (href 等) は extraAttrs にも入れているが、念のため raw attrs も適用
  if (!isEditing && attrs) {
    for (const [name, val] of Object.entries(attrs)) {
      if (name === 'html' || name === 'text' || name === 'model_v2') continue;
      if (typeof val !== 'string') continue;
      try {
        el.setAttribute(name, val);
        if (name === 'src' && el.tagName === 'VIDEO') (el as HTMLVideoElement).load();
      } catch {
        /* ignore */
      }
    }
  }
}

type DanInspectorApi = {
  slug: string;
  computeKey: (el: Element) => string;
  resolveUnit: (el: Element) => Element;
  findByKey: (key: string) => Element | null;
  applyOverride: (key: string, styles: Record<string, string>, attrs: Record<string, unknown>) => void;
  reapplyAll: () => void;
  /** runtime キャッシュからキーの EditModel を取り出す（preview-store がモデル初期化に使う）。 */
  getModel: (key: string) => EditModel | null;
};

export function InspectorRuntime({ slug }: { slug: string }) {
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const doc = document;
    const cache: Record<string, OverrideEntry> = {};

    const applyAll = () => {
      // 適用順序:
      //   1) @<edit-id> を先に適用（新方式が真）
      //   2) legacy DOM パス key を後に適用、ただし
      //      解決先要素が data-edit-id を持つ祖先の中にある場合は **スキップ**
      //      （新方式で管理されている要素にレガシーが上書きするのを防ぐ。
      //       旧データが構造的に似た別ページの要素に漏れる「ページ間共有」バグの根本対策）
      const entries = Object.entries(cache);
      const editId = entries.filter(([k]) => k.startsWith('@'));
      const legacy = entries.filter(([k]) => !k.startsWith('@'));

      for (const [key, patch] of editId) {
        const el = findElementByKey(doc, key);
        if (el) applyEntry(el, patch.styles, patch.attrs);
      }
      for (const [key, patch] of legacy) {
        const el = findElementByKey(doc, key);
        if (!el) continue;
        // 解決先要素 or その祖先が data-edit-id を持つなら、その要素は新方式が
        // 管理対象 → レガシーは適用しない（汚染防止）
        if (hasEditIdAncestor(el)) continue;
        applyEntry(el, patch.styles, patch.attrs);
      }
    };

    const fetchAndApply = async () => {
      try {
        let res = await fetch(
          `/api/v1/inspector-overrides?slug=${encodeURIComponent(slug)}`,
          { credentials: 'include' }
        );
        if (!res.ok) {
          res = await fetch(
            `/api/v1/inspector-overrides/public?slug=${encodeURIComponent(slug)}`,
            { credentials: 'omit' }
          );
        }
        if (!res.ok) return;
        const rows = (await res.json()) as Array<{
          element_key: string;
          styles: Record<string, string> | null;
          attrs: Record<string, unknown> | null;
        }>;
        for (const r of rows) {
          cache[r.element_key] = {
            styles: r.styles || {},
            attrs: r.attrs || {},
          };
        }
        applyAll();
        // localStorage に同期（pre-paint 用）
        try {
          const lsKey = `dan-inspector-overrides-${slug}`;
          localStorage.setItem(
            lsKey,
            JSON.stringify(
              rows.map((r) => ({
                elementKey: r.element_key,
                styles: r.styles || {},
                attrs: r.attrs || {},
              }))
            )
          );
        } catch {
          /* ignore */
        }
      } catch (e) {
        console.warn('[InspectorRuntime] fetch failed', e);
      }
    };

    // 公開閲覧モード（iframe 外、トップレベル訪問）では DB を見に行かない。
    // JSX 自体が真実の状態なので fetch して上書きすると一瞬古い→新しいの flash が起きる。
    // 編集モード（dan UI の iframe 内）では従来通り DB を取りに行って live edit を反映する。
    const isInIframe = (() => {
      try {
        return window.top !== window.self;
      } catch {
        // cross-origin で window.top にアクセスできない場合は iframe とみなす
        return true;
      }
    })();
    if (isInIframe) {
      fetchAndApply();
    }

    const api: DanInspectorApi = {
      slug,
      computeKey: computeElementKey,
      resolveUnit: resolveEditUnit,
      findByKey: (key) => findElementByKey(doc, key),
      applyOverride: (key, styles, attrs) => {
        const el = findElementByKey(doc, key);
        if (el && (!key || key.startsWith('@') || !hasEditIdAncestor(el))) {
          applyEntry(el, styles, attrs);
        }
        cache[key] = {
          styles: { ...(cache[key]?.styles || {}), ...(styles || {}) },
          attrs: { ...(cache[key]?.attrs || {}), ...(attrs || {}) },
        };
      },
      reapplyAll: applyAll,
      getModel: (key) => {
        const entry = cache[key];
        if (!entry) return null;
        // v2 model 優先、無ければ legacy を v2 化して返す
        const attrs = entry.attrs || {};
        if (typeof attrs['model_v2'] === 'string') {
          try {
            const m = JSON.parse(attrs['model_v2'] as string) as EditModel;
            // styles を blockStyle にマージ（互換）
            if (entry.styles) {
              for (const [k, v] of Object.entries(entry.styles)) {
                if (typeof v === 'string') m.blockStyle[k] = v;
              }
            }
            return m;
          } catch {
            /* fall through */
          }
        }
        return normalizeToModel({ styles: entry.styles || {}, attrs }) || null;
      },
    };
    (window as unknown as Record<string, DanInspectorApi>)[WINDOW_KEY] = api;

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

