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

async function call<T>(path: string, body?: Record<string, unknown>, base = '/api/v1/prompts'): Promise<T> {
  const send = (token: string | null) =>
    fetch(`${base}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      cache: 'no-store',
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
  sha: (id: string) => call<{ id: string; sha: string }>(`/sha?id=${encodeURIComponent(id)}`),
  save: (id: string, text: string, note: string, baseSha: string) =>
    call<{ saved: boolean; item: PromptItem }>('/item', { id, text, note, base_sha: baseSha }),
  revert: (id: string, sha: string, baseSha: string) => call<{ saved: boolean; item: PromptItem }>('/revert', { id, sha, base_sha: baseSha }),
};

// ---- 指示文の画面の会話（2026-11-21）。部屋は1つ（app/api/prompts_screen.py の /prompts/chat）。発言はダン本体のチャットと同じ入口 ----
export interface ChatMessage { id: string; sender_type: string; content: string; created_at: string; client_message_id?: string | null }
export interface ChatStep { id: string; event_type: string; tool_name: string | null; tool_label: string | null; content: string | null; seq: number | null; created_at: string; metadata?: Record<string, unknown> | null }

const dan = <T,>(path: string, body?: Record<string, unknown>) => call<T>(path, body, '/api/v1');

export const promptsChat = {
  room: () => call<{ project_id: string; room_id: string; title: string }>('/chat'),
  messages: (room: string, limit = 40, before?: string) =>
    dan<{ messages: ChatMessage[] }>(`/chat/rooms/${room}/messages?limit=${limit}${before ? `&before=${encodeURIComponent(before)}` : ''}`).then(r => r.messages),
  active: (room: string) => dan<{ active: boolean; started_at?: number | string | null }>(`/chat/dan/sessions/${room}/active`),
  steps: (room: string) => dan<ChatStep[]>(`/chat/dan/sessions/${room}/execution-events?current_only=true`),
  stop: (room: string) => dan<{ success: boolean; withdrawn?: Array<{ id: string; content: string | null }> }>('/chat/dan/cancel', { session_id: room, withdraw_unread: true }),
  /** その部屋に本人の発言として届ける。保存の合図（user_message / followup_queued）を見たら届いたとする（開発室の deliver と同じ） */
  async send(content: string, room: string, id: string): Promise<void> {
    const body = { content, session_id: room, client_message_id: id };
    const post = (token: string | null) => fetch('/api/v1/chat/dan/messages/stream', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    });
    let response = await post(localStorage.getItem(TOKEN_KEY));
    if (response.status === 401) {
      const renewed = await refreshSession(value => { localStorage.setItem(TOKEN_KEY, value); useAuthStore.getState().setToken(value); });
      response = await post(renewed);
    }
    if (response.status === 401) throw new Error('ログインが切れています。入り直してから、もう一度送ってください。');
    if (!response.ok || !response.body) throw new Error(`届きませんでした（${response.status}）。もう一度送ってください。`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let text = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (value) text += decoder.decode(value, { stream: true });
      if (/"type": ?"(user_message|followup_queued|voice_call_routed)"/.test(text)) break;
      if (done || /"type": ?"error"/.test(text)) throw new Error('届いたか確かめられませんでした。もう一度送ってください。');
      if (text.length > 200000) text = text.slice(-2000);
    }
    // 返事はその部屋に出る。読み切るまでつないだままにする（切ると作業が止まる入口がある）
    void (async () => { try { while (!(await reader.read()).done); } catch { /* 閉じられた */ } })();
  },
};
