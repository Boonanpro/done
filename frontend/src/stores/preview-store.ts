'use client';

import { create } from 'zustand';

export interface SelectedElement {
  refId: string;
  tagName: string;
  text: string;
  outerHtmlSnippet: string;
  rect: { x: number; y: number; width: number; height: number };
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

interface PreviewState {
  isOpen: boolean;
  projectId: string | null;
  artifact: ArtifactRecord | null;
  isEditMode: boolean;
  selectedElement: SelectedElement | null;
  popoverDraft: string;
  refCounter: number;
}

interface PreviewActions {
  openArtifact: (projectId: string, artifact: ArtifactRecord) => void;
  closePreview: () => void;
  toggleEditMode: () => void;
  selectElement: (el: Omit<SelectedElement, 'refId'>) => void;
  clearSelection: () => void;
  setPopoverDraft: (v: string) => void;
  consumeDraft: () => { text: string; element: SelectedElement | null };
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
    }),

  closePreview: () => set({ ...INITIAL }),

  toggleEditMode: () =>
    set((s) => ({
      isEditMode: !s.isEditMode,
      selectedElement: null,
      popoverDraft: '',
    })),

  selectElement: (el) => {
    const counter = get().refCounter + 1;
    set({
      selectedElement: { ...el, refId: `e${counter}` },
      refCounter: counter,
      popoverDraft: '',
    });
  },

  clearSelection: () => set({ selectedElement: null, popoverDraft: '' }),

  setPopoverDraft: (v) => set({ popoverDraft: v }),

  consumeDraft: () => {
    const { popoverDraft, selectedElement } = get();
    set({ selectedElement: null, popoverDraft: '' });
    return { text: popoverDraft, element: selectedElement };
  },
}));
