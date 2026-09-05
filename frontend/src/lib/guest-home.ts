// ゲスト（外部窓口の相手）の「自分の窓口」URL を端末保存から復元する。
// オーナー用URL（/collab/<room>）や /login に迷い込んだゲストを、ログイン画面ではなく
// 自分の窓口へ戻すために使う（iOS のホーム画面アプリは最後に開いていたURLを覚えるため、
// 一度ログイン画面に飛ぶと開き直しても毎回ログイン画面になる）。
export function guestHomeUrl(preferRoomId?: string | null): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const found: { inviteToken: string; roomId: string }[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i) || '';
      const m = key.match(/^collab-guest-token-(.+)$/);
      if (!m) continue;
      const inviteToken = m[1];
      const guestToken = localStorage.getItem(key);
      const roomId = localStorage.getItem(`collab-guest-room-${inviteToken}`);
      if (!guestToken || !roomId) continue;
      found.push({ inviteToken, roomId });
    }
    if (found.length === 0) return null;
    const pick = (preferRoomId && found.find((f) => f.roomId === preferRoomId)) || found[found.length - 1];
    return `/collab/join/${pick.inviteToken}`;
  } catch {
    return null;
  }
}

/** オーナーとしてログイン済みか（ゲストの保存とは別物） */
export function hasOwnerToken(): boolean {
  try { return !!localStorage.getItem('done-token'); } catch { return false; }
}
