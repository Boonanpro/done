'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { api, type ActiveSessionStatus } from '@/lib/api-client';
import { useProjectStore } from '@/stores/project-store';

interface UseProjectRecoveryOptions {
  projectId: string;
  roomId: string;
}

function buildActiveStatus(sessionId: string, active: boolean): ActiveSessionStatus {
  return {
    active,
    session_id: sessionId,
    started_at: active ? Date.now() : null,
  };
}

export function useProjectRecovery({ projectId, roomId }: UseProjectRecoveryOptions) {
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isPollingRef = useRef(false);
  const queryClient = useQueryClient();

  const setInterrupted = useProjectStore((s) => s.setInterrupted);
  const isInterrupted = useProjectStore(
    (s) => s.recoveryStates[projectId]?.isInterrupted ?? false
  );

  const syncActiveStatus = useCallback(
    (active: boolean) => {
      queryClient.setQueryData(['session-active', roomId], buildActiveStatus(roomId, active));
    },
    [queryClient, roomId]
  );

  const invalidateRecoveryQueries = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['session-active', roomId] });
    // project-messages は refetch で即座に再取得（SSE断線で見逃したメッセージを確実に表示）
    queryClient.refetchQueries({ queryKey: ['project-messages', roomId] });
    queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
    queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project-proposals', projectId] });
  }, [projectId, queryClient, roomId]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const checkAndRecover = useCallback(async () => {
    if (!roomId) return;

    try {
      const status = await api.sm.getActiveStatus(roomId);
      syncActiveStatus(status.active);

      if (status.active) {
        setInterrupted(projectId, false);
        invalidateRecoveryQueries();

        if (!pollingRef.current) {
          pollingRef.current = setInterval(async () => {
            if (isPollingRef.current) return;
            isPollingRef.current = true;
            try {
              const nextStatus = await api.sm.getActiveStatus(roomId);
              syncActiveStatus(nextStatus.active);
              if (!nextStatus.active) {
                stopPolling();
                setInterrupted(projectId, false);
                invalidateRecoveryQueries();
              }
            } catch (err) {
              console.warn('[ProjectRecovery] Poll error:', err);
            } finally {
              isPollingRef.current = false;
            }
          }, 2000);
        }
        return;
      }

      stopPolling();
      if (isInterrupted) {
        setInterrupted(projectId, false);
      }
      invalidateRecoveryQueries();
    } catch (err) {
      console.warn('[ProjectRecovery] Failed to check active status:', err);
    }
  }, [
    invalidateRecoveryQueries,
    isInterrupted,
    projectId,
    roomId,
    setInterrupted,
    stopPolling,
    syncActiveStatus,
  ]);

  const checkAndRecoverRef = useRef(checkAndRecover);
  checkAndRecoverRef.current = checkAndRecover;

  useEffect(() => {
    if (!isInterrupted) return;
    checkAndRecoverRef.current();
  }, [isInterrupted]);

  useEffect(() => {
    const handleRecover = () => {
      checkAndRecoverRef.current();
    };

    const handlePause = () => {
      stopPolling();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        handleRecover();
      } else {
        handlePause();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('pageshow', handleRecover);
    window.addEventListener('pagehide', handlePause);
    window.addEventListener('online', handleRecover);
    document.addEventListener('resume', handleRecover as EventListener);
    document.addEventListener('freeze', handlePause as EventListener);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('pageshow', handleRecover);
      window.removeEventListener('pagehide', handlePause);
      window.removeEventListener('online', handleRecover);
      document.removeEventListener('resume', handleRecover as EventListener);
      document.removeEventListener('freeze', handlePause as EventListener);
    };
  }, [stopPolling]);

  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);
}
