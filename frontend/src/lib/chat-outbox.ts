'use client';

/**
 * 会話で送った文の控え（送信の控え）。サーバーが「受け取った」と返すまで、送った文を端末（localStorage）に残す。
 *
 * 2026-11-21 本人「さっきサムネ修正で送ったメッセージが消えて作業も止まってるんだけど何で？」。送った瞬間に入力欄を
 * 空にし、文は画面の中（メモリ）にだけ持っていたので、届く前に通信が切れる（画面の入れ替えで 3000 が数秒止まる・Wi-Fi の
 * 切れ）か画面が読み直されると、文は消え、「ダンが作業中」の表示だけが残って何も動いていなかった。
 *
 * ここに控えた文は、届いた印（自分の発言がサーバーの行で返る・追い連絡として受け付けられた）で消す。届いたか分からない
 * まま通信が終わった時と、画面を開き直した時は、同じ送信 ID でサーバーに保存を聞き、保存されていなければ同じ ID で
 * 送り直す（サーバーは同じ ID を二度保存せず、ダンを二度起こさない）。複数のタブが同じ控えを同時に送り直さないよう、
 * 送り直す前に控えを「預かる」。
 *
 * 画面の読み直し（新しい版・成果物タブの版合わせ）は、控えがある間・会話の通信中・ダンの作業中・入力中は勝手に
 * 読み直さない。その印を <html data-dan-chat-busy> に出す（new-build-notice.tsx と lib/live-version/guard.ts が見る）。
 */

export type OutboxEntry = {
  id: string;
  room: string;
  content: string;
  image_urls?: string[];
  file_urls?: { name: string; url: string }[];
  reply_to_id?: string;
  timeline_refs?: { content_id: string; title: string; updated_at?: string }[];
  /** 端末の時計で、最初に送った時刻（ISO） */
  created_at: string;
  /** 送り直した回数 */
  tries: number;
  /** どれかのタブが送り直しを預かった時刻（ms）。この間はほかのタブは送らない */
  claimed_at?: number;
  claimed_by?: string;
};

const PREFIX = 'dan-chat-outbox:';
/** 送り直しを預かってから、ほかのタブが代われるまで */
export const CLAIM_MS = 20_000;
/** これより古い控えは自動では送らず、入力欄に戻す（何十分も後に勝手に届くと、本人の今の話とずれる） */
export const AUTO_RESEND_MS = 10 * 60_000;

const TAB = (() => {
  if (typeof window === 'undefined') return 'server';
  try {
    const k = 'dan-chat-outbox-tab';
    const v = sessionStorage.getItem(k) || Math.random().toString(36).slice(2, 10);
    sessionStorage.setItem(k, v);
    return v;
  } catch {
    return Math.random().toString(36).slice(2, 10);
  }
})();

const listeners = new Set<() => void>();
let version = 0;
function changed() {
  version += 1;
  listeners.forEach((f) => { try { f(); } catch { /* 片付けだけ */ } });
  syncBusyAttr();
}

export function subscribeOutbox(f: () => void): () => void {
  listeners.add(f);
  return () => { listeners.delete(f); };
}
export function outboxVersion(): number { return version; }

if (typeof window !== 'undefined') {
  // ほかのタブが控えを書き換えた
  window.addEventListener('storage', (e) => { if (!e.key || e.key.startsWith(PREFIX)) changed(); });
}

function read(room: string): OutboxEntry[] {
  if (typeof window === 'undefined' || !room) return [];
  try {
    const raw = localStorage.getItem(PREFIX + room);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x) => x && typeof x.id === 'string' && typeof x.content === 'string') : [];
  } catch {
    return [];
  }
}

function write(room: string, list: OutboxEntry[]) {
  if (typeof window === 'undefined' || !room) return;
  try {
    if (list.length) localStorage.setItem(PREFIX + room, JSON.stringify(list));
    else localStorage.removeItem(PREFIX + room);
  } catch {
    /* localStorage が使えなければ控えなしで動く（前と同じ） */
  }
  changed();
}

export function outboxList(room: string): OutboxEntry[] { return read(room); }

export function outboxHas(room: string, id: string): boolean { return read(room).some((e) => e.id === id); }

/** 送る直前に控える（同じ ID がもうあれば中身はそのまま）。 */
export function outboxPut(entry: Omit<OutboxEntry, 'tries' | 'created_at'> & { created_at?: string }) {
  const list = read(entry.room);
  if (list.some((e) => e.id === entry.id)) return;
  list.push({ ...entry, created_at: entry.created_at || new Date().toISOString(), tries: 0, claimed_at: Date.now(), claimed_by: TAB });
  write(entry.room, list);
}

/** 届いた（または本人が取り消した・入力欄に戻した）ので控えを消す。 */
export function outboxDrop(room: string, id: string) {
  const list = read(room);
  if (!list.some((e) => e.id === id)) return;
  write(room, list.filter((e) => e.id !== id));
}

/** 送り直しを預かる。ほかのタブが少し前に預かっていれば false。 */
export function outboxClaim(room: string, id: string): OutboxEntry | null {
  const list = read(room);
  const e = list.find((x) => x.id === id);
  if (!e) return null;
  if (e.claimed_at && e.claimed_by !== TAB && Date.now() - e.claimed_at < CLAIM_MS) return null;
  e.claimed_at = Date.now();
  e.claimed_by = TAB;
  e.tries = (e.tries || 0) + 1;
  write(room, list);
  return e;
}

/** 預かりを外す（通信が終わったのに届いたか分からない時。次の確かめでまた預かれる）。 */
export function outboxRelease(room: string, id: string) {
  const list = read(room);
  const e = list.find((x) => x.id === id);
  if (!e || e.claimed_by !== TAB) return;
  delete e.claimed_at;
  delete e.claimed_by;
  write(room, list);
}

function anyOutbox(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(PREFIX)) return true;
    }
  } catch { /* ignore */ }
  return false;
}

// ── 読み直してはいけない間の印 ──
const busy = new Set<string>();

/** 会話の欄が「今は読み直さないで」を出す・外す（入力中・通信中・ダンの作業中）。 */
export function setChatBusy(key: string, on: boolean) {
  const had = busy.has(key);
  if (on) busy.add(key); else busy.delete(key);
  if (had !== on) syncBusyAttr();
}

export function chatBusy(): boolean { return busy.size > 0 || anyOutbox(); }

function syncBusyAttr() {
  if (typeof document === 'undefined') return;
  const on = chatBusy();
  const el = document.documentElement;
  if (on) el.setAttribute('data-dan-chat-busy', [...busy].join(' ') || 'outbox');
  else el.removeAttribute('data-dan-chat-busy');
}
