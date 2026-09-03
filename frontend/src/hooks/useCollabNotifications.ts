'use client';

import { useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { useUnreadStore } from '@/stores/unread-store';
import { api } from '@/lib/api-client';

/**
 * Connects a per-user WebSocket for real-time cross-room notifications.
 * Shows toast + updates unread store when a message arrives in any room.
 */
export function useCollabNotifications() {
  const markUnread = useUnreadStore((s) => s.markUnread);
  const syncFromServer = useUnreadStore((s) => s.syncFromServer);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // 未読のサーバー同期: 起動時＋定期。WS通知は即時の印、真実はサーバーの既読位置
  // （APKで読んだ部屋はここで消える）。
  useEffect(() => {
    let alive = true;
    const sync = () => {
      api.collab.listRooms()
        .then((d) => { if (alive) syncFromServer(d.rooms.filter((r) => r.unread).map((r) => r.id)); })
        .catch(() => {});
    };
    sync();
    const t = setInterval(sync, 30_000);
    const onFocus = () => sync();
    window.addEventListener('focus', onFocus);
    return () => { alive = false; clearInterval(t); window.removeEventListener('focus', onFocus); };
  }, [syncFromServer]);

  useEffect(() => {
    const token = localStorage.getItem('done-token');
    if (!token) return;

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const apiHost = window.location.host;
      const ws = new WebSocket(`${protocol}://${apiHost}/api/v1/collab/ws/notifications`);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ token }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'new_message_notification') {
            const roomId = data.room_id;
            const isOnRoom = window.location.pathname.includes(roomId);

            if (!isOnRoom) {
              markUnread(roomId);

              toast(data.room_title || 'メッセージ', {
                description: `${data.sender_name}: ${(data.content || '').slice(0, 60)}`,
                action: {
                  label: '開く',
                  onClick: () => {
                    window.location.href = `/collab/${roomId}`;
                  },
                },
                duration: 8000,
              });
            }
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        // Reconnect after 5 seconds
        reconnectTimer.current = setTimeout(connect, 5000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    // Keep alive ping every 30 seconds
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);

    return () => {
      clearInterval(pingInterval);
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [markUnread]);
}
