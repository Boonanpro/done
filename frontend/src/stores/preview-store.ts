'use client';

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { toast } from 'sonner';
import {
  emptyModel,
  applyBlockStyle,
  applyInlineStyle,
  applyText,
  type EditModel,
} from '@/lib/inspector-model';
import {
  applyModelToElement,
  selectionToTextRange,
} from '@/lib/inspector-render';
import { normalizeToModel } from '@/lib/inspector-migrate';

export interface SelectedElement {
  refId: string;
  tagName: string;
  text: string;
  outerHtmlSnippet: string;
  rect: { x: number; y: number; width: number; height: number };
  className?: string;
  ancestors?: string[];
  bgColor?: string;
  /** 編集単位の識別子（@<edit-id> または DOM パス）。 */
  elementKey?: string;
  stackHint?: { index: number; total: number };
}

export interface ArtifactRecord {
  id: string;
  project_id: string | null;
  message_id: string | null;
  slug: string;
  kind: string;
  label: string | null;
  preview_url: string;
  created_at: string;
}

export type InspectorMode = 'comment' | 'edit';

interface PreviewState {
  isOpen: boolean;
  projectId: string | null;
  artifact: ArtifactRecord | null;
  isEditMode: boolean;
  selectedElement: SelectedElement | null;
  popoverDraft: string;
  refCounter: number;

  inspectorMode: InspectorMode;
  liveTarget: Element | null;
  /** iframe 内で現在選択されているテキスト範囲。null = 選択なし or 折りたたみ */
  selectedRange: Range | null;
  /** elementKey → 現在のモデル（DOMより真）。新規操作時に DOM から構築。 */
  models: Record<string, EditModel>;
  /** 変更通知用バージョン。 */
  styleVersion: number;
}

interface PreviewActions {
  openArtifact: (projectId: string, artifact: ArtifactRecord) => void;
  closePreview: () => void;
  toggleEditMode: () => void;
  selectElement: (el: Omit<SelectedElement, 'refId'>, target?: Element | null) => void;
  clearSelection: () => void;
  setPopoverDraft: (v: string) => void;
  consumeDraft: () => { text: string; element: SelectedElement | null };

  setInspectorMode: (mode: InspectorMode) => void;
  setLiveStyle: (property: string, value: string, important?: boolean) => void;
  setLiveText: (text: string) => void;
  applyStyleTo: (target: Element | null, property: string, value: string, important?: boolean) => void;
  resetElementEdits: () => void;
}

type PreviewStore = PreviewState & PreviewActions;

const INITIAL: PreviewState = {
  isOpen: false,
  projectId: null,
  artifact: null,
  isEditMode: false,
  selectedElement: null,
  popoverDraft: '',
  refCounter: 0,
  inspectorMode: 'comment',
  liveTarget: null,
  selectedRange: null,
  models: {},
  styleVersion: 0,
};

/**
 * 要素から現在のモデルを取得 or 新規作成。
 * - store の models[key] にあればそれを返す
 * - 無ければ inspector-runtime のキャッシュ（サーバから取得した model_v2 を含む）を参照
 * - それも無ければ DOM から初期モデル（text=textContent, blockStyle なし）を作る
 *
 * これがないと、サーバ保存済みの spans/blockStyle が編集開始時に空モデルで上書きされ、
 * テキストだけ編集したのに色や大きさの装飾が全消えする事故が起きる。
 */
function getOrInitModel(
  key: string,
  el: Element,
  models: Record<string, EditModel>
): EditModel {
  const existing = models[key];
  if (existing) return existing;

  // runtime キャッシュ（サーバ取得済みの model）を優先
  if (typeof window !== 'undefined') {
    const win = window as unknown as Record<string, unknown>;
    const api = win['__DAN_INSPECTOR__'] as
      | { getModel: (k: string) => EditModel | null }
      | undefined;
    const fromRuntime = api?.getModel?.(key);
    if (fromRuntime) {
      // runtime は text 未設定（legacy で text 無し）の場合があるので、
      // DOM 内容で穴埋め
      if (fromRuntime.text === null) {
        fromRuntime.text = el.textContent;
      }
      return fromRuntime;
    }
  }

  // フォールバック: 完全新規モデル
  const m = emptyModel();
  m.text = el.textContent;
  return m;
}

export const usePreviewStore = create<PreviewStore>()(
  persist(
    (set, get) => ({
      ...INITIAL,

      openArtifact: (projectId, artifact) =>
        set({
          isOpen: true,
          projectId,
          artifact,
          isEditMode: false,
          selectedElement: null,
          popoverDraft: '',
          refCounter: 0,
          liveTarget: null,
          models: {},
          inspectorMode: 'comment',
        }),

      closePreview: () => set({ ...INITIAL }),

      toggleEditMode: () =>
        set((s) => ({
          isEditMode: !s.isEditMode,
          selectedElement: null,
          popoverDraft: '',
          liveTarget: null,
        })),

      selectElement: (el, target = null) => {
        const counter = get().refCounter + 1;
        const prev = get().liveTarget;
        // liveTarget が変わったら sticky な selectedRange をリセット
        // （別要素を選択したのに前要素の text range が残ると誤適用する）
        const rangeReset = prev !== target ? { selectedRange: null } : {};
        set({
          selectedElement: { ...el, refId: `e${counter}` },
          refCounter: counter,
          popoverDraft: '',
          liveTarget: target,
          ...rangeReset,
        });
      },

      clearSelection: () =>
        set({
          selectedElement: null,
          popoverDraft: '',
          liveTarget: null,
          selectedRange: null,
        }),

      setPopoverDraft: (v) => set({ popoverDraft: v }),

      consumeDraft: () => {
        const { popoverDraft, selectedElement } = get();
        set({ selectedElement: null, popoverDraft: '', liveTarget: null });
        return { text: popoverDraft, element: selectedElement };
      },

      setInspectorMode: (mode) => set({ inspectorMode: mode }),

      /**
       * 装飾を適用する。
       * - 部分テキスト選択中（selectedRange あり）→ inline span として model.spans に追記
       * - それ以外 → model.blockStyle に追記
       * モデルを更新したら DOM に反映 → 永続化キュー。
       */
      setLiveStyle: (property, value, important = false) => {
        const { liveTarget, selectedElement, selectedRange, models, styleVersion } = get();
        if (!liveTarget || !selectedElement?.elementKey) return;
        const key = selectedElement.elementKey;

        const current = getOrInitModel(key, liveTarget, models);
        let next: EditModel;

        const partialRange =
          selectedRange &&
          !selectedRange.collapsed &&
          liveTarget.contains(selectedRange.commonAncestorContainer)
            ? selectionToTextRange(liveTarget, selectedRange)
            : null;

        if (partialRange && current.text) {
          next = applyInlineStyle(current, partialRange.start, partialRange.end, property, value);
        } else {
          next = applyBlockStyle(current, property, value);
        }

        // DOM 反映
        try {
          applyModelToElement(liveTarget as HTMLElement, next);
          // 部分装飾後は span が再構築されるので、選択を「同じ start/end の範囲」に再設定しておく
          if (partialRange) {
            try {
              restoreTextRangeSelection(liveTarget, partialRange.start, partialRange.end, set);
            } catch {
              /* ignore */
            }
          }
        } catch {
          /* ignore */
        }

        set({
          models: { ...models, [key]: next },
          styleVersion: styleVersion + 1,
        });

        queueInspectorEdit({
          target: liveTarget,
          elementKey: key,
          model: next,
          // important hint は blockStyle の場合のみ意味がある
          important,
        });
      },

      /**
       * テキストを差し替える。spans の位置は自動補正される。
       *
       * 致命防御: liveTarget が wrapper（自身に data-edit-id が無く、配下に
       * data-edit-id 持ち子孫がある）の場合、テキスト保存しない。
       * （wrapper の textContent は子要素テキストの連結なので、保存して再描画すると
       *   子要素 h2/p ごと plaintext で上書きされ構造破壊に至る）
       */
      setLiveText: (text) => {
        const { liveTarget, selectedElement, models, styleVersion } = get();
        if (!liveTarget || !selectedElement?.elementKey) return;
        const key = selectedElement.elementKey;
        // wrapper チェック
        const el = liveTarget as HTMLElement;
        const isWrapper =
          !el.getAttribute?.('data-edit-id') &&
          !!el.querySelector?.('[data-edit-id]');
        if (isWrapper) {
          console.warn(
            '[preview-store] setLiveText blocked: liveTarget is a wrapper containing data-edit-id descendants.'
          );
          return;
        }

        const current = getOrInitModel(key, liveTarget, models);
        const next = applyText(current, text);

        try {
          applyModelToElement(liveTarget as HTMLElement, next);
        } catch {
          /* ignore */
        }

        set({
          models: { ...models, [key]: next },
          styleVersion: styleVersion + 1,
        });

        queueInspectorEdit({
          target: liveTarget,
          elementKey: key,
          model: next,
        });
      },

      /** 任意要素にスタイルだけ当てる（モデルなしの軽量版、img/video 用）。 */
      applyStyleTo: (target, property, value, important = false) => {
        if (!target) return;
        try {
          (target as HTMLElement).style.setProperty(
            property,
            value,
            important ? 'important' : ''
          );
        } catch {
          /* ignore */
        }
        set((s) => ({ styleVersion: s.styleVersion + 1 }));
        // モデルを使わずスタイルだけ送る（後で読み込まれた時は blockStyle 相当として扱われる）
        queueInspectorEdit({
          target,
          stylesOnly: { [property]: value },
        });
      },

      /** 選択中要素の編集をリセット（モデルを空に戻す）。 */
      resetElementEdits: () => {
        const { liveTarget, selectedElement, models, styleVersion } = get();
        if (!liveTarget || !selectedElement?.elementKey) return;
        const key = selectedElement.elementKey;
        const empty = emptyModel();
        try {
          // inline style をクリア
          const cur = models[key];
          if (cur) {
            for (const prop of Object.keys(cur.blockStyle)) {
              (liveTarget as HTMLElement).style.removeProperty(prop);
            }
            // text を JSX オリジナルに戻す手段がないので、現在の textContent を保つ
          }
        } catch {
          /* ignore */
        }
        const nextModels = { ...models };
        delete nextModels[key];
        set({ models: nextModels, styleVersion: styleVersion + 1 });
        queueInspectorEdit({
          target: liveTarget,
          elementKey: key,
          model: empty,
        });
      },
    }),
    {
      name: 'dan-preview-state',
      storage: createJSONStorage(() => (typeof window !== 'undefined' ? localStorage : undefined as unknown as Storage)),
      partialize: (s) => ({
        isOpen: s.isOpen,
        projectId: s.projectId,
        artifact: s.artifact,
        isEditMode: s.isEditMode,
        inspectorMode: s.inspectorMode,
      }),
    }
  )
);

/**
 * 部分テキスト適用後、DOM が再構築されているので Selection を文字位置で復元する。
 * iframe の Selection / Range API を使って start/end の文字位置に対応する text node を見つける。
 */
function restoreTextRangeSelection(
  el: Element,
  start: number,
  end: number,
  set: (partial: Partial<PreviewState>) => void
): void {
  const doc = el.ownerDocument;
  if (!doc) return;
  const win = doc.defaultView;
  if (!win) return;
  const range = doc.createRange();
  let acc = 0;
  let startSet = false;
  const walker = doc.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node: Node | null = walker.nextNode();
  while (node) {
    const len = node.textContent?.length ?? 0;
    if (!startSet && acc + len >= start) {
      range.setStart(node, start - acc);
      startSet = true;
    }
    if (acc + len >= end) {
      range.setEnd(node, end - acc);
      const sel = win.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
      set({ selectedRange: range.cloneRange() });
      return;
    }
    acc += len;
    node = walker.nextNode();
  }
}

/* ========== Runtime Overrides Layer ========== */

type LocalOverride = {
  elementKey: string;
  styles: Record<string, string>;
  attrs: Record<string, unknown>;
};

type PendingOverride = LocalOverride & {
  slug: string;
};

const pendingOverrides: Record<string, PendingOverride> = {};
let flushTimer: ReturnType<typeof setTimeout> | null = null;
const FLUSH_DEBOUNCE_MS = 100;

type QueueContext = {
  target: Element | null;
  elementKey?: string;
  /** 完全な編集モデル。これがあれば attrs.model_v2 として送信。 */
  model?: EditModel;
  /** モデルなしで style だけ送る場合（applyStyleTo 用）。 */
  stylesOnly?: Record<string, string>;
  /** モデルなしで attrs（src/href/alt 等）だけ送る場合（image/video 用）。 */
  attrsOnly?: Record<string, string>;
  /** important フラグ（blockStyle 全体に適用したいケース用、現状未使用）。 */
  important?: boolean;
};

export function queueInspectorEdit(ctx: QueueContext) {
  if (!ctx.target && !ctx.elementKey) return;
  const doc = ctx.target?.ownerDocument;
  const win = doc?.defaultView as unknown as Record<string, unknown> | undefined;
  type DanApi = {
    computeKey: (el: Element) => string;
    applyOverride: (k: string, s: Record<string, string>, a: Record<string, unknown>) => void;
    slug: string;
  };
  const danApi = win?.__DAN_INSPECTOR__ as DanApi | undefined;
  const key =
    ctx.elementKey ||
    (danApi && ctx.target ? danApi.computeKey(ctx.target) : '');
  if (!key) return;

  const urlSlug = danApi?.slug || usePreviewStore.getState().artifact?.slug || '';
  if (!urlSlug) {
    console.warn('[inspector-overrides] no slug derivable, drop edit', key);
    return;
  }

  let attrs: Record<string, unknown> = {};
  let styles: Record<string, string> = {};

  if (ctx.model) {
    attrs = { model_v2: JSON.stringify(ctx.model) };
    // blockStyle は styles 列にも入れると、データベースのインデックス /
    // 旧フェッチコードからも見えるので二重保存。
    styles = { ...ctx.model.blockStyle };
  } else if (ctx.stylesOnly) {
    styles = { ...ctx.stylesOnly };
  } else if (ctx.attrsOnly) {
    attrs = { ...ctx.attrsOnly };
  }

  if (danApi) {
    danApi.applyOverride(key, styles, attrs);
  }

  const existing = pendingOverrides[key];
  pendingOverrides[key] = {
    elementKey: key,
    // model 送信時は attrs を「全置換」する（v1 の html / text を残さない）
    styles: ctx.model ? styles : { ...(existing?.styles || {}), ...styles },
    attrs: ctx.model ? attrs : { ...(existing?.attrs || {}), ...attrs },
    slug: urlSlug,
  };
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(flushPendingOverrides, FLUSH_DEBOUNCE_MS);
}

export function flushInspectorEdits(): Promise<void> {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  return flushPendingOverrides();
}

const LS_KEY = (slug: string) => `dan-inspector-overrides-${slug}`;

function upsertLocalStorage(slug: string, entry: LocalOverride): void {
  if (typeof window === 'undefined') return;
  try {
    const raw = window.localStorage.getItem(LS_KEY(slug));
    const rows = raw ? (JSON.parse(raw) as LocalOverride[]) : [];
    const idx = rows.findIndex((r) => r.elementKey === entry.elementKey);
    const merged: LocalOverride = idx >= 0
      ? {
          elementKey: entry.elementKey,
          // v2 model_v2 が来ていれば attrs を全置換
          styles: 'model_v2' in entry.attrs ? entry.styles : { ...(rows[idx].styles || {}), ...entry.styles },
          attrs: 'model_v2' in entry.attrs ? entry.attrs : { ...(rows[idx].attrs || {}), ...entry.attrs },
        }
      : { ...entry };
    if (idx >= 0) rows[idx] = merged;
    else rows.push(merged);
    window.localStorage.setItem(LS_KEY(slug), JSON.stringify(rows));
  } catch {
    /* ignore */
  }
}

export function syncLocalStorageFromServer(
  slug: string,
  rows: Array<{ element_key: string; styles: Record<string, string>; attrs: Record<string, unknown> }>
) {
  if (typeof window === 'undefined') return;
  try {
    const entries: LocalOverride[] = rows.map((r) => ({
      elementKey: r.element_key,
      styles: r.styles || {},
      attrs: r.attrs || {},
    }));
    window.localStorage.setItem(LS_KEY(slug), JSON.stringify(entries));
  } catch {
    /* ignore */
  }
}

async function flushPendingOverrides(): Promise<void> {
  const entries = Object.entries(pendingOverrides);
  if (!entries.length) return;
  for (const key of entries.map(([k]) => k)) delete pendingOverrides[key];

  const state = usePreviewStore.getState();
  const projectId = state.projectId || undefined;

  for (const [, edit] of entries) {
    upsertLocalStorage(edit.slug, edit);
  }

  let failures = 0;
  let lastError: { status?: number; text?: string } | null = null;
  for (const [, edit] of entries) {
    try {
      const res = await fetch('/api/v1/inspector-overrides', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          artifact_slug: edit.slug,
          element_key: edit.elementKey,
          styles: Object.keys(edit.styles).length ? edit.styles : null,
          attrs: Object.keys(edit.attrs).length ? edit.attrs : null,
          project_id: projectId,
          // v2 モデル送信時は attrs を全置換するよう、明示フラグを送る
          replace_attrs: 'model_v2' in (edit.attrs as Record<string, unknown>),
        }),
      });
      if (!res.ok) {
        failures++;
        lastError = { status: res.status, text: await res.text() };
        console.warn('[inspector-overrides] upsert failed', res.status, lastError.text);
      }
    } catch (err) {
      failures++;
      lastError = { text: String(err) };
      console.warn('[inspector-overrides] upsert exception', err);
    }
  }

  if (failures > 0) {
    const msg = lastError?.status === 401 || lastError?.status === 403
      ? '編集の保存に失敗しました（ログインが切れています）'
      : `編集の保存に失敗しました（${failures}件）`;
    try {
      toast.error(msg, { description: lastError?.text?.slice(0, 200) });
    } catch { /* ignore */ }
  }
}

/** 互換 API: 旧コードで使われている可能性があるので残す。 */
export function findMediaInScope(target: Element | null, tag: 'img' | 'video'): HTMLElement | null {
  if (!target) return null;
  const upper = tag.toUpperCase();
  if (target.tagName === upper) return target as HTMLElement;
  return (target.querySelector?.(tag) as HTMLElement | null) ?? null;
}

/** 互換: 旧コードが import している場合のため、normalizeToModel を再エクスポート。 */
export { normalizeToModel };
