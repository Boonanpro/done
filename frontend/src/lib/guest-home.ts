// ゲスト（外部窓口の相手）の「自分の窓口」URL を端末保存から復元する。
// オーナー用URL（/collab/<room>）や /login に迷い込んだゲストを、ログイン画面ではなく
// 自分の窓口へ戻すために使う（iOS のホーム画面アプリは最後に開いていたURLを覚えるため、
// 一度ログイン画面に飛ぶと開き直しても毎回ログイン画面になる）。
import { api } from '@/lib/api-client';

export type GuestHomeCandidate = { inviteToken: string; roomId: string };

/** 端末に保存されている窓口の候補（新しく保存されたものが後ろ） */
export function guestHomeCandidates(): GuestHomeCandidate[] {
  if (typeof window === 'undefined') return [];
  try {
    const found: GuestHomeCandidate[] = [];
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
    return found;
  } catch {
    return [];
  }
}

/** 端末保存の窓口を1つ消す（無効になったトークン用） */
export function forgetGuestHome(inviteToken: string): void {
  try {
    localStorage.removeItem(`collab-guest-token-${inviteToken}`);
    localStorage.removeItem(`collab-guest-room-${inviteToken}`);
    localStorage.removeItem(`collab-guest-title-${inviteToken}`);
  } catch { /* ignore */ }
}

/**
 * サーバーに聞いて「今も有効な」自分の窓口URLを返す。
 * 削除された身分のトークンが端末に残っていることがある（Invalid invite link の原因）ので、
 * 保存されているだけでは信用せず、無効なものは消しながら探す。
 */
export async function findGuestHome(opts?: { preferRoomId?: string | null; exclude?: string }): Promise<string | null> {
  const candidates = guestHomeCandidates().filter((c) => c.inviteToken !== opts?.exclude);
  // 部屋が一致するものを先に、あとは新しい保存順
  const ordered = [
    ...candidates.filter((c) => opts?.preferRoomId && c.roomId === opts.preferRoomId),
    ...candidates.filter((c) => !(opts?.preferRoomId && c.roomId === opts.preferRoomId)).reverse(),
  ];
  for (const c of ordered) {
    try {
      const info = await api.collab.getInviteInfo(c.inviteToken);
      if (info && (info as { status?: string }).status !== 'expired') return `/collab/join/${c.inviteToken}`;
    } catch (e) {
      const status = (e as { status?: number })?.status;
      if (status === 404 || status === 410) forgetGuestHome(c.inviteToken);
    }
  }
  return null;
}

/** オーナーとしてログイン済みか（ゲストの保存とは別物） */
export function hasOwnerToken(): boolean {
  try { return !!localStorage.getItem('done-token'); } catch { return false; }
}
