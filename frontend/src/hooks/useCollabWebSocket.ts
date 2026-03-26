'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import type { CollabMessageResponse } from '@/lib/api-client';

interface UseCollabWebSocketOptions {
  roomId: string;
  token: string;
  isGuest?: boolean;
  onMessage?: (message: CollabMessageResponse) => void;
  onUserJoined?: (data: { sender_type: string; sender_name: string; online_users: OnlineUser[] }) => void;
  onUserLeft?: (data: { sender_type: string; sender_name: string; online_users: OnlineUser[] }) => void;
  onTyping?: (data: { sender_type: string; sender_name: string }) => void;
  onDanThinking?: () => void;
}

export interface OnlineUser {
  sender_type: string;
  sender_name: string;
}

export function useCollabWebSocket({
  roomId,
  token,
  isGuest = false,
  onMessage,
  onUserJoined,
  onUserLeft,
  onTyping,
  onDanThinking,
}: UseCollabWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [onlineUsers, setOnlineUsers] = useState<OnlineUser[]>([]);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    // Use API URL for WebSocket (Vercel doesn't proxy WS, connect to backend directly)
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || '';
    let wsUrl: string;
    if (apiUrl) {
      // External API: convert https://xxx to wss://xxx
      wsUrl = apiUrl.replace(/^http/, 'ws') + `/api/v1/collab/ws/${roomId}`;
    } else {
      // Local dev: use same host
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      wsUrl = `${protocol}//${window.location.host}/api/v1/collab/ws/${roomId}`;
    }
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      // Send auth
      ws.send(JSON.stringify({
        type: isGuest ? 'auth_guest' : 'auth',
        token,
      }));
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case 'auth_success':
            setIsConnected(true);
            reconnectAttempts.current = 0;
            break;
          case 'new_message':
            onMessage?.(data.message);
            break;
          case 'user_joined':
            setOnlineUsers(data.online_users || []);
            onUserJoined?.(data);
            break;
          case 'user_left':
            setOnlineUsers(data.online_users || []);
            onUserLeft?.(data);
            break;
          case 'typing':
            onTyping?.(data);
            break;
          case 'dan_thinking':
            onDanThinking?.();
            break;
          case 'error':
            console.error('Collab WS error:', data.message);
            break;
        }
      } catch (e) {
        console.error('Failed to parse WS message:', e);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      // Reconnect with backoff
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
      reconnectAttempts.current++;
      reconnectTimeoutRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [roomId, token, isGuest, onMessage, onUserJoined, onUserLeft, onTyping, onDanThinking]);

  useEffect(() => {
    if (roomId && token) {
      connect();
    }
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      wsRef.current?.close();
    };
  }, [roomId, token, connect]);

  const sendMessage = useCallback((content: string, metadata?: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'message', content, metadata }));
    }
  }, []);

  const sendTyping = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'typing' }));
    }
  }, []);

  return { isConnected, onlineUsers, sendMessage, sendTyping };
}
