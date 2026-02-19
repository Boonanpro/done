'use client';

/**
 * useSessionRecovery - セッション復帰フック
 *
 * 役割: バックエンドで処理が進行中かを検知し、プロセスモニターを復元する。
 *
 * メッセージの再取得はReact Queryの refetchOnWindowFocus に任せる。
 * このフックはプロセスモニター復帰と完了検知のみを担当する。
 */

import { useEffect, useRef, useCallback } from 'react';
import { api } from '@/lib/api-client';
import { useSessionStateStore, PENDING_PROCESS_ID } from '@/stores/session-state-store';

interface UseSessionRecoveryOptions {
  sessionId: string | null;
}

export function useSessionRecovery({
  sessionId,
}: UseSessionRecoveryOptions) {
  const isActiveRef = useRef(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastSeqRef = useRef<number>(0);
  const isPollingRef = useRef(false);

  const { addProcessStep, setProcess, setIsSending, deleteProcess } =
    useSessionStateStore();

  /**
   * バックエンドの実行状態を確認し、処理中ならプロセスモニター復元 + ポーリング開始。
   */
  const checkActive = useCallback(async () => {
    if (!sessionId) return;

    try {
      const status = await api.sm.getActiveStatus(sessionId);
      isActiveRef.current = status.active;

      if (status.active) {
        setIsSending(sessionId, true);

        // current_only=true でバックエンド側で最後のdone以降のみ取得
        const events = await api.sm.getSessionEvents(sessionId, undefined, true);

        const activeEvents = events.filter((e) => e.event_type !== 'done');
        if (activeEvents.length > 0) {
          setProcess(sessionId, PENDING_PROCESS_ID, {
            steps: activeEvents.map((e, idx) => ({
              id: `recovery-${idx}`,
              label: e.tool_label || e.content || e.event_type,
              status: 'completed' as const,
            })),
            isCollapsed: false,
            isProcessing: true,
          });
        }

        // seqは取得イベントの最後尾を使う（差分ポーリング用）
        if (events.length > 0) {
          const maxSeq = Math.max(...events.map((e) => e.seq || 0));
          lastSeqRef.current = maxSeq;
        }

        startPolling();
      }
    } catch (err) {
      console.warn('[SessionRecovery] Failed to check active status:', err);
    }
  }, [sessionId, setIsSending, setProcess]);

  /**
   * ポーリング: 進行中プロセスの差分イベントを取得
   */
  const pollEvents = useCallback(async () => {
    if (!sessionId || isPollingRef.current) return;
    isPollingRef.current = true;

    try {
      const events = await api.sm.getSessionEvents(
        sessionId,
        lastSeqRef.current || undefined,
      );

      if (events.length > 0) {
        for (const event of events) {
          if (event.event_type === 'done') {
            isActiveRef.current = false;
            stopPolling();
            setIsSending(sessionId, false);
            deleteProcess(sessionId, PENDING_PROCESS_ID);
            return;
          }

          addProcessStep(sessionId, PENDING_PROCESS_ID, {
            id: `poll-${event.seq || event.id}`,
            label: event.tool_label || event.content || event.event_type,
            status: 'running',
          });
        }

        const maxSeq = Math.max(...events.map((e) => e.seq || 0));
        if (maxSeq > lastSeqRef.current) {
          lastSeqRef.current = maxSeq;
        }
      }

      // イベントがなくても完了チェック
      if (events.length === 0) {
        try {
          const status = await api.sm.getActiveStatus(sessionId);
          if (!status.active) {
            isActiveRef.current = false;
            stopPolling();
            setIsSending(sessionId, false);
            deleteProcess(sessionId, PENDING_PROCESS_ID);
          }
        } catch {
          // ignore
        }
      }
    } catch (err) {
      console.warn('[SessionRecovery] Poll error:', err);
    } finally {
      isPollingRef.current = false;
    }
  }, [sessionId, addProcessStep, setIsSending, deleteProcess]);

  const startPolling = useCallback(() => {
    if (pollingRef.current) return;
    pollingRef.current = setInterval(pollEvents, 1000);
  }, [pollEvents]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const checkActiveRef = useRef(checkActive);
  checkActiveRef.current = checkActive;

  // タブ復帰時: プロセスモニター復元チェック
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        checkActiveRef.current();
      } else {
        stopPolling();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [stopPolling]);

  // 初回マウント & sessionId変更時
  useEffect(() => {
    lastSeqRef.current = 0;
    isActiveRef.current = false;
    stopPolling();
    checkActiveRef.current();
    return () => { stopPolling(); };
  }, [sessionId, stopPolling]);
}
