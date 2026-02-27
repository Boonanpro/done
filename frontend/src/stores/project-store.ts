/**
 * Project Store
 *
 * Keeps project selection plus minimal transient recovery state.
 * Execution activity itself is derived from the session-active query.
 */

import { create } from 'zustand';
import { useShallow } from 'zustand/react/shallow';

interface ProjectRecoveryState {
  isInterrupted: boolean;
}

interface ProjectStore {
  selectedProjectId: string | null;
  selectProject: (id: string | null) => void;
  recoveryStates: Record<string, ProjectRecoveryState>;
  setInterrupted: (projectId: string, isInterrupted: boolean) => void;
  resetRecovery: (projectId: string) => void;
}

const DEFAULT_RECOVERY_STATE: ProjectRecoveryState = {
  isInterrupted: false,
};

export const useProjectStore = create<ProjectStore>((set) => ({
  selectedProjectId: null,
  selectProject: (id) => set({ selectedProjectId: id }),
  recoveryStates: {},

  setInterrupted: (projectId, isInterrupted) => {
    set((state) => {
      const current = state.recoveryStates[projectId] || DEFAULT_RECOVERY_STATE;
      if (current.isInterrupted === isInterrupted) return state;
      return {
        recoveryStates: {
          ...state.recoveryStates,
          [projectId]: { isInterrupted },
        },
      };
    });
  },

  resetRecovery: (projectId) => {
    set((state) => ({
      recoveryStates: {
        ...state.recoveryStates,
        [projectId]: DEFAULT_RECOVERY_STATE,
      },
    }));
  },
}));

export function useRecoveryState(projectId: string) {
  return useProjectStore(
    useShallow((s: ProjectStore) => ({
      isInterrupted: s.recoveryStates[projectId]?.isInterrupted ?? false,
    }))
  );
}

export function useRecoveryActions() {
  return useProjectStore(
    useShallow((s: ProjectStore) => ({
      setInterrupted: s.setInterrupted,
      resetRecovery: s.resetRecovery,
    }))
  );
}
