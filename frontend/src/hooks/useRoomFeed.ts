'use client';

/**
 * 押し込み同期の受け口（ブラウザ）。
 *
 * 開いている間 /api/v1/chat/feed(SSE) を1本つなぎ、全部屋の新着メッセージを
 * react-query のキャッシュ（IndexedDB に永続化される）へ直接差し込む。
 * 部屋を開いた時には写しがすでに最新なので、通信を待たずに最新が出る。
 *
 * 切れていた間（タブ非表示・スリープ・再接続）は /api/v1/chat/rooms-delta で
 * 「最後に受け取った時刻以降」の全部屋の差分を1往復で取り込む。
 */
import { useEffect, useRef } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';

import type { MessageResponse, ProjectListResponse } from '@/lib/api-client';
import { perfLog } from '@/lib/perf-log';

const LAST_KEY = 'done-feed-last-at';

type FeedMessageEvent = { type: 'message'; room_id: string; message: MessageResponse; at?: number };

function readLastAt(): string | null {
  try {
    return localStorage.getItem(LAST_KEY);
  } catch {
    return null;
  }
}

function writeLastAt(iso: string): void {
  try {
    localStorage.setItem(LAST_KEY, iso);
  } catch {
    /* ignore */
  }
}

/** 部屋のメッセージキャッシュへ1件差し込む（新しい順を維持、重複は無視）。キャッシュが無い部屋は触らない。 */
export function applyFeedMessage(queryClient: QueryClient, msg: MessageResponse): boolean {
  const key = ['project-messages', msg.room_id];
  const cur = queryClient.getQueryData<{ messages: MessageResponse[] }>(key);
  if (!cur) return false;
  if (cur.messages.some((m) => m.id === msg.id)) return false;
  const merged = [msg, ...cur.messages].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  queryClient.setQueryData(key, { messages: merged });
  return true;
}

/** サイドバーの一覧キャッシュの「最終メッセージ」を更新する。 */
function applyToProjectList(queryClient: QueryClient, msg: MessageResponse): void {
  queryClient.setQueryData<ProjectListResponse>(['projects'], (cur) => {
    if (!cur?.projects) return cur;
    let touched = false;
    const projects = cur.projects.map((p) => {
      if (p.room_id !== msg.room_id) return p;
      if ((p.last_message_at || '') >= msg.created_at) return p;
      touched = true;
      return { ...p, last_message_at: msg.created_at, last_message_preview: (msg.content || '').slice(0, 80) };
    });
    return touched ? { ...cur, projects } : cur;
  });
}

export function useRoomFeed(enabled: boolean): void {
  const queryClient = useQueryClient();
  const lastAtRef = useRef<string | null>(null);
  const syncingRef = useRef(false);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;
    let es: EventSource | null = null;
    let closed = false;
    let retry = 1000;
    let retryTimer: number | null = null;
    lastAtRef.current = readLastAt();

    const catchUp = async (reason: string) => {
      if (syncingRef.current) return;
      const since = lastAtRef.current;
      if (!since) return; // 初回は何も知らないので差分は取らない（各部屋は開いた時に /open が取る）
      syncingRef.current = true;
      const t0 = performance.now();
      try {
        const res = await fetch(`/api/v1/chat/rooms-delta?since=${encodeURIComponent(since)}&limit=500`, {
          credentials: 'include',
        });
        if (!res.ok) return;
        const data = (await res.json()) as { messages: MessageResponse[]; server_time: string; complete: boolean };
        let applied = 0;
        for (const m of data.messages) {
          if (applyFeedMessage(queryClient, m)) applied += 1;
          applyToProjectList(queryClient, m);
        }
        if (data.complete) {
          lastAtRef.current = data.server_time;
          writeLastAt(data.server_time);
        } else if (data.messages.length) {
          const last = data.messages[data.messages.length - 1].created_at;
          lastAtRef.current = last;
          writeLastAt(last);
        }
        perfLog({ surface: 'web', event: 'feed-catchup', ms: performance.now() - t0, extra: { reason, received: data.messages.length, applied } });
      } catch {
        /* 次の機会に */
      } finally {
        syncingRef.current = false;
      }
    };

    const connect = () => {
      if (closed) return;
      es = new EventSource('/api/v1/chat/feed', { withCredentials: true });
      es.addEventListener('hello', (ev) => {
        retry = 1000;
        try {
          const d = JSON.parse((ev as MessageEvent).data) as { server_time: string };
          // つながった時点で、切れていた間の分を追いつく
          void catchUp('connect').then(() => {
            if (!lastAtRef.current) {
              lastAtRef.current = d.server_time;
              writeLastAt(d.server_time);
            }
          });
        } catch {
          /* ignore */
        }
      });
      es.addEventListener('message', (ev) => {
        try {
          const d = JSON.parse((ev as MessageEvent).data) as FeedMessageEvent;
          applyFeedMessage(queryClient, d.message);
          applyToProjectList(queryClient, d.message);
          if (d.message.created_at > (lastAtRef.current || '')) {
            lastAtRef.current = d.message.created_at;
            writeLastAt(d.message.created_at);
          }
        } catch {
          /* ignore */
        }
      });
      es.onerror = () => {
        es?.close();
        es = null;
        if (closed) return;
        retryTimer = window.setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30_000);
      };
    };

    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      void catchUp('visible');
      if (!es) connect();
    };
    const onOnline = () => {
      void catchUp('online');
      if (!es) connect();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('online', onOnline);
    connect();

    return () => {
      closed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      es?.close();
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('online', onOnline);
    };
  }, [enabled, queryClient]);
}
