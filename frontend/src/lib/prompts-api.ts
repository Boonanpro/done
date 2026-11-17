// ダンを動かしている指示文を本人が読んで直す画面（/prompts）の呼び出し。
// 裏側は app/api/prompts_screen.py（サンドボックス）、文の置き場所は ~/.dan/workspace/prompts（app/services/prompt_store.py）。
import { ApiError } from './api-client';
import { refreshSession } from './session-refresh';
import { useAuthStore } from '@/stores/auth-store';

const TOKEN_KEY = 'done-token';

export interface PromptPlace { id: string; name: string; line: string }

export interface PromptVersion { at: string; by: 'owner' | 'dan' | 'seed'; note: string; sha: string; text: string }

export interface PromptSummary {
  id: string;
  title: string;
  place: string;
  reader: string;
  when: string;
  source: string;
  why: string;
  kind?: string;
  readonly?: boolean;
  chars: number;
  sha?: string;
  last_by?: string | null;
  last_at?: string | null;
  edited_by_owner?: boolean;
  code_history?: { date: string; what: string }[];
  marks?: string[];
  mark_notes?: Record<string, string>;
  keys?: string[];
  error?: string;
}

export interface PromptItem extends PromptSummary { text: string; sha: string; history: PromptVersion[] }

async function call<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const send = (token: string | null) =>
    fetch(`/api/v1/prompts${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'include',
    });
  let response = await send(localStorage.getItem(TOKEN_KEY));
  if (response.status === 401) {
    const renewed = await refreshSession(value => {
      localStorage.setItem(TOKEN_KEY, value);
      useAuthStore.getState().setToken(value);
    });
    response = await send(renewed);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, response.statusText, data);
  return data as T;
}

export const promptsApi = {
  list: () => call<{ places: PromptPlace[]; prompts: PromptSummary[] }>(''),
  item: (id: string) => call<PromptItem>(`/item?id=${encodeURIComponent(id)}`),
  save: (id: string, text: string, note: string, baseSha: string) =>
    call<{ saved: boolean; item: PromptItem }>('/item', { id, text, note, base_sha: baseSha }),
  revert: (id: string, sha: string) => call<{ saved: boolean; item: PromptItem }>('/revert', { id, sha }),
};
