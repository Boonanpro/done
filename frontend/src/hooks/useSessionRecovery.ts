'use client';

/**
 * useSessionRecovery - セッション復帰・再接続フック
 *
 * ページ読み込み時やタブ復帰時に：
 * 1. バックエンドがまだ処理中かチェック (active session API)
 * 2. 処理中なら execution_events をポーリングしてプロセスモニタを復元
 * 3. 完了を検知したらポーリング停止 + メッセージ再取得
 * 4. 既に完了済みでも、ページ復帰時にメッセージを再取得（SSE切断で逃した回答を取得）
 *
 * これにより、タブを閉じてもブラウザを切り替えても
 * 戻ってきた時に「接続中...」→ 進捗表示が復元される。
 * または既に完了済みなら最終回答がすぐ表示される。
 */

import { useEffect, useRef, useCallback } from 'react';
import { api, type ExecutionEvent } from '@/lib/api-client';
import { useSessionStateStore, PENDING_PROCESS_ID } from '@/stores/session-state-store';

interface UseSessionRecoveryOptions {
  sessionId: string | null;
  /** メッセージ一覧を再取得する関数 */
  refetchMessages: () => void;
}

interface UseSessionRecoveryReturn {
  /** バックエンドが実行中か */
  isBackendActive: boolean;
}

export function useSessionRecovery({
  sessionId,
  refetchMessages,
}: UseSessionRecoveryOptions): UseSessionRecoveryReturn {
  const isActiveRef = useRef(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastSeqRef = useRef<number>(0);
  const isPollingRef = useRef(false);

  const { addProcessStep, setProcess, setIsSending, deleteProcess } =
    useSessionStateStore();

  /**
   * アクティブセッションをチェックし、必要ならポーリング開始
   * active: false の場合でもメッセージを再取得（SSE切断で逃した回答を拾う）
   */
  const checkAndRecover = useCallback(async () => {
    if (!sessionId) return;

    try {
      const status = await api.sm.getActiveStatus(sessionId);
      isActiveRef.current = status.active;

      if (status.active) {
        // バックエンドが処理中 → isSending=true にしてUIを「実行中」状態に
        setIsSending(sessionId, true);

        // 既存のexecution_eventsを取得してプロセスモニタ復元
        const events = await api.sm.getSessionEvents(sessionId);
        if (events.length > 0) {
          // プロセスモニタにステップを復元
          setProcess(sessionId, PENDING_PROCESS_ID, {
            steps: events
              .filter((e) => e.event_type !== 'done')
              .map((e, idx) => ({
                id: `recovery-${idx}`,
                label: e.tool_label || e.content || e.event_type,
                status: 'completed' as const,
              })),
            isCollapsed: false,
            isProcessing: true,
          });

          // 最後のseqを記録
          const maxSeq = Math.max(...events.map((e) => e.seq || 0));
          lastSeqRef.current = maxSeq;
        }

        // ポーリング開始
        startPolling();
      } else {
        // ★ バックエンドが非アクティブでも、メッセージを再取得する
        // SSE切断中にバックエンドが回答を保存・完了した場合、
        // フロントエンドはその回答を受け取れていないので、ここで拾う
        refetchMessages();
      }
    } catch (err) {
      console.warn('[SessionRecovery] Failed to check active status:', err);
    }
  }, [sessionId, setIsSending, setProcess, refetchMessages]);

  /**
   * ポーリング: since_seq で差分取得
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
            // 完了検知 → ポーリング停止 + 状態リセット
            isActiveRef.current = false;
            stopPolling();
            setIsSending(sessionId, false);
            deleteProcess(sessionId, PENDING_PROCESS_ID);
            // メッセージ再取得（最終回答をDBから取得）
            refetchMessages();
            return;
          }

          // プロセスステップを追加
          addProcessStep(sessionId, PENDING_PROCESS_ID, {
            id: `poll-${event.seq || event.id}`,
            label: event.tool_label || event.content || event.event_type,
            status: 'running',
          });
        }

        // 最後のseqを更新
        const maxSeq = Math.max(...events.map((e) => e.seq || 0));
        if (maxSeq > lastSeqRef.current) {
          lastSeqRef.current = maxSeq;
        }
      }

      // アクティブ状態を再確認（イベントがなくても完了チェック）
      if (events.length === 0) {
        try {
          const status = await api.sm.getActiveStatus(sessionId);
          if (!status.active) {
            isActiveRef.current = false;
            stopPolling();
            setIsSending(sessionId, false);
            deleteProcess(sessionId, PENDING_PROCESS_ID);
            refetchMessages();
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
  }, [sessionId, addProcessStep, setIsSending, deleteProcess, refetchMessages]);

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

  /**
   * visibilitychange: タブ復帰時に即座にチェック
   */
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        // タブが再びアクティブになった → 即座にチェック + メッセージ再取得
        checkAndRecover();
      } else {
        // タブが非アクティブ → ポーリング停止（バッテリー節約）
        stopPolling();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [checkAndRecover, stopPolling]);

  /**
   * 初回マウント時: アクティブセッションチェック
   */
  useEffect(() => {
    checkAndRecover();
    return () => {
      stopPolling();
    };
  }, [sessionId, checkAndRecover, stopPolling]);

  /**
   * sessionId変更時にリセット
   */
  useEffect(() => {
    lastSeqRef.current = 0;
    isActiveRef.current = false;
    stopPolling();
  }, [sessionId, stopPolling]);

  return {
    isBackendActive: isActiveRef.current,
  };
}
