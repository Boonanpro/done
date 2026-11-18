// 台本を聞いて直す画面（/script-listen）の呼び出し。裏側は app/api/script_listen_screen.py（サンドボックス）、
// 読み取り・音声・書き戻しは app/services/script_listen.py。
import { ApiError } from './api-client';
import { refreshSession } from './session-refresh';
import { useAuthStore } from '@/stores/auth-store';

const TOKEN_KEY = 'done-token';

export type ListenUnit =
  | { n: number; kind: 'title'; text: string }
  | { n: number; kind: 'heading'; level: number; text: string; read: boolean }
  | { n: number; kind: 'note'; text: string; section?: string }
  | {
      n: number; kind: 'say'; text: string; speak: string; para: number; start: number; end: number; bold: boolean;
      locked: boolean; section: string; gap: 's' | 'p' | 'h'; key: string; ready: boolean; seconds: number | null;
    };

export type SayUnit = Extract<ListenUnit, { kind: 'say' }>;

export interface ListenDoc {
  doc_id: string;
  title: string;
  revision: string;
  version: string | null;
  voice: string;
  voices: { id: string; name: string }[];
  units: ListenUnit[];
}

async function send(path: string, init: { method?: string; body?: unknown } = {}): Promise<Response> {
  const go = (token: string | null) =>
    fetch(`/api/v1/script-listen${path}`, {
      method: init.method || (init.body === undefined ? 'GET' : 'POST'),
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: 'include',
    });
  let response = await go(localStorage.getItem(TOKEN_KEY));
  if (response.status === 401) {
    const renewed = await refreshSession(value => {
      localStorage.setItem(TOKEN_KEY, value);
      useAuthStore.getState().setToken(value);
    });
    response = await go(renewed);
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, response.statusText, data);
  }
  return response;
}

async function json<T>(path: string, body?: unknown): Promise<T> {
  return (await send(path, { body })).json() as Promise<T>;
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = (e as unknown as { data?: { detail?: unknown } }).data?.detail;
    if (typeof d === 'string') return d;
  }
  return e instanceof Error ? e.message : String(e);
}

export const listenApi = {
  doc: (id: string, voice: string) => json<ListenDoc>(`/doc/${encodeURIComponent(id)}?voice=${encodeURIComponent(voice)}`),
  version: (id: string) => json<{ version: string | null }>(`/doc/${encodeURIComponent(id)}/version`),
  ahead: (voice: string, items: { speak: string; gap: string }[]) => json<{ queued: number }>('/ahead', { voice, items }),
  edit: (id: string, old: string, next: string, start: number) =>
    json<{ changed: boolean }>(`/doc/${encodeURIComponent(id)}/edit`, { old, new: next, start }),
  /** 1文の音声（mp3）。まだ無ければ裏で作ってから返る（1文2秒ほど）。 */
  clip: async (u: SayUnit, voice: string): Promise<Blob> => {
    const q = new URLSearchParams({ t: u.speak, v: voice, g: u.gap });
    return (await send(`/clip/${u.key}.mp3?${q.toString()}`)).blob();
  },
};
