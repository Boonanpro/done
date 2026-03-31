'use client';

import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { api } from '@/lib/api-client';
import { useUnreadStore } from '@/stores/unread-store';

/**
 * Polls collab rooms and:
 * 1. Shows toast when a new message arrives (if not on that room's page)
 * 2. Updates unread store for badge display
 */
export function useCollabNotifications() {
  const lastMessages = useRef<Record<string, string>>({});
  const initialized = useRef(false);
  const markUnread = useUnreadStore((s) => s.markUnread);

  const { data } = useQuery({
    queryKey: ['collab-rooms-poll'],
    queryFn: () => api.collab.listRooms(),
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  useEffect(() => {
    if (!data?.rooms) return;

    if (!initialized.current) {
      for (const room of data.rooms) {
        if (room.last_message) {
          lastMessages.current[room.id] = room.last_message;
        }
      }
      initialized.current = true;
      return;
    }

    for (const room of data.rooms) {
      const prev = lastMessages.current[room.id];
      const current = room.last_message;

      if (current && current !== prev) {
        const isOnRoom = window.location.pathname.includes(room.id);

        if (!isOnRoom) {
          // Mark as unread
          markUnread(room.id);

          // Toast notification
          toast(room.title, {
            description: current.slice(0, 80),
            action: {
              label: '開く',
              onClick: () => {
                window.location.href = `/collab/${room.id}`;
              },
            },
            duration: 8000,
          });
        }

        lastMessages.current[room.id] = current;
      }
    }
  }, [data, markUnread]);
}
