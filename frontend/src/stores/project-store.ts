/**
 * Project Store - プロジェクト選択状態を管理
 */

import { create } from 'zustand';

interface ProjectStore {
  selectedProjectId: string | null;
  selectProject: (id: string | null) => void;
}

export const useProjectStore = create<ProjectStore>((set) => ({
  selectedProjectId: null,
  selectProject: (id) => set({ selectedProjectId: id }),
}));
