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

export const PERSISTED_QUERY_KEYS = new Set(['projects', 'project', 'project-messages', 'chat-artifacts']);
export const PERSIST_MAX_AGE_MS = 24 * 60 * 60 * 1000;
// 保存形式を変えた時にここを上げると古い写しを捨てる
export const PERSIST_BUSTER = 'v1';

const KEY = 'done-rq-cache';

export function makeQueryPersister() {
  if (typeof window === 'undefined' || !('indexedDB' in window)) return undefined;
  return createAsyncStoragePersister({
    key: KEY,
    storage: {
      getItem: (k) => get<string>(k).then((v) => v ?? null).catch(() => null),
      setItem: (k, v) => set(k, v).catch(() => undefined),
      removeItem: (k) => del(k).catch(() => undefined),
    },
    // 連続更新（ポーリング・SSE）をまとめて書く
    throttleTime: 1500,
  });
}

export function shouldPersistQuery(query: Query): boolean {
  const head = query.queryKey[0];
  return query.state.status === 'success' && typeof head === 'string' && PERSISTED_QUERY_KEYS.has(head);
}
