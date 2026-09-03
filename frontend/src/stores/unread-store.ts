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
  /** サーバーの未読判定（collab_rooms.unread）で丸ごと置き換える。
   *  未読の真実はサーバー（owner_last_read_at）。APK等の別端末で読めばここも消える */
  syncFromServer: (roomIds: string[]) => void;
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
  syncFromServer: (roomIds) =>
    set((state) => {
      const next = new Set(roomIds);
      const same = next.size === state.unreadRooms.size && [...next].every((id) => state.unreadRooms.has(id));
      return same ? state : { unreadRooms: next };
    }),
}));
