'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { get, update } from 'idb-keyval';
import { api, type CollabMessageResponse } from '@/lib/api-client';
import { uploadCollabFiles, type UploadedFile } from '@/components/collab/pending-attachments';

export type OutboxMessage = {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
  files: File[];
  uploaded?: UploadedFile[];
  createdAt: string;
  error?: string;
};

/** Durable sends survive closing the tab and reconnecting. The API deduplicates by client_msg_id. */
export function useCollabOutbox(roomId: string | null, token: string | null, invite: string,
  onSent: (message: CollabMessageResponse) => void) {
  const key = `collab-outbox:${invite}`;
  const [entries, setEntries] = useState<OutboxMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const onSentRef = useRef(onSent);
  onSentRef.current = onSent;
  const reload = useCallback(async () => setEntries((await get<OutboxMessage[]>(key)) || []), [key]);

  useEffect(() => {
    void reload();
    const wake = () => { setVersion(v => v + 1); void reload(); };
    window.addEventListener('online', wake);
    // A modest retry interval also covers an online connection whose server was temporarily down.
    const timer = setInterval(wake, 30_000);
    return () => { clearInterval(timer); window.removeEventListener('online', wake); };
  }, [reload]);

  useEffect(() => {
    if (!roomId || !token) return;
    let cancelled = false;
    const drain = async () => {
      if (cancelled || !navigator.onLine) return;
      setBusy(true);
      try {
        const pending = (await get<OutboxMessage[]>(key)) || [];
        for (const entry of pending) {
          if (cancelled || !navigator.onLine || entry.error) break;
          try {
            const uploaded = [...(entry.uploaded || [])];
            for (const file of entry.files.slice(uploaded.length)) {
              uploaded.push(...await uploadCollabFiles(roomId, [file], { guestToken: token }));
              await update<OutboxMessage[]>(key, list => (list || []).map(m => m.id === entry.id ? { ...m, uploaded } : m));
            }
            const metadata = { ...entry.metadata, client_msg_id: entry.id,
              ...(uploaded.length ? { files: uploaded, file: uploaded[0] } : {}) };
            const sent = await api.collab.sendMessage(roomId, entry.content, token, metadata);
            onSentRef.current(sent);
            await update<OutboxMessage[]>(key, list => (list || []).filter(m => m.id !== entry.id));
            await reload();
          } catch (error) {
            const status = (error as { status?: number })?.status;
            if ((status && status >= 400 && status < 500) || /HTTP 4\d\d/.test(String(error))) {
              await update<OutboxMessage[]>(key, list => (list || []).map(m => m.id === entry.id
                ? { ...m, error: '送信できませんでした。内容や添付を確認してください' } : m));
            }
            await reload();
            break;
          }
        }
      } finally { if (!cancelled) setBusy(false); }
    };
    // Web Locks prevents two restored tabs from uploading the same queue concurrently.
    if (navigator.locks) void navigator.locks.request(key, drain);
    else void drain();
    return () => { cancelled = true; };
  }, [key, roomId, token, version, reload]);

  const enqueue = useCallback(async (content: string, metadata: Record<string, unknown>, files: File[]) => {
    const entry: OutboxMessage = { id: `temp-${crypto.randomUUID()}`, content, metadata, files, createdAt: new Date().toISOString() };
    await update<OutboxMessage[]>(key, list => [...(list || []), entry]);
    await reload();
    setVersion(v => v + 1);
  }, [key, reload]);
  const retry = useCallback(async () => {
    await update<OutboxMessage[]>(key, list => (list || []).map(({ error: _, ...m }) => m));
    await reload(); setVersion(v => v + 1);
  }, [key, reload]);
  const remove = useCallback(async (id: string) => {
    await update<OutboxMessage[]>(key, list => (list || []).filter(m => m.id !== id));
    await reload(); setVersion(v => v + 1);
  }, [key, reload]);
  return { entries, busy, enqueue, retry, remove };
}
