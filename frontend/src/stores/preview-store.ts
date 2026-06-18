'use client';

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { toast } from 'sonner';
import {
  emptyModel,
  applyBlockStyle,
  applyInlineStyle,
  applyText,
  readModelFromAttrs,
  type EditModel,
} from '@/lib/inspector-model';
import { useEditHistoryStore, makeEditSummary } from '@/stores/edit-history-store';
import { sendToIframe } from '@/components/preview/inspector-bridge';
import type { SelectionSnapshot, MediaInfo, OverrideRow } from '@/lib/inspector-protocol';

/**
 * クロスオリジン Inspector ストア。
 *
 * 設計: docs/proposals/inspector_cross_origin.md
 *
 * 旧版は live DOM(`liveTarget: Element`) と live `Range` を保持して直接DOMを編集していた
 * （同一オリジン限定）。新版は DOM を一切持たず、iframe から来た **snapshot**（選択情報）と
 * **文字オフセット**（選択範囲）だけを扱い、編集は inspector-bridge 経由で iframe へ
 * postMessage する。保存は従来の API（認証付き）に親が代行する。
 */

export interface SelectedElement {
  refId: string;
  tagName: string;
  text: string;
  outerHtmlSnippet: string;
  rect: { x: number; y: number; width: number; height: number };
  className?: string;
  ancestors?: { tagName: string; className: string; elementKey: string | null }[];
  bgColor?: string | null;
  /** 編集単位の識別子（@<edit-id> または DOM パス）。 */
  elementKey?: string;
  /** iframe が計算した computedStyle の抜粋（パネルはこれを読む。live DOM は読まない）。 */
  computedStyles?: Record<string, string>;
  /** インラインテキスト編集できる葉要素か。 */
  isTextLeaf?: boolean;
  /** img/video の場合の情報。 */
  media?: MediaInfo;
}

export interface ArtifactRecord {
  id: string;
  room_id: string;
  project_id: string | null;
  message_id: string | null;
  slug: string;
  kind: string;
  artifact_type: 'website' | 'dashboard' | 'tool' | string;
  label: string | null;
  preview_url: string;
  share_url?: string | null;
  draft_url?: string | null;
  production_url?: string | null;
  custom_domain?: string | null;
  publish_status?: string | null;
  last_publish_error?: string | null;
  delivery_status?: string | null;
  delivery_mode?: string | null;
  target_audience?: string | null;
  requires_auth?: boolean | null;
  payment_responsibility?: string | null;
  delivery_checklist?: Record<string, unknown> | null;
  handoff_notes?: string | null;
  created_at: string;
  updated_at?: string;
  published_at?: string | null;
}

export type InspectorMode = 'comment' | 'edit';

/** 文字オフセットで表した選択範囲（live Range の代替）。 */
export interface SelectionRange {
  elementKey: string;
  start: number;
  end: number;
}

interface PreviewState {
  isOpen: boolean;
  projectId: string | null;
  artifact: ArtifactRecord | null;
  isEditMode: boolean;
  selectedElement: SelectedElement | null;
  popoverDraft: string;
  refCounter: number;

  inspectorMode: InspectorMode;
  /** iframe が実際に表示している成果物 slug（agent が URL から検出して ready で報告）。
   *  保存/取得はこの slug を優先する。chat_artifact レコードの slug が中身とズレていても
   *  （例: ラベル kittoku-v2 だが中身は kittoku）、編集が正しい場所に保存され公開も通る。 */
  iframeSlug: string | null;
  /** iframe 内で現在選択されているテキスト範囲（文字オフセット）。null=なし。 */
  selectedRange: SelectionRange | null;
  /** elementKey → 現在のモデル（DOMより真）。fetch した override や編集で更新。 */
  models: Record<string, EditModel>;
  styleVersion: number;
  /** JSXファイル書き戻し成功時に+1。preview-pane が iframe src の ?t= に反映し再ロード。 */
  contentVersion: number;
}

interface PreviewActions {
  openArtifact: (projectId: string, artifact: ArtifactRecord) => void;
  closePreview: () => void;
  toggleEditMode: () => void;
  /** iframe からの選択 snapshot を受けて選択状態を更新する。 */
  selectFromSnapshot: (snap: SelectionSnapshot) => void;
  clearSelection: () => void;
  setPopoverDraft: (v: string) => void;
  consumeDraft: () => { text: string; element: SelectedElement | null };

  setInspectorMode: (mode: InspectorMode) => void;
  /** agent が ready で報告した「iframe実表示slug」を記録する。 */
  setIframeSlug: (slug: string | null) => void;
  /** iframe からの選択範囲（文字オフセット）を受ける。null payload で解除。 */
  setSelectionRange: (payload: SelectionRange | null) => void;
  /** スタイルを適用（選択範囲ありなら部分span、なければblock）。iframeへ送信＋永続化。 */
  setLiveStyle: (property: string, value: string, important?: boolean) => void;
  /** インラインテキスト確定（iframe agent からの commit を受ける）。 */
  commitText: (elementKey: string, text: string) => void;
  /** 任意要素にスタイルだけ当てる（img/video 用）。elementKey 指定。 */
  applyStyleTo: (elementKey: string | undefined, property: string, value: string, important?: boolean) => void;
  /** 属性(src/alt/href等)を当てる（img/video 用）。 */
  applyAttrs: (elementKey: string | undefined, attrs: Record<string, string>) => void;
  resetElementEdits: () => void;
  deleteSelectedElement: (opts?: { elementKey?: string; tagName?: string }) => Promise<boolean>;
  /** fetch した override 行で models キャッシュを種付けする。 */
  seedModels: (rows: OverrideRow[]) => void;
  bumpContentVersion: () => void;
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
  iframeSlug: null,
  selectedRange: null,
  models: {},
  styleVersion: 0,
  contentVersion: 0,
};

/** キャッシュ or 空モデル（text を seed）から現在モデルを得る。DOM には触れない。 */
function getOrInitModel(key: string, text: string, models: Record<string, EditModel>): EditModel {
  const existing = models[key];
  if (existing) return existing;
  const m = emptyModel();
  m.text = text;
  return m;
}

export const usePreviewStore = create<PreviewStore>()(
  persist(
    (set, get) => ({
      ...INITIAL,

      openArtifact: (projectId, artifact) => {
        useEditHistoryStore.getState().clear();
        set({
          isOpen: true,
          projectId,
          artifact,
          isEditMode: false,
          selectedElement: null,
          popoverDraft: '',
          refCounter: 0,
          models: {},
          selectedRange: null,
          iframeSlug: null,
          inspectorMode: 'comment',
        });
      },

      closePreview: () => {
        useEditHistoryStore.getState().clear();
        set({ ...INITIAL });
      },

      toggleEditMode: () =>
        set((s) => ({
          isEditMode: !s.isEditMode,
          selectedElement: null,
          popoverDraft: '',
          selectedRange: null,
        })),

      selectFromSnapshot: (snap) => {
        const counter = get().refCounter + 1;
        const prevKey = get().selectedElement?.elementKey;
        const rangeReset = prevKey !== snap.elementKey ? { selectedRange: null } : {};
        set({
          selectedElement: {
            refId: `e${counter}`,
            tagName: snap.tagName,
            text: snap.text,
            outerHtmlSnippet: snap.outerHtmlSnippet,
            rect: snap.rect,
            className: snap.className,
            ancestors: snap.ancestors,
            bgColor: snap.bgColor,
            elementKey: snap.elementKey,
            computedStyles: snap.computedStyles,
            isTextLeaf: snap.isTextLeaf,
            media: snap.media,
          },
          refCounter: counter,
          popoverDraft: '',
          // 選択の瞬間に iframe 実表示slugを確定（保存/取得をこれに固定）。
          iframeSlug: snap.slug || get().iframeSlug,
          ...rangeReset,
        });
      },

      clearSelection: () => {
        set({ selectedElement: null, popoverDraft: '', selectedRange: null });
        sendToIframe({ type: 'inspector:clear-selection', payload: {} });
      },

      setPopoverDraft: (v) => set({ popoverDraft: v }),

      consumeDraft: () => {
        const { popoverDraft, selectedElement } = get();
        set({ selectedElement: null, popoverDraft: '', selectedRange: null });
        return { text: popoverDraft, element: selectedElement };
      },

      setInspectorMode: (mode) => set({ inspectorMode: mode }),

      setIframeSlug: (slug) => set({ iframeSlug: slug }),

      setSelectionRange: (payload) => {
        if (!payload || (payload.end <= payload.start)) {
          // 折りたたみ/空は前の選択を保持（sticky）— null 明示時のみクリア
          if (payload === null) set({ selectedRange: null });
          return;
        }
        set({ selectedRange: payload });
      },

      setLiveStyle: (property, value) => {
        const { selectedElement, selectedRange, models, styleVersion, artifact } = get();
        const key = selectedElement?.elementKey;
        if (!key) return;
        const slug = get().iframeSlug || artifact?.slug || '';
        const current = getOrInitModel(key, selectedElement?.text || '', models);
        const partial =
          selectedRange && selectedRange.elementKey === key && selectedRange.end > selectedRange.start && current.text
            ? selectedRange
            : null;
        const next = partial
          ? applyInlineStyle(current, partial.start, partial.end, property, value)
          : applyBlockStyle(current, property, value);
        // 初回編集なら「編集前の状態」を捕捉（Resetで戻すため）。block編集時は
        // そのプロパティの元の computed 値を一度だけ記録する。
        if (!next.orig) next.orig = { text: selectedElement?.text ?? null, blockStyle: {} };
        if (!partial && next.orig.blockStyle[property] === undefined) {
          const camel = property.replace(/-([a-z])/g, (_m, c) => c.toUpperCase());
          const origVal = selectedElement?.computedStyles?.[camel];
          if (typeof origVal === 'string') next.orig.blockStyle[property] = origVal;
        }
        set({ models: { ...models, [key]: next }, styleVersion: styleVersion + 1 });
        sendToIframe({ type: 'inspector:apply', payload: { elementKey: key, model: next } });
        queueInspectorEdit({
          slug,
          elementKey: key,
          model: next,
          historyMeta: {
            summary: makeEditSummary({ kind: 'style', prop: property, value, elementHint: selectedElement?.tagName }),
          },
        });
      },

      commitText: (elementKey, text) => {
        const { models, styleVersion, artifact, selectedElement } = get();
        const slug = get().iframeSlug || artifact?.slug || '';
        const current = getOrInitModel(elementKey, text, models);
        const next = applyText(current, text);
        // 初回編集なら「編集前テキスト」を捕捉（Resetで戻すため）。selectedElement.text は
        // 選択時スナップショット=このタイプ前の状態。一度捕捉したら上書きしない。
        if (!next.orig) next.orig = { text: selectedElement?.text ?? null, blockStyle: {} };
        set({ models: { ...models, [elementKey]: next }, styleVersion: styleVersion + 1 });
        sendToIframe({ type: 'inspector:apply', payload: { elementKey, model: next } });
        queueInspectorEdit({
          slug,
          elementKey,
          model: next,
          historyMeta: { summary: makeEditSummary({ kind: 'text', elementHint: selectedElement?.tagName }) },
        });
      },

      applyStyleTo: (elementKey, property, value) => {
        if (!elementKey) return;
        const { models, styleVersion, artifact } = get();
        const slug = get().iframeSlug || artifact?.slug || '';
        const current = getOrInitModel(elementKey, '', models);
        const next = applyBlockStyle(current, property, value);
        set({ models: { ...models, [elementKey]: next }, styleVersion: styleVersion + 1 });
        sendToIframe({ type: 'inspector:apply', payload: { elementKey, model: next } });
        queueInspectorEdit({
          slug,
          elementKey,
          model: next,
          historyMeta: { summary: makeEditSummary({ kind: 'style', prop: property, value, elementHint: 'media' }) },
        });
      },

      applyAttrs: (elementKey, attrs) => {
        if (!elementKey) return;
        const { artifact, styleVersion } = get();
        const slug = get().iframeSlug || artifact?.slug || '';
        set({ styleVersion: styleVersion + 1 });
        sendToIframe({ type: 'inspector:apply', payload: { elementKey, attrs } });
        queueInspectorEdit({
          slug,
          elementKey,
          attrsOnly: attrs,
          historyMeta: { summary: makeEditSummary({ kind: 'style', prop: 'attr', value: '', elementHint: 'media' }) },
        });
      },

      deleteSelectedElement: async (opts) => {
        const { selectedElement, artifact, models, styleVersion } = get();
        const key = opts?.elementKey || selectedElement?.elementKey;
        if (!key) {
          toast.error('削除対象が選択されていません');
          return false;
        }
        if (!key.startsWith('@')) {
          toast.error('この要素には data-edit-id が無いので削除できません');
          return false;
        }
        const slug = get().iframeSlug || artifact?.slug || '';
        if (!slug) {
          toast.error('artifact slug が取得できません');
          return false;
        }
        // 楽観的に iframe で非表示化（display:none）。
        sendToIframe({ type: 'inspector:apply', payload: { elementKey: key, styles: { display: 'none' } } });
        const nextModels = { ...models };
        delete nextModels[key];
        set({ models: nextModels, styleVersion: styleVersion + 1, selectedElement: null });
        removeLocalStorageOverride(slug, key);

        const tagHint = opts?.tagName || selectedElement?.tagName;
        try {
          const res = await fetch('/api/v1/inspector-overrides/delete-element', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ artifact_slug: slug, element_key: key }),
          });
          if (!res.ok) {
            const txt = await res.text();
            toast.error('要素の削除に失敗しました', { description: txt.slice(0, 200) });
            return false;
          }
          try {
            const body = (await res.json()) as {
              removed?: boolean; file?: string | null; before_content?: string | null; after_content?: string | null;
            };
            if (body.removed && body.file && typeof body.before_content === 'string' && typeof body.after_content === 'string') {
              useEditHistoryStore.getState().push({
                slug, filePath: body.file, before: body.before_content, after: body.after_content,
                elementKey: key, summary: makeEditSummary({ kind: 'delete', elementHint: tagHint }),
              });
            }
          } catch (e) {
            console.warn('[deleteSelectedElement] history record failed', e);
          }
          toast.success('要素を削除しました（Cmd+Z で復元）');
          return true;
        } catch (err) {
          toast.error('要素削除のリクエストに失敗', { description: String(err).slice(0, 200) });
          return false;
        }
      },

      resetElementEdits: () => {
        const { selectedElement, models, styleVersion, artifact } = get();
        const key = selectedElement?.elementKey;
        if (!key) return;
        const slug = get().iframeSlug || artifact?.slug || '';
        const orig = models[key]?.orig;

        if (orig && slug) {
          // 編集前へ戻す: 初回編集時に捕捉した元の状態を再適用する。queueInspectorEdit が
          // 保存→自動公開を回すので、ライブプレビューも本番(〜1〜2分)も元へ戻る。
          const origModel: EditModel = {
            v: 2, text: orig.text, blockStyle: { ...orig.blockStyle }, spans: [], attrs: {}, orig,
          };
          set({ models: { ...models, [key]: origModel }, styleVersion: styleVersion + 1 });
          sendToIframe({ type: 'inspector:apply', payload: { elementKey: key, model: origModel } });
          queueInspectorEdit({
            slug, elementKey: key, model: origModel,
            historyMeta: { summary: makeEditSummary({ kind: 'style', prop: 'reset', value: '', elementHint: selectedElement?.tagName }) },
          });
          try { toast.success('編集前に戻しました', { description: '本番にも〜1〜2分で反映されます' }); } catch { /* ignore */ }
          return;
        }

        // orig が無い(古いデータ等): override を削除（少なくともプレビュー上の上書きは消える）。
        const nextModels = { ...models };
        delete nextModels[key];
        set({ models: nextModels, styleVersion: styleVersion + 1 });
        if (!slug) return;
        removeLocalStorageOverride(slug, key);
        void deleteInspectorOverride(slug, key)
          .catch((err) => {
            console.warn('[inspector-overrides] delete failed', err);
            try { toast.error('編集のリセットに失敗しました', { description: String(err).slice(0, 200) }); } catch { /* ignore */ }
          })
          .finally(() => {
            usePreviewStore.getState().bumpContentVersion();
          });
      },

      seedModels: (rows) => {
        const models = { ...get().models };
        for (const r of rows) {
          const attrs = (r.attrs as Record<string, unknown>) || {};
          let m: EditModel | null = null;
          // 保存形式は attrs.model_v2 = JSON文字列(model全体, orig含む)。まずそれを優先。
          if (typeof attrs['model_v2'] === 'string') {
            try { m = JSON.parse(attrs['model_v2'] as string) as EditModel; } catch { m = null; }
          }
          if (!m) m = readModelFromAttrs(attrs); // v2直書き(古い形式)フォールバック
          if (m) {
            if (r.styles) for (const [k, v] of Object.entries(r.styles)) if (typeof v === 'string') m.blockStyle[k] = v;
            models[r.element_key] = m;
          }
        }
        set({ models });
      },

      bumpContentVersion: () => set((s) => ({ contentVersion: s.contentVersion + 1 })),
    }),
    {
      name: 'dan-preview-state',
      version: 2,
      storage: createJSONStorage(() => (typeof window !== 'undefined' ? localStorage : undefined as unknown as Storage)),
      partialize: (s) => ({ isEditMode: s.isEditMode, inspectorMode: s.inspectorMode }),
      migrate: (_persisted, version) => {
        if (version < 2) return { isEditMode: false, inspectorMode: 'comment' as const };
        return _persisted as { isEditMode: boolean; inspectorMode: 'comment' | 'edit' };
      },
    }
  )
);

/* ========== Runtime Overrides Layer（永続化） ========== */

type LocalOverride = { elementKey: string; styles: Record<string, string>; attrs: Record<string, unknown> };
type PendingOverride = LocalOverride & { slug: string; _historyMeta?: { summary: string } };

const pendingOverrides: Record<string, PendingOverride> = {};
let flushTimer: ReturnType<typeof setTimeout> | null = null;
const FLUSH_DEBOUNCE_MS = 100;

// 自動公開: 編集が一段落したら（最後の保存から数秒後）、ボタン操作なしで
// 「JSX焼き込み→done-artifacts公開」を裏で走らせる。公開URL/クライアントには
// Vercel再ビルド分（〜1〜2分）遅れて反映される。ユーザーの「公開を押さずとも
// 自動反映」思想に合わせた実装。
let autoPublishTimer: ReturnType<typeof setTimeout> | null = null;
const AUTO_PUBLISH_DEBOUNCE_MS = 8000;
let autoPublishNoticeShown = false;

function scheduleAutoPublish(slug: string): void {
  if (!slug) return;
  if (autoPublishTimer) clearTimeout(autoPublishTimer);
  autoPublishTimer = setTimeout(async () => {
    autoPublishTimer = null;
    try {
      const res = await fetch(`/api/v1/inspector-overrides/publish?slug=${encodeURIComponent(slug)}`, {
        method: 'POST',
        credentials: 'include',
      });
      if (res.ok && !autoPublishNoticeShown) {
        autoPublishNoticeShown = true;
        try {
          toast.success('編集を本番に反映中…', {
            description: '公開URL/クライアントには1〜2分で自動反映されます（操作不要）',
          });
        } catch { /* ignore */ }
      }
    } catch (e) {
      console.warn('[inspector-overrides] auto-publish failed', e);
    }
  }, AUTO_PUBLISH_DEBOUNCE_MS);
}

type QueueContext = {
  slug: string;
  elementKey: string;
  model?: EditModel;
  stylesOnly?: Record<string, string>;
  attrsOnly?: Record<string, string>;
  historyMeta?: { summary: string };
};

export function queueInspectorEdit(ctx: QueueContext) {
  const key = ctx.elementKey;
  const slug = ctx.slug || usePreviewStore.getState().artifact?.slug || '';
  if (!key || !slug) {
    console.warn('[inspector-overrides] missing key/slug, drop edit', key, slug);
    return;
  }
  let attrs: Record<string, unknown> = {};
  let styles: Record<string, string> = {};
  if (ctx.model) {
    attrs = { model_v2: JSON.stringify(ctx.model) };
    styles = { ...ctx.model.blockStyle };
  } else if (ctx.stylesOnly) {
    styles = { ...ctx.stylesOnly };
  } else if (ctx.attrsOnly) {
    attrs = { ...ctx.attrsOnly };
  }
  const existing = pendingOverrides[key];
  pendingOverrides[key] = {
    elementKey: key,
    styles: ctx.model ? styles : { ...(existing?.styles || {}), ...styles },
    attrs: ctx.model ? attrs : { ...(existing?.attrs || {}), ...attrs },
    slug,
    _historyMeta: ctx.historyMeta,
  };
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(flushPendingOverrides, FLUSH_DEBOUNCE_MS);
}

export function flushInspectorEdits(): Promise<void> {
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  return flushPendingOverrides();
}

const LS_KEY = (slug: string) => `dan-inspector-overrides-${slug}`;

function removeLocalStorageOverride(slug: string, elementKey: string): void {
  if (typeof window === 'undefined') return;
  try {
    const raw = window.localStorage.getItem(LS_KEY(slug));
    const rows = raw ? (JSON.parse(raw) as LocalOverride[]) : [];
    const next = rows.filter((r) => r.elementKey !== elementKey);
    if (next.length) window.localStorage.setItem(LS_KEY(slug), JSON.stringify(next));
    else window.localStorage.removeItem(LS_KEY(slug));
  } catch { /* ignore */ }
}

async function deleteInspectorOverride(slug: string, elementKey: string): Promise<void> {
  const params = new URLSearchParams({ slug, element_key: elementKey });
  const res = await fetch(`/api/v1/inspector-overrides?${params.toString()}`, { method: 'DELETE', credentials: 'include' });
  if (!res.ok && res.status !== 404) throw new Error(await res.text());
}

function upsertLocalStorage(slug: string, entry: LocalOverride): void {
  if (typeof window === 'undefined') return;
  try {
    const raw = window.localStorage.getItem(LS_KEY(slug));
    const rows = raw ? (JSON.parse(raw) as LocalOverride[]) : [];
    const idx = rows.findIndex((r) => r.elementKey === entry.elementKey);
    const merged: LocalOverride = idx >= 0
      ? {
          elementKey: entry.elementKey,
          styles: 'model_v2' in entry.attrs ? entry.styles : { ...(rows[idx].styles || {}), ...entry.styles },
          attrs: 'model_v2' in entry.attrs ? entry.attrs : { ...(rows[idx].attrs || {}), ...entry.attrs },
        }
      : { ...entry };
    if (idx >= 0) rows[idx] = merged; else rows.push(merged);
    window.localStorage.setItem(LS_KEY(slug), JSON.stringify(rows));
  } catch { /* ignore */ }
}

export function syncLocalStorageFromServer(
  slug: string,
  rows: Array<{ element_key: string; styles: Record<string, string>; attrs: Record<string, unknown> }>
) {
  if (typeof window === 'undefined') return;
  try {
    const entries: LocalOverride[] = rows.map((r) => ({ elementKey: r.element_key, styles: r.styles || {}, attrs: r.attrs || {} }));
    window.localStorage.setItem(LS_KEY(slug), JSON.stringify(entries));
  } catch { /* ignore */ }
}

async function flushPendingOverrides(): Promise<void> {
  const entries = Object.entries(pendingOverrides);
  if (!entries.length) return;
  for (const key of entries.map(([k]) => k)) delete pendingOverrides[key];

  const state = usePreviewStore.getState();
  const projectId = state.projectId || undefined;

  for (const [, edit] of entries) upsertLocalStorage(edit.slug, edit);

  let failures = 0;
  let lastError: { status?: number; text?: string } | null = null;
  for (const [, edit] of entries) {
    try {
      // DB(inspector_overrides)に upsert する。クロスオリジンの iframe は done-artifacts
      // 公開版を読むため、JSX 直書き(/direct-write)では反映されない。DB に入れておけば
      // 親がナビゲーション/再読込のたびに取得して iframe へ apply-overrides で再適用できる。
      // 公開(canonical)への焼き込みは別途 writeback(DB→JSX)→publish で行う。
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
    try { toast.error(msg, { description: lastError?.text?.slice(0, 200) }); } catch { /* ignore */ }
  }

  // 1件でも保存できたら自動公開をスケジュール（ボタン不要で本番反映）。
  if (entries.length - failures > 0) {
    const slug = entries.map(([, e]) => e.slug).find(Boolean);
    if (slug) scheduleAutoPublish(slug);
  }
}

/** 互換 API（旧コード用）。 */
export function findMediaInScope(target: Element | null, tag: 'img' | 'video'): HTMLElement | null {
  if (!target) return null;
  const upper = tag.toUpperCase();
  if (target.tagName === upper) return target as HTMLElement;
  return (target.querySelector?.(tag) as HTMLElement | null) ?? null;
}

export { normalizeToModel } from '@/lib/inspector-migrate';
