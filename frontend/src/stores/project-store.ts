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
  warmupMode: 'thinking' | 'switching' | null;
}

interface ProjectStore {
  selectedProjectId: string | null;
  selectProject: (id: string | null) => void;
  recoveryStates: Record<string, ProjectRecoveryState>;
  setInterrupted: (projectId: string, isInterrupted: boolean) => void;
  setWarmupMode: (
    projectId: string,
    warmupMode: ProjectRecoveryState['warmupMode']
  ) => void;
  resetRecovery: (projectId: string) => void;
}

const DEFAULT_RECOVERY_STATE: ProjectRecoveryState = {
  isInterrupted: false,
  warmupMode: null,
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
          [projectId]: { ...current, isInterrupted },
        },
      };
    });
  },

  setWarmupMode: (projectId, warmupMode) => {
    set((state) => {
      const current = state.recoveryStates[projectId] || DEFAULT_RECOVERY_STATE;
      if (current.warmupMode === warmupMode) return state;
      return {
        recoveryStates: {
          ...state.recoveryStates,
          [projectId]: { ...current, warmupMode },
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
      warmupMode: s.recoveryStates[projectId]?.warmupMode ?? null,
    }))
  );
}

export function useRecoveryActions() {
  return useProjectStore(
    useShallow((s: ProjectStore) => ({
      setInterrupted: s.setInterrupted,
      setWarmupMode: s.setWarmupMode,
      resetRecovery: s.resetRecovery,
    }))
  );
}
