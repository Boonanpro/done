// コラボ窓口のメッセージ一覧の合流ルール。
//
// 受信は「最新N件を丸ごと取り直す」ポーリングなので、素朴に置き換えると
// (1) 過去を遡って読み足した分が消える (2) 配列の参照が毎回変わるので
// 「新着で最下部へ」の処理が5秒ごとに走って、上へ遡れなくなる。
// ここでは差分だけを反映し、画面側は「本当に増えた時」だけ下へ送る。

export type ScrollMessage = {
  id: string;
  created_at: string;
  metadata?: unknown;
};

const time = (m: ScrollMessage) => new Date(m.created_at).getTime() || 0;
const byTime = (a: ScrollMessage, b: ScrollMessage) => time(a) - time(b);

/**
 * サーバーの「最新N件」を手元のリストへ反映する。
 * - 手元にしか無い古い行（遡って読み足した分）は残す
 * - 送信直後の仮バブル（temp-*）はサーバーに現れるまで残す
 */
export function mergeLatest<T extends ScrollMessage>(prev: T[], server: T[]): T[] {
  if (server.length === 0) return prev;
  const serverIds = new Set(server.map((m) => m.id));
  const serverCids = new Set(
    server.map((m) => (m.metadata as { client_msg_id?: string } | undefined)?.client_msg_id).filter(Boolean)
  );
  const oldestServer = Math.min(...server.map(time));
  const kept = prev.filter((m) => {
    if (serverIds.has(m.id) || serverCids.has(m.id)) return false;
    if (m.id.startsWith('temp-')) return true;          // 送信中の仮バブル
    return time(m) < oldestServer;                       // 遡って読み足した過去
  });
  if (kept.length === 0) return server;
  return [...kept, ...server].sort(byTime);
}

/** 遡り取得した過去ぶんを先頭へ足す（重複は捨てる） */
export function mergeOlder<T extends ScrollMessage>(prev: T[], older: T[]): T[] {
  const have = new Set(prev.map((m) => m.id));
  const add = older.filter((m) => !have.has(m.id));
  if (add.length === 0) return prev;
  return [...add, ...prev].sort(byTime);
}

/** いま最下部にいるか（この余白の中なら「下にいる」とみなす） */
export const BOTTOM_THRESHOLD = 80;

export function isAtBottom(el: HTMLElement | null): boolean {
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_THRESHOLD;
}

/** 上端に近いか（過去の読み足しを始める位置） */
export function isNearTop(el: HTMLElement | null): boolean {
  return !!el && el.scrollTop < 200;
}
