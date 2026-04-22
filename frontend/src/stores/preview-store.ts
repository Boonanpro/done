'use client';

import { create } from 'zustand';

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

  // Stage C additions
  inspectorMode: InspectorMode;
  liveTarget: Element | null;
  edits: Record<string, StyleEdit>;
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
  setLiveStyle: (property: string, value: string) => void;
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
};

export const usePreviewStore = create<PreviewStore>((set, get) => ({
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

  setInspectorMode: (mode) =>
    set({ inspectorMode: mode, selectedElement: null, liveTarget: null, popoverDraft: '' }),

  setLiveStyle: (property, value) => {
    const { liveTarget, selectedElement, edits } = get();
    if (!liveTarget || !selectedElement) return;
    try {
      (liveTarget as HTMLElement).style.setProperty(property, value);
    } catch {
      /* ignore */
    }
    const key = selectedElement.refId;
    set({
      edits: {
        ...edits,
        [key]: { ...(edits[key] || {}), [property]: value },
      },
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
}));
