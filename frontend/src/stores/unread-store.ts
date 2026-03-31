import { create } from 'zustand';

interface UnreadState {
  /** Set of room IDs with unread messages */
  unreadRooms: Set<string>;
  /** Mark a room as having unread messages */
  markUnread: (roomId: string) => void;
  /** Mark a room as read */
  markRead: (roomId: string) => void;
  /** Total unread room count */
  unreadCount: () => number;
}

export const useUnreadStore = create<UnreadState>((set, get) => ({
  unreadRooms: new Set(),
  markUnread: (roomId) =>
    set((state) => {
      const next = new Set(state.unreadRooms);
      next.add(roomId);
      return { unreadRooms: next };
    }),
  markRead: (roomId) =>
    set((state) => {
      const next = new Set(state.unreadRooms);
      next.delete(roomId);
      return { unreadRooms: next };
    }),
  unreadCount: () => get().unreadRooms.size,
}));
