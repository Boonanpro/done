/**
 * Project Store - プロジェクト選択状態 + プロセスモニター状態を管理
 *
 * プロセスモニター状態をここに保持することで、ページ遷移しても消えない。
 */

import { create } from 'zustand';
import { useShallow } from 'zustand/react/shallow';

export interface ProjectLiveStep {
  label: string;
  type: 'tool' | 'reasoning' | 'error';
}

interface ProjectProcessState {
  isProcessing: boolean;
  isSending: boolean;
  liveSteps: ProjectLiveStep[];
}

interface ProjectStore {
  selectedProjectId: string | null;
  selectProject: (id: string | null) => void;

  // プロセスモニター（projectId ごと）
  processStates: Record<string, ProjectProcessState>;
  getProcessState: (projectId: string) => ProjectProcessState;
  setProcessing: (projectId: string, isProcessing: boolean) => void;
  setSending: (projectId: string, isSending: boolean) => void;
  addLiveStep: (projectId: string, step: ProjectLiveStep) => void;
  clearLiveSteps: (projectId: string) => void;
  resetProcess: (projectId: string) => void;
}

const DEFAULT_PROCESS_STATE: ProjectProcessState = {
  isProcessing: false,
  isSending: false,
  liveSteps: [],
};

export const useProjectStore = create<ProjectStore>((set, get) => ({
  selectedProjectId: null,
  selectProject: (id) => set({ selectedProjectId: id }),

  processStates: {},

  getProcessState: (projectId: string): ProjectProcessState => {
    return get().processStates[projectId] || DEFAULT_PROCESS_STATE;
  },

  setProcessing: (projectId, isProcessing) => {
    set((state) => {
      const current = state.processStates[projectId] || DEFAULT_PROCESS_STATE;
      if (current.isProcessing === isProcessing) return state;
      return {
        processStates: {
          ...state.processStates,
          [projectId]: { ...current, isProcessing },
        },
      };
    });
  },

  setSending: (projectId, isSending) => {
    set((state) => {
      const current = state.processStates[projectId] || DEFAULT_PROCESS_STATE;
      if (current.isSending === isSending) return state;
      return {
        processStates: {
          ...state.processStates,
          [projectId]: { ...current, isSending },
        },
      };
    });
  },

  addLiveStep: (projectId, step) => {
    set((state) => {
      const current = state.processStates[projectId] || DEFAULT_PROCESS_STATE;
      return {
        processStates: {
          ...state.processStates,
          [projectId]: {
            ...current,
            liveSteps: [...current.liveSteps, step],
          },
        },
      };
    });
  },

  clearLiveSteps: (projectId) => {
    set((state) => {
      const current = state.processStates[projectId] || DEFAULT_PROCESS_STATE;
      if (current.liveSteps.length === 0) return state;
      return {
        processStates: {
          ...state.processStates,
          [projectId]: { ...current, liveSteps: [] },
        },
      };
    });
  },

  resetProcess: (projectId) => {
    set((state) => ({
      processStates: {
        ...state.processStates,
        [projectId]: DEFAULT_PROCESS_STATE,
      },
    }));
  },
}));

/**
 * プロセス状態を個別プロパティとして取得するフック
 * 各プロパティが変わったときだけ再描画される
 */
export function useProcessState(projectId: string) {
  return useProjectStore(
    useShallow((s: ProjectStore) => {
      const ps = s.processStates[projectId] || DEFAULT_PROCESS_STATE;
      return {
        isProcessing: ps.isProcessing,
        isSending: ps.isSending,
        liveSteps: ps.liveSteps,
      };
    })
  );
}

/**
 * プロセス操作メソッドだけを取得するフック（安定参照）
 */
export function useProcessActions() {
  return useProjectStore(
    useShallow((s: ProjectStore) => ({
      setProcessing: s.setProcessing,
      setSending: s.setSending,
      addLiveStep: s.addLiveStep,
      clearLiveSteps: s.clearLiveSteps,
      resetProcess: s.resetProcess,
    }))
  );
}
