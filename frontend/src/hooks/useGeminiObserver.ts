'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type ObserverState = 'disconnected' | 'connecting' | 'connected' | 'error';

interface ObserverMessage {
  type: string;
  text?: string;
  step?: string;
  tool?: string;
  success?: boolean;
  params?: Record<string, unknown>;
  message?: string;
}

interface UseGeminiObserverOptions {
  sessionId: string | null;
  autoConnect?: boolean;
  onAssistantText?: (text: string) => void;
  onProcessStep?: (step: string) => void;
  onToolStart?: (tool: string, params: Record<string, unknown>) => void;
  onToolResult?: (tool: string, success: boolean) => void;
  onTurnComplete?: () => void;
  onUserText?: (text: string) => void;
}

interface UseGeminiObserverResult {
  state: ObserverState;
  error: string | null;
  messages: ObserverMessage[];
  sendText: (text: string) => void;
  connect: () => void;
  disconnect: () => void;
}

function getWsBase(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  if (typeof window === 'undefined') return 'ws://localhost:8000';
  // Same-origin WebSocket: use the Next.js dev server which proxies /ws/* to backend
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

export function useGeminiObserver({
  sessionId,
  autoConnect = false,
  onAssistantText,
  onProcessStep,
  onToolStart,
  onToolResult,
  onTurnComplete,
  onUserText,
}: UseGeminiObserverOptions): UseGeminiObserverResult {
  const [state, setState] = useState<ObserverState>('disconnected');
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ObserverMessage[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const maxReconnectAttempts = 5;

  // Callback refs
  const onAssistantTextRef = useRef(onAssistantText);
  const onProcessStepRef = useRef(onProcessStep);
  const onToolStartRef = useRef(onToolStart);
  const onToolResultRef = useRef(onToolResult);
  const onTurnCompleteRef = useRef(onTurnComplete);
  const onUserTextRef = useRef(onUserText);

  useEffect(() => { onAssistantTextRef.current = onAssistantText; }, [onAssistantText]);
  useEffect(() => { onProcessStepRef.current = onProcessStep; }, [onProcessStep]);
  useEffect(() => { onToolStartRef.current = onToolStart; }, [onToolStart]);
  useEffect(() => { onToolResultRef.current = onToolResult; }, [onToolResult]);
  useEffect(() => { onTurnCompleteRef.current = onTurnComplete; }, [onTurnComplete]);
  useEffect(() => { onUserTextRef.current = onUserText; }, [onUserText]);

  const disconnect = useCallback(() => {
    // Cancel any pending reconnect
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptRef.current = 0;
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
      wsRef.current = null;
    }
    setState('disconnected');
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (!sessionId) return;
    if (reconnectAttemptRef.current >= maxReconnectAttempts) {
      reconnectAttemptRef.current = 0;
      setState('disconnected');
      return;
    }

    const attempt = reconnectAttemptRef.current;
    const delay = Math.min(2000 * Math.pow(2, attempt), 32000); // 2s, 4s, 8s, 16s, 32s
    reconnectAttemptRef.current = attempt + 1;

    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      // connectRef is used to avoid stale closure — set below
      connectRef.current?.();
    }, delay);
  }, [sessionId]);

  const connectRef = useRef<(() => void) | null>(null);

  const connect = useCallback(async () => {
    if (!sessionId) return;

    setState('connecting');
    setError(null);

    try {
      const ws = new WebSocket(`${getWsBase()}/ws/gemini-voice`);
      wsRef.current = ws;

      await new Promise<void>((resolve, reject) => {
        ws.onopen = () => resolve();
        ws.onerror = () => reject(new Error('WebSocket connection failed'));
        setTimeout(() => reject(new Error('Connection timeout')), 10000);
      });

      // Auth
      const token = localStorage.getItem('done-token');
      ws.send(JSON.stringify({
        type: 'auth',
        token: token || '',
        session_id: sessionId,
      }));

      const authResp = await waitForJson(ws);
      if (authResp.type === 'error') {
        throw new Error(authResp.message || 'Auth failed');
      }

      // Config as observer
      ws.send(JSON.stringify({
        type: 'config',
        mode: 'observer',
      }));

      const configResp = await waitForJson(ws);
      if (configResp.type === 'error') {
        // No active voice session - schedule reconnect if we were reconnecting
        ws.close();
        wsRef.current = null;
        if (reconnectAttemptRef.current > 0) {
          scheduleReconnect();
        } else {
          setState('disconnected');
        }
        return;
      }

      // Successfully connected — reset reconnect counter
      reconnectAttemptRef.current = 0;

      // Message handler
      ws.onmessage = (event: MessageEvent) => {
        if (typeof event.data !== 'string') return;

        try {
          const data: ObserverMessage = JSON.parse(event.data);

          // session_ended: server is shutting down, try to reconnect
          if (data.type === 'session_ended') {
            wsRef.current = null;
            try { ws.close(); } catch {}
            setState('disconnected');
            scheduleReconnect();
            return;
          }

          setMessages(prev => [...prev, data]);

          switch (data.type) {
            case 'assistant_text':
              onAssistantTextRef.current?.(data.text || '');
              break;
            case 'process_step':
              onProcessStepRef.current?.(data.step || '');
              break;
            case 'tool_start':
              onToolStartRef.current?.(data.tool || '', data.params || {});
              break;
            case 'tool_result':
              onToolResultRef.current?.(data.tool || '', data.success || false);
              break;
            case 'turn_complete':
              onTurnCompleteRef.current?.();
              break;
            case 'user_text':
              onUserTextRef.current?.(data.text || '');
              break;
          }
        } catch {
          // Ignore
        }
      };

      ws.onclose = () => {
        setState('disconnected');
        wsRef.current = null;
      };

      ws.onerror = () => {
        setError('WebSocket error');
        setState('error');
      };

      setState('connected');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Connection failed';
      // If reconnecting, keep trying silently
      if (reconnectAttemptRef.current > 0) {
        scheduleReconnect();
      } else {
        setError(msg);
        setState('error');
      }
      if (wsRef.current) {
        try { wsRef.current.close(); } catch {}
        wsRef.current = null;
      }
    }
  }, [sessionId, scheduleReconnect]);

  // Keep connectRef in sync so scheduleReconnect can call it without stale closure
  useEffect(() => { connectRef.current = connect; }, [connect]);

  const sendText = useCallback((text: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'text',
        text,
      }));
    }
  }, []);

  // Auto-connect on mount; scheduleReconnect handles retries after session_ended
  const autoConnectDoneRef = useRef(false);
  useEffect(() => {
    if (autoConnect && sessionId && !autoConnectDoneRef.current) {
      autoConnectDoneRef.current = true;
      connect();
    }
  }, [autoConnect, sessionId, connect]);

  // Cleanup
  useEffect(() => {
    return () => { disconnect(); };
  }, [disconnect]);

  return {
    state,
    error,
    messages,
    sendText,
    connect,
    disconnect,
  };
}

function waitForJson(ws: WebSocket, timeoutMs = 10000): Promise<Record<string, string>> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      ws.removeEventListener('message', handler);
      reject(new Error('Timeout'));
    }, timeoutMs);

    function handler(event: MessageEvent) {
      if (typeof event.data === 'string') {
        clearTimeout(timeout);
        ws.removeEventListener('message', handler);
        try { resolve(JSON.parse(event.data)); } catch { reject(new Error('Invalid JSON')); }
      }
    }

    ws.addEventListener('message', handler);
  });
}
