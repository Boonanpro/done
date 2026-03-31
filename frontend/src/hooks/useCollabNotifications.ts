'use client';

import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { api } from '@/lib/api-client';

/**
 * Polls collab rooms and shows a toast when a new message arrives
 * in any room the user is part of (as owner or guest).
 * Only triggers when the user is NOT on that room's chat page.
 */
export function useCollabNotifications() {
  const lastMessages = useRef<Record<string, string>>({});
  const initialized = useRef(false);

  const { data } = useQuery({
    queryKey: ['collab-rooms-poll'],
    queryFn: () => api.collab.listRooms(),
    refetchInterval: 15_000, // 15秒ごと
    staleTime: 10_000,
  });

  useEffect(() => {
    if (!data?.rooms) return;

    // Skip first load (don't toast existing messages)
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
        // Don't toast if user is already on this room's page
        const isOnRoom = window.location.pathname.includes(room.id);
        if (!isOnRoom) {
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
  }, [data]);
}
