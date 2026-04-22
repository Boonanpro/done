'use client';

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export interface SelectedElement {
  refId: string;
  tagName: string;
  text: string;
  outerHtmlSnippet: string;
  rect: { x: number; y: number; width: number; height: number };
  className?: string;
  ancestors?: string[];
  bgColor?: string;
  // DOM ツリー上のパスキー（InspectorRuntime が使う形式）
  elementKey?: string;
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

type StyleEdit = Record<string, string>;

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
  edits: Record<string, StyleEdit>;
  /** style 変更のバージョン。変更の度にインクリメントされ、
   *  subscribe した全コンポーネントに再描画のトリガを与える */
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
  edits: {},
  styleVersion: 0,
};

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
          edits: {},
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
        set({
          selectedElement: { ...el, refId: `e${counter}` },
          refCounter: counter,
          popoverDraft: '',
          liveTarget: target,
        });
      },

      clearSelection: () =>
        set({ selectedElement: null, popoverDraft: '', liveTarget: null }),

      setPopoverDraft: (v) => set({ popoverDraft: v }),

      consumeDraft: () => {
        const { popoverDraft, selectedElement } = get();
        set({ selectedElement: null, popoverDraft: '', liveTarget: null });
        return { text: popoverDraft, element: selectedElement };
      },

      // モード切替時に選択は残す（ユーザーが同じ要素を続けて編集できるように）
      setInspectorMode: (mode) => set({ inspectorMode: mode }),

      setLiveStyle: (property, value, important = false) => {
        const { liveTarget, selectedElement, edits, styleVersion } = get();
        if (!liveTarget || !selectedElement) return;
        try {
          (liveTarget as HTMLElement).style.setProperty(
            property,
            value,
            important ? 'important' : ''
          );
        } catch {
          /* ignore */
        }
        const key = selectedElement.refId;
        set({
          edits: {
            ...edits,
            [key]: { ...(edits[key] || {}), [property]: value },
          },
          styleVersion: styleVersion + 1,
        });
        queueInspectorEdit({
          target: liveTarget,
          elementKey: selectedElement.elementKey,
          patch: { styles: { [property]: value } },
        });
      },

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
        queueInspectorEdit({
          target,
          patch: { styles: { [property]: value } },
        });
      },

      resetElementEdits: () => {
        const { liveTarget, selectedElement, edits } = get();
        if (!liveTarget || !selectedElement) return;
        const key = selectedElement.refId;
        const e = edits[key] || {};
        for (const prop of Object.keys(e)) {
          try {
            (liveTarget as HTMLElement).style.removeProperty(prop);
          } catch {
            /* ignore */
          }
        }
        const nextEdits = { ...edits };
        delete nextEdits[key];
        set({ edits: nextEdits });
      },
    }),
    {
      name: 'dan-preview-state',
      storage: createJSONStorage(() => (typeof window !== 'undefined' ? localStorage : undefined as unknown as Storage)),
      // DOM 参照や一時的な編集状態は永続化しない
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

/* ========== Runtime Overrides Layer ==========
 * 編集内容は iframe 内 DOM に即時反映しつつ、バックエンドの inspector_overrides
 * 表に保存する。iframe の <InspectorRuntime /> が初回マウントと DOM 更新時に
 * 自動で再適用する。
 *
 * JSX ファイルは触らないので HMR rebuild が走らない = iframe が勝手にリロード
 * しない = 編集中の状態が維持される。*/

type PendingOverride = {
  elementKey: string;
  styles: Record<string, string>;
  attrs: Record<string, string>;
};

const pendingOverrides: Record<string, PendingOverride> = {};
let flushTimer: ReturnType<typeof setTimeout> | null = null;
const FLUSH_DEBOUNCE_MS = 100; // HMR を誘発しないので短めでよい

type QueueContext = {
  target: Element | null;
  elementKey?: string;
  patch: { styles?: Record<string, string>; attrs?: Record<string, string> };
};

export function queueInspectorEdit(ctx: QueueContext) {
  if (!ctx.target && !ctx.elementKey) return;
  const doc = ctx.target?.ownerDocument;
  const win = doc?.defaultView as unknown as Record<string, unknown> | undefined;
  // elementKey は ctx 優先、無ければ iframe の computeKey から取る
  const danApi = win?.__DAN_INSPECTOR__ as
    | { computeKey: (el: Element) => string; applyOverride: (k: string, s: Record<string, string>, a: Record<string, string>) => void; slug: string }
    | undefined;
  const key =
    ctx.elementKey ||
    (danApi && ctx.target ? danApi.computeKey(ctx.target) : '');
  if (!key) return;

  // iframe 側のキャッシュも同期（MutationObserver 再描画でも消えないように）
  if (danApi) {
    danApi.applyOverride(key, ctx.patch.styles || {}, ctx.patch.attrs || {});
  }

  const existing = pendingOverrides[key];
  pendingOverrides[key] = {
    elementKey: key,
    styles: { ...(existing?.styles || {}), ...(ctx.patch.styles || {}) },
    attrs: { ...(existing?.attrs || {}), ...(ctx.patch.attrs || {}) },
  };
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(flushPendingOverrides, FLUSH_DEBOUNCE_MS);
}

/** 明示的に即時フラッシュ（iframe リロード前など） */
export function flushInspectorEdits(): Promise<void> {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  return flushPendingOverrides();
}

const LS_KEY = (slug: string) => `dan-inspector-overrides-${slug}`;

/** localStorage 上の overrides を更新（pre-paint blocking script が読む） */
function upsertLocalStorage(
  slug: string,
  entry: PendingOverride
): void {
  if (typeof window === 'undefined') return;
  try {
    const raw = window.localStorage.getItem(LS_KEY(slug));
    const rows = raw ? (JSON.parse(raw) as PendingOverride[]) : [];
    const idx = rows.findIndex((r) => r.elementKey === entry.elementKey);
    const merged: PendingOverride = idx >= 0
      ? {
          elementKey: entry.elementKey,
          styles: { ...(rows[idx].styles || {}), ...entry.styles },
          attrs: { ...(rows[idx].attrs || {}), ...entry.attrs },
        }
      : entry;
    if (idx >= 0) rows[idx] = merged;
    else rows.push(merged);
    window.localStorage.setItem(LS_KEY(slug), JSON.stringify(rows));
  } catch {
    /* ignore */
  }
}

/** バックエンドから取得した overrides 全量で localStorage を上書き同期 */
export function syncLocalStorageFromServer(
  slug: string,
  rows: Array<{ element_key: string; styles: Record<string, string>; attrs: Record<string, string> }>
) {
  if (typeof window === 'undefined') return;
  try {
    const entries: PendingOverride[] = rows.map((r) => ({
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
  const slug = state.artifact?.slug;
  if (!slug) return;
  const projectId = state.projectId || undefined;

  // localStorage には即時反映（次回リフレッシュでの flash 対策）
  for (const [, edit] of entries) {
    upsertLocalStorage(slug, edit);
  }

  for (const [, edit] of entries) {
    try {
      const res = await fetch('/api/v1/inspector-overrides', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          artifact_slug: slug,
          element_key: edit.elementKey,
          styles: Object.keys(edit.styles).length ? edit.styles : null,
          attrs: Object.keys(edit.attrs).length ? edit.attrs : null,
          project_id: projectId,
        }),
      });
      if (!res.ok) {
        console.warn('[inspector-overrides] upsert failed', res.status, await res.text());
      }
    } catch (err) {
      console.warn('[inspector-overrides] upsert exception', err);
    }
  }
}

/** 選択要素自身 or その子孫に img/video があれば返す。
 *  先祖は辿らない（選択してない要素まで拾うと混乱するため、↑ボタンで親に遡らせる）*/
export function findMediaInScope(target: Element | null, tag: 'img' | 'video'): HTMLElement | null {
  if (!target) return null;
  const upper = tag.toUpperCase();
  if (target.tagName === upper) return target as HTMLElement;
  return (target.querySelector?.(tag) as HTMLElement | null) ?? null;
}
