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

/** 選択要素自身 or その子孫に img/video があれば返す。
 *  先祖は辿らない（選択してない要素まで拾うと混乱するため、↑ボタンで親に遡らせる）*/
export function findMediaInScope(target: Element | null, tag: 'img' | 'video'): HTMLElement | null {
  if (!target) return null;
  const upper = tag.toUpperCase();
  if (target.tagName === upper) return target as HTMLElement;
  return (target.querySelector?.(tag) as HTMLElement | null) ?? null;
}
