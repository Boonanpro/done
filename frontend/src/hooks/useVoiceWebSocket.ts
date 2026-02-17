'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type VoiceSocketStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export type VoiceSocketMessage =
  | { type: 'auth_success'; user_id: string; session_id: string }
  | { type: 'progress'; step: string; session_id?: string }
  | { type: 'assistant_message'; text: string; session_id?: string; reasoning_steps?: string[] }
  | { type: 'processing'; status: 'start' | 'done' }
  | { type: 'notify'; message: string }
  | { type: 'error'; message: string }
  | { type: 'busy'; message: string }
  | { type: 'pong' }
  | Record<string, unknown>;

interface UseVoiceWebSocketOptions {
  token?: string | null;
  sessionId?: string | null;
  autoConnect?: boolean;
  onMessage?: (message: VoiceSocketMessage) => void;
}

interface UseVoiceWebSocketResult {
  status: VoiceSocketStatus;
  sessionId: string | null;
  lastMessage: VoiceSocketMessage | null;
  error: string | null;
  connect: () => void;
  disconnect: () => void;
  sendText: (text: string) => void;
  sendPing: () => void;
}

const buildWsUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) {
    const base = process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, '');
    return `${base.replace(/^http/, 'ws')}/ws/voice`;
  }
  if (typeof window === 'undefined') return 'ws://localhost:8000/ws/voice';
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/voice`;
};

export function useVoiceWebSocket(
  options: UseVoiceWebSocketOptions = {}
): UseVoiceWebSocketResult {
  const { token, sessionId: initialSessionId, autoConnect = true, onMessage } = options;

  const socketRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<VoiceSocketStatus>('disconnected');
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId ?? null);
  const sessionIdRef = useRef<string | null>(initialSessionId ?? null);
  const [lastMessage, setLastMessage] = useState<VoiceSocketMessage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const disconnect = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
    setStatus('disconnected');
  }, []);

  const connect = useCallback(() => {
    const url = buildWsUrl();
    if (socketRef.current) {
      socketRef.current.close();
    }

    setStatus('connecting');
    setError(null);

    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      setStatus('connected');
      socket.send(
        JSON.stringify({
          type: 'auth',
          token,
          session_id: sessionIdRef.current,
        })
      );
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as VoiceSocketMessage;
        setLastMessage(data);
        if (data && typeof data === 'object' && 'type' in data) {
          if (data.type === 'auth_success' && 'session_id' in data) {
            const nextSession = (data as { session_id?: string }).session_id ?? null;
            if (nextSession && nextSession !== sessionIdRef.current) {
              sessionIdRef.current = nextSession;
              setSessionId(nextSession);
            }
          }
        }
        onMessage?.(data);
      } catch (err) {
        setError('Invalid message payload');
      }
    };

    socket.onerror = () => {
      setStatus('error');
      setError('WebSocket error');
    };

    socket.onclose = () => {
      setStatus('disconnected');
      socketRef.current = null;
    };
  }, [token, onMessage]);

  const sendText = useCallback((text: string) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: 'user_message', text }));
  }, []);

  const sendPing = useCallback(() => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: 'ping' }));
  }, []);

  useEffect(() => {
    if (!autoConnect) return;
    connect();
    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  useEffect(() => {
    if (!initialSessionId) return;
    if (initialSessionId !== sessionIdRef.current) {
      sessionIdRef.current = initialSessionId;
      setSessionId(initialSessionId);
    }
  }, [initialSessionId]);

  return {
    status,
    sessionId,
    lastMessage,
    error,
    connect,
    disconnect,
    sendText,
    sendPing,
  };
}
