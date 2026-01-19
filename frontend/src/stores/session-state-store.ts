/**
 * Session State Store - セッションごとの状態を管理
 *
 * プロセスモニター、提案パネル、送信状態などをセッションIDごとに分離
 */

import { create } from 'zustand';
import type { ProcessStep, StateMachineResponse } from '@/lib/api-client';

// 単一セッションの状態
export interface SessionState {
  // プロセスモニター
  processes: Map<string, {
    steps: ProcessStep[];
    isCollapsed: boolean;
    isProcessing: boolean;
  }>;
  // 提案パネル
  pendingConfirmation: StateMachineResponse | null;
  // 送信中フラグ
  isSending: boolean;
  // 修正入力
  revisionInput: string;
  showRevisionInput: boolean;
  // 未読カウント
  unreadCount: number;
}

// デフォルトのセッション状態
const createDefaultSessionState = (): SessionState => ({
  processes: new Map(),
  pendingConfirmation: null,
  isSending: false,
  revisionInput: '',
  showRevisionInput: false,
  unreadCount: 0,
});

// ストア全体の型
interface SessionStateStore {
  // セッションIDごとの状態
  sessions: Map<string, SessionState>;

  // 現在アクティブなセッションID
  activeSessionId: string | null;

  // アクティブなセッションIDを設定
  setActiveSessionId: (sessionId: string | null) => void;

  // セッションの状態を取得（なければ作成）
  getSessionState: (sessionId: string) => SessionState;

  // プロセス関連
  setProcess: (sessionId: string, processId: string, process: {
    steps: ProcessStep[];
    isCollapsed: boolean;
    isProcessing: boolean;
  }) => void;
  deleteProcess: (sessionId: string, processId: string) => void;
  toggleProcessCollapse: (sessionId: string, processId: string) => void;
  addProcessStep: (sessionId: string, processId: string, step: ProcessStep) => void;

  // 提案パネル
  setPendingConfirmation: (sessionId: string, confirmation: StateMachineResponse | null) => void;

  // 送信状態
  setIsSending: (sessionId: string, isSending: boolean) => void;

  // 修正入力
  setRevisionInput: (sessionId: string, input: string) => void;
  setShowRevisionInput: (sessionId: string, show: boolean) => void;

  // セッション状態をクリア
  clearSessionState: (sessionId: string) => void;

  // DBから読み込んだプロセスを初期化
  initializeProcessesFromMessages: (sessionId: string, messages: Array<{
    id: string;
    sender_type: string;
    ai_context?: { reasoning_steps?: string[] };
  }>) => void;

  // 未読管理
  incrementUnread: (sessionId: string) => void;
  markAsRead: (sessionId: string) => void;
  getUnreadCount: (sessionId: string) => number;
}

// ペンディングプロセスID
export const PENDING_PROCESS_ID = '__pending__';

export const useSessionStateStore = create<SessionStateStore>((set, get) => ({
  sessions: new Map(),
  activeSessionId: null,

  setActiveSessionId: (sessionId) => {
    set({ activeSessionId: sessionId });
  },

  getSessionState: (sessionId) => {
    const { sessions } = get();
    let state = sessions.get(sessionId);
    if (!state) {
      state = createDefaultSessionState();
      const newSessions = new Map(sessions);
      newSessions.set(sessionId, state);
      set({ sessions: newSessions });
    }
    return state;
  },

  setProcess: (sessionId, processId, process) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId) || createDefaultSessionState();
      const newProcesses = new Map(sessionState.processes);
      newProcesses.set(processId, process);
      sessions.set(sessionId, { ...sessionState, processes: newProcesses });
      return { sessions };
    });
  },

  deleteProcess: (sessionId, processId) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId);
      if (!sessionState) return state;

      const newProcesses = new Map(sessionState.processes);
      newProcesses.delete(processId);
      sessions.set(sessionId, { ...sessionState, processes: newProcesses });
      return { sessions };
    });
  },

  toggleProcessCollapse: (sessionId, processId) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId);
      if (!sessionState) return state;

      const process = sessionState.processes.get(processId);
      if (!process) return state;

      const newProcesses = new Map(sessionState.processes);
      newProcesses.set(processId, { ...process, isCollapsed: !process.isCollapsed });
      sessions.set(sessionId, { ...sessionState, processes: newProcesses });
      return { sessions };
    });
  },

  addProcessStep: (sessionId, processId, step) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId) || createDefaultSessionState();
      const process = sessionState.processes.get(processId) || {
        steps: [],
        isCollapsed: false,
        isProcessing: true,
      };

      // 既存のステップをIDで検索
      const existingIndex = process.steps.findIndex(s => s.id === step.id);
      let updatedSteps: ProcessStep[];

      if (existingIndex >= 0) {
        updatedSteps = [...process.steps];
        updatedSteps[existingIndex] = step;
      } else {
        updatedSteps = [...process.steps, step];
      }

      const newProcesses = new Map(sessionState.processes);
      newProcesses.set(processId, { ...process, steps: updatedSteps });
      sessions.set(sessionId, { ...sessionState, processes: newProcesses });
      return { sessions };
    });
  },

  setPendingConfirmation: (sessionId, confirmation) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId) || createDefaultSessionState();
      sessions.set(sessionId, { ...sessionState, pendingConfirmation: confirmation });
      return { sessions };
    });
  },

  setIsSending: (sessionId, isSending) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId) || createDefaultSessionState();
      sessions.set(sessionId, { ...sessionState, isSending });
      return { sessions };
    });
  },

  setRevisionInput: (sessionId, input) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId) || createDefaultSessionState();
      sessions.set(sessionId, { ...sessionState, revisionInput: input });
      return { sessions };
    });
  },

  setShowRevisionInput: (sessionId, show) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId) || createDefaultSessionState();
      sessions.set(sessionId, { ...sessionState, showRevisionInput: show });
      return { sessions };
    });
  },

  clearSessionState: (sessionId) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      sessions.set(sessionId, createDefaultSessionState());
      return { sessions };
    });
  },

  initializeProcessesFromMessages: (sessionId, messages) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId) || createDefaultSessionState();
      const newProcesses = new Map(sessionState.processes);

      for (const msg of messages) {
        if (msg.sender_type === 'ai' && msg.ai_context?.reasoning_steps?.length) {
          // 既にprocessesに存在しない場合のみ追加
          if (!newProcesses.has(msg.id)) {
            newProcesses.set(msg.id, {
              steps: msg.ai_context.reasoning_steps.map((step, idx) => ({
                id: `step-${idx}`,
                label: step,
                status: 'completed' as const,
              })),
              isCollapsed: true,
              isProcessing: false,
            });
          }
        }
      }

      sessions.set(sessionId, { ...sessionState, processes: newProcesses });
      return { sessions };
    });
  },

  incrementUnread: (sessionId) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId) || createDefaultSessionState();
      sessions.set(sessionId, { ...sessionState, unreadCount: sessionState.unreadCount + 1 });
      return { sessions };
    });
  },

  markAsRead: (sessionId) => {
    set((state) => {
      const sessions = new Map(state.sessions);
      const sessionState = sessions.get(sessionId);
      if (!sessionState || sessionState.unreadCount === 0) return state;
      sessions.set(sessionId, { ...sessionState, unreadCount: 0 });
      return { sessions };
    });
  },

  getUnreadCount: (sessionId) => {
    const { sessions } = get();
    const sessionState = sessions.get(sessionId);
    return sessionState?.unreadCount || 0;
  },
}));
