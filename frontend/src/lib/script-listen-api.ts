// 台本を聞いて直す画面（/script-listen）の呼び出し。裏側は app/api/script_listen_screen.py（サンドボックス）、
// 読み取り・音声・書き戻しは app/services/script_listen.py。
import { ApiError } from './api-client';
import { refreshSession } from './session-refresh';
import { useAuthStore } from '@/stores/auth-store';

const TOKEN_KEY = 'done-token';

/** A piece of a unit as the doc has it: suggested insertions / deletions carry their suggestion id. */
export type Seg = { t: string; ins?: string; del?: string; blue?: boolean; b?: boolean };

export type ListenUnit =
  | { n: number; kind: 'title'; text: string }
  /** A picture where it is in the doc. ins / del: the suggestion that adds / takes it out. */
  | { n: number; kind: 'image'; src: string; id?: string; para?: number; ins?: string; del?: string; section?: string;
      /** A picture of the top part (a thumbnail): its place among them, and its work made of parts when it has one. */
      thumb_order?: number; thumb?: string }
  | { n: number; kind: 'heading'; level: number; text: string; read: boolean; segs?: Seg[]; para?: number }
  | { n: number; kind: 'note'; text: string; section?: string; para?: number; segs?: Seg[] }
  | { n: number; kind: 'blank'; text: string; section?: string; para: number; segs: Seg[] }
  | { n: number; kind: 'gone'; text: string; para: number; section?: string; segs: Seg[] }
  | {
      n: number; kind: 'say'; text: string; speak: string; para: number; start: number; end: number; bold: boolean;
      locked: boolean; section: string; gap: 's' | 'p' | 'h'; key: string; ready: boolean; seconds: number | null; segs?: Seg[];
    };

export type SayUnit = Extract<ListenUnit, { kind: 'say' }>;

/** by owner: written in suggestion mode on this screen (kept by the screen; the Docs API cannot write suggestions). */
export interface Suggestion { id: string; ins: string; del: string; n: number; by?: 'owner' | 'doc' }

export type EditMode = 'edit' | 'suggest';

export interface ReplaceResult {
  changed: boolean;
  revision?: string | null;
  /** The doc had changed meanwhile and the owner's change was put onto it. */
  rebased?: boolean;
  /** What the screen shows is no longer what the doc is (a suggestion was settled): read it again. */
  reload?: boolean;
  /** Suggestions settled because their words were typed over: {id: accepted}. */
  settled?: Record<string, boolean>;
}

export interface ListenDoc {
  doc_id: string;
  title: string;
  revision: string;
  version: string | null;
  voice: string;
  voices: { id: string; name: string }[];
  units: ListenUnit[];
  suggestions: Suggestion[];
}

/** The script of a video this script was modelled on, cut into the same sections (app/services/script_listen_refs.py). */
export interface RefSection { match: string; start: number | null; text: string }
export interface Reference { id: string; who: string; title: string; url: string; length: string; note: string; sections: RefSection[] }

export interface ThreadMessage {
  id: string;
  who: 'owner' | 'dan' | 'other';
  name?: string;
  text?: string;
  action?: string;
  at?: string;
}

/** One line of Dan's work log on a comment (the same lines the chat shows while Dan works). */
/** say: a tool step in plain words (for the one line when Dan has not written a line for a while). */
export interface WorkEvent { seq: number; kind: 'progress' | 'result' | 'error' | 'tool' | 'input'; text: string; at: string; say?: string }

/** Dan's answer to one or more comments: waiting, working, or just ended (kept 15 min). */
export interface DanJob {
  id: string;
  status: 'pending' | 'running' | 'needs_room' | 'completed' | 'attention' | 'failed';
  comment_ids: string[];
  started: string;
  updated: string | null;
  events: WorkEvent[];
  /** The words Dan's browser step is selecting / typing in the doc now (live), or did a few seconds ago. */
  touch?: { words: string[]; live: boolean } | null;
}

export interface Thread {
  id: string;
  quote: string;
  resolved: boolean;
  messages: ThreadMessage[];
  at?: string;
  /** pending / running: Dan is on it. needs_room: Dan asked which room the script belongs to. */
  working: string | null;
  start: number | null;
  /** Written on a suggestion's card: the suggestion it is about (it may be gone by now). */
  suggestion?: string | null;
  /** That suggestion's words (to find the one Dan put in for it when it is gone). */
  suggestion_words?: { ins: string; del: string } | null;
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

/** url null: no copy made yet. behind: the working doc moved on since the copy was last updated. */
export interface ShareState { url: string | null; behind: boolean; pending: number; updated_at?: string | null }

/** A thumbnail of the doc tied to a work made of parts (app/services/script_listen_thumbs.py). */
export interface ThumbItem { order: number; object: string; content_id: string; synced_rev: number; rev: number; stale: boolean }

export const listenApi = {
  thumbOpen: (id: string, object: string | null, order: number | null) =>
    json<{ room_id: string; content_id: string }>(`/doc/${encodeURIComponent(id)}/thumb/open`, { object, order }),
  thumbs: (id: string) => json<{ items: ThumbItem[] }>(`/doc/${encodeURIComponent(id)}/thumbs`),
  thumbSync: (id: string, contentId?: string) => json<{ changed?: number; busy?: boolean }>(`/doc/${encodeURIComponent(id)}/thumb/sync`, { content_id: contentId || null }),
  /** The link to send to the other side: the customer's copy, anyone with it can edit and comment (app/services/script_share.py). */
  shareState: (id: string) => json<ShareState>(`/doc/${encodeURIComponent(id)}/share`),
  share: (id: string, update = false) => json<ShareState & { made?: boolean; updated?: boolean }>(`/doc/${encodeURIComponent(id)}/share`, { update }),
  /** The room of the chat at the side of the screen (app/services/script_rooms.py). */
  room: (id: string) => json<{ project_id: string; room_id: string; title: string }>(`/doc/${encodeURIComponent(id)}/room`, {}),
  state: (id: string, body: { para?: number | null; sentence?: string; selection?: string; playing?: boolean; thumb?: string }) =>
    json<{ ok: boolean }>(`/doc/${encodeURIComponent(id)}/state`, body),
  doc: (id: string, voice: string) => json<ListenDoc>(`/doc/${encodeURIComponent(id)}?voice=${encodeURIComponent(voice)}`),
  references: (id: string) => json<{ refs: Reference[] }>(`/doc/${encodeURIComponent(id)}/references`),
  version: (id: string) => json<{ version: string | null }>(`/doc/${encodeURIComponent(id)}/version`),
  ahead: (voice: string, items: { speak: string; gap: string }[]) => json<{ queued: number }>('/ahead', { voice, items }),
  edit: (id: string, old: string, next: string, start: number) =>
    json<{ changed: boolean }>(`/doc/${encodeURIComponent(id)}/edit`, { old, new: next, start }),
  /** 段落 para_from..para_to（'\n' でつないだ文）を old から new へ。new_bmask は1文字ずつの太字（'0'/'1'）。 */
  replace: (id: string, body: {
    para_from: number; para_to: number; old: string; new: string; old_bmask: string; new_bmask: string; new_dmask?: string; mode?: EditMode;
  }) => json<ReplaceResult>(`/doc/${encodeURIComponent(id)}/replace`, body),
  acceptAll: (id: string) => json<{ accepted: number; failed: number }>(`/doc/${encodeURIComponent(id)}/suggestions/accept-all`, {}),
  rejectAll: (id: string) => json<{ rejected: number; failed: number }>(`/doc/${encodeURIComponent(id)}/suggestions/reject-all`, {}),
  activity: (id: string) => json<{ jobs: DanJob[] }>(`/doc/${encodeURIComponent(id)}/activity`),
  comments: (id: string) => json<{ threads: Thread[]; can_comment: boolean }>(`/doc/${encodeURIComponent(id)}/comments`),
  addComment: (id: string, body: { text: string; quote: string; start?: number | null; sentence?: string; suggestion?: Suggestion }) =>
    json<{ id: string }>(`/doc/${encodeURIComponent(id)}/comments`, body),
  reply: (id: string, cid: string, text: string, suggestion?: Suggestion) =>
    json<{ id: string }>(`/doc/${encodeURIComponent(id)}/comments/${encodeURIComponent(cid)}/reply`, { text, suggestion }),
  settle: (id: string, cid: string, reopen = false) =>
    json<{ done: boolean }>(`/doc/${encodeURIComponent(id)}/comments/${encodeURIComponent(cid)}/settle`, { reopen }),
  /** 画像（base64）を、段落 after_para の下の新しい段落としてドキュメントに入れる。 */
  addImage: (id: string, afterPara: number, type: string, data: string) =>
    json<{ changed: boolean; para: number }>(`/doc/${encodeURIComponent(id)}/image`, { after_para: afterPara, type, data }),
  removeImage: (id: string, objectId: string) =>
    json<{ changed: boolean }>(`/doc/${encodeURIComponent(id)}/image/delete`, { id: objectId }),
  decide: (id: string, sid: string, accept: boolean) =>
    json<{ done: boolean }>(`/doc/${encodeURIComponent(id)}/suggestion`, { id: sid, accept }),
  /** 1文の音声（mp3）。まだ無ければ裏で作ってから返る（1文2秒ほど）。 */
  clip: async (u: SayUnit, voice: string): Promise<Blob> => {
    const q = new URLSearchParams({ t: u.speak, v: voice, g: u.gap });
    return (await send(`/clip/${u.key}.mp3?${q.toString()}`)).blob();
  },
};
