/**
 * react-query キャッシュの永続化（IndexedDB）。
 *
 * 部屋を開いた時の一式（一覧・部屋・メッセージ・成果物）をブラウザ内に残し、
 * 次回はネットワークを待たずに手元の写しを描いてから裏で差分同期する（LINE方式）。
 * 実測で部屋切替の待ちは「遠いDBへの往復」が主因だったので、往復を画面の前提から外す。
 *
 * 永続化するのは「表示の骨格」だけ。実行中かどうか（session-active / current-run /
 * execution-events）は数秒で変わる揮発情報なので保存しない。
 */
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import type { Query } from '@tanstack/react-query';
import { del, get, set } from 'idb-keyval';

export const PERSISTED_QUERY_KEYS = new Set([
  'projects', 'project', 'project-messages', 'chat-artifacts',
  // コミュニケーション（一覧・部屋・メッセージ・参加者）も同じ扱い。一覧は以前
  // 2〜4秒のAPIを毎回待って骨組み表示していたので、手元の写しを先に描く
  'collab-rooms', 'collab-room', 'collab-messages', 'collab-participants',
  // 送信案カード（一覧＋各カード本体）。写しが無いと開くたびに「読み込み中…」→出現し直しになり、
  // 中身は変わっていないのに「再生成された」ように見える（2026-09-14）
  'collab-outbound', 'outbound-proposal',
]);
export const PERSIST_MAX_AGE_MS = 24 * 60 * 60 * 1000;
// 保存形式を変えた時にここを上げると古い写しを捨てる
export const PERSIST_BUSTER = 'v2';

const KEY = 'done-rq-cache';

// 部屋ごとの会話（一番重い）は、新しく読んだ順にこの数の部屋だけ残す。全部の部屋を残すと本人の端末で6.8MBになり、
// 読み戻しに31秒かかった（2026-11-21）。開くのは最近の部屋がほとんどなので、残りはネットから読む
const PER_ROOM_KEYS = new Set(['project', 'project-messages', 'chat-artifacts', 'collab-room', 'collab-messages', 'collab-participants', 'outbound-proposal']);
const KEEP_ROOMS = 16; // 部屋の番号と会話の部屋の番号で2つずつ数えるので、約8部屋
const MAX_CHARS = 2_500_000;

type Dehydrated = { clientState: { queries: Array<{ queryKey: readonly unknown[]; state: { dataUpdatedAt?: number } }> } };
type Q = Dehydrated['clientState']['queries'][number];
const roomOf = (q: Q) => (PER_ROOM_KEYS.has(String(q.queryKey[0])) ? JSON.stringify(q.queryKey.slice(1, 2)) : null);

/** Keeps the shared lists and only the `rooms` most recently read rooms, so the kept copy stays small enough to read back quickly. */
export function trimPersisted<T>(client: T, rooms = KEEP_ROOMS): T {
  const c = client as unknown as Dehydrated;
  const queries = c?.clientState?.queries;
  if (!Array.isArray(queries)) return client;
  const latest = new Map<string, number>();
  for (const q of queries) {
    const r = roomOf(q);
    if (r != null) latest.set(r, Math.max(latest.get(r) ?? 0, q.state?.dataUpdatedAt ?? 0));
  }
  const keep = new Set([...latest.entries()].sort((x, y) => y[1] - x[1]).slice(0, rooms).map(([r]) => r));
  const kept = queries.filter((q) => { const r = roomOf(q); return r == null || keep.has(r); });
  return { ...c, clientState: { ...c.clientState, queries: kept } } as unknown as T;
}

function serialize(client: unknown): string {
  // まだ大きければ、残す部屋を半分ずつ減らす
  let rooms = KEEP_ROOMS;
  let out = JSON.stringify(trimPersisted(client, rooms));
  while (out.length > MAX_CHARS && rooms > 1) {
    rooms = Math.floor(rooms / 2);
    out = JSON.stringify(trimPersisted(client, rooms));
  }
  return out;
}

export function makeQueryPersister() {
  if (typeof window === 'undefined' || !('indexedDB' in window)) return undefined;
  return createAsyncStoragePersister({
    key: KEY,
    storage: {
      getItem: (k) => get<string>(k).then((v) => v ?? null).catch(() => null),
      setItem: (k, v) => set(k, v).catch(() => undefined),
      removeItem: (k) => del(k).catch(() => undefined),
    },
    serialize,
    // 連続更新（ポーリング・SSE）をまとめて書く。数MBを1.5秒ごとに書き直すと端末の置き場所が重くなるので5秒
    throttleTime: 5000,
  });
}

export function shouldPersistQuery(query: Query): boolean {
  const head = query.queryKey[0];
  return query.state.status === 'success' && typeof head === 'string' && PERSISTED_QUERY_KEYS.has(head);
}
