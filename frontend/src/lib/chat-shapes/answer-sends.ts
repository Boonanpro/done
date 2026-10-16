/**
 * 部品（選択ボタン・入力欄）の答えの、まだ決着していない送信の置き場。
 *
 * 1回の答えの送信は1つの送信 ID（client_message_id＝保存される行の id）を持ち、保存された・保存されていないと
 * 分かるまで、送り直しはいつも同じ ID で行う（サーバーは同じ ID の2回目を保存し直さない）。その ID と状態を部品の
 * 中（React の state）だけに持つと、部屋を離れて戻った時（部品が作り直される）に消え、保存できたか分からない答えを
 * 別の ID で送り直せてしまう（VERIFY4 P1-1）。そこで、送信の状態を部品の外のこの置き場に、
 *   本人（利用者 ID）＋部屋＋AI の発言（返事の id）＋部品（部品の鍵）
 * ごとに持つ。部品はここを読み書きするだけで、作り直されても同じ送信を続ける。
 *
 * 寿命:
 * - 同じタブの中（部屋の移動・作り直し）: メモリに持つ。
 * - ページの読み直し・同じブラウザのほかのタブ: 決着していない状態（送信中・分からない・失敗）を localStorage にも
 *   書く（KEEP_MS＝7日。古い物と、数が MAX_ENTRIES を超えた分は古い順に消す）。ほかのタブが書いたら storage の知らせで
 *   取り込む。読み直す前のページが送っていた「送信中」は、その通信がもう無いので「確かめが要る」として扱う。
 * - 決着した（保存された）送信は localStorage から消す（メモリにだけ「保存済み」として残し、その行が部屋の記録に
 *   載ったら以後は記録が根拠）。
 * - 別のブラウザ・localStorage を消した・7日を過ぎた時は持っていない（新しい ID になる）。保存されていれば記録に
 *   載っているので、その部品は「答えました」になり押せない。
 *
 * 依存なし（node:test から読み込んで試験する）。
 */
import type { AnswerTo } from './answers';

export type AnswerSendStatus = 'sending' | 'unknown' | 'failed' | 'saved';

export type AnswerSend = {
  /** この答えの送信 ID（保存される行の id） */
  id: string;
  status: AnswerSendStatus;
  /** 画面に出す答えの値（選んだ選択肢・単位つきの入力値） */
  value: string;
  /** 部屋に送る文面と照合情報（送り直しに使う） */
  text: string;
  answerTo: AnswerTo;
  /** 入力欄に打った値（作り直した時に入力欄へ戻す） */
  raw?: string;
  /** この送信を始めたページ（同じページの「送信中」だけが本当に通信中） */
  page: string;
  /** この状態を決めた部品の表示の印（作り直された部品は別の印なので、押せるようにする前に確かめ直す） */
  seenBy?: string;
  /** 最後に変わった時刻（Date.now()） */
  at: number;
  /** 保存されたかをサーバーに聞いている間 */
  checking?: boolean;
  /** 聞き直しても分からなかった */
  again?: boolean;
  /** 保存済みなのにダンの処理が始まっていなかった送信を、同じ ID で送り直した（1回だけ） */
  kicked?: boolean;
  /** 保存された行が部屋の記録に一度載った（以後は記録が根拠。記録から消えたら取り消された） */
  seen?: boolean;
};

export const ANSWER_SENDS_STORAGE_KEY = 'dan.chatShapes.answerSends.v1';
export const KEEP_MS = 7 * 24 * 60 * 60 * 1000;
export const MAX_ENTRIES = 200;

/** このページ（読み込み）の印。 */
export const PAGE = typeof crypto !== 'undefined' && 'randomUUID' in crypto
  ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

/** 置き場の鍵: 本人＋部屋＋AI の発言＋部品 */
export function answerSendKey(ownerId: string, roomId: string, messageId: string, part: string): string {
  return `${ownerId}|${roomId}|${messageId}|${part}`;
}

/** 決着していない（localStorage にも残す）状態か */
const persistent = (s: AnswerSendStatus) => s === 'sending' || s === 'unknown' || s === 'failed';

/**
 * 作り直した部品が押せるようにする前に、サーバーに保存を確かめる必要があるか: 分からない・失敗（保存されて
 * いないと前に聞いたが、その後で前の通信が保存したかもしれない）・ほかのページの送信中（その通信はもう無い）。
 */
export function needsCheck(e: AnswerSend, page = PAGE): boolean {
  return e.status === 'unknown' || e.status === 'failed' || (e.status === 'sending' && e.page !== page);
}

type Storage = { getItem(k: string): string | null; setItem(k: string, v: string): void };

let entries = new Map<string, AnswerSend>();
const listeners = new Set<() => void>();
let storage: Storage | null = null;

function storageNow(): Storage | null {
  if (storage) return storage;
  try {
    if (typeof window !== 'undefined' && window.localStorage) storage = window.localStorage;
  } catch {
    storage = null;   // 使えない（プライベート窓など）: 同じタブの中だけで持つ
  }
  return storage;
}

function isAnswerSend(v: unknown): v is AnswerSend {
  if (!v || typeof v !== 'object') return false;
  const e = v as Record<string, unknown>;
  return typeof e.id === 'string' && typeof e.value === 'string' && typeof e.text === 'string' && typeof e.page === 'string'
    && typeof e.at === 'number' && (e.status === 'sending' || e.status === 'unknown' || e.status === 'failed')
    && !!e.answerTo && typeof e.answerTo === 'object';
}

function readStored(now = Date.now()): Map<string, AnswerSend> {
  const out = new Map<string, AnswerSend>();
  const st = storageNow();
  if (!st) return out;
  try {
    const raw = JSON.parse(st.getItem(ANSWER_SENDS_STORAGE_KEY) || '{}') as Record<string, unknown>;
    for (const [k, v] of Object.entries(raw || {})) {
      // 読み直した時に「聞いている途中」は残っていない（その問い合わせはもう無い）
      if (isAnswerSend(v) && now - v.at <= KEEP_MS) out.set(k, { ...v, checking: false });
    }
  } catch {
    // 壊れた中身は読まない
  }
  return out;
}

function writeStored(): void {
  const st = storageNow();
  if (!st) return;
  const keep = [...entries.entries()]
    .filter(([, e]) => persistent(e.status) && Date.now() - e.at <= KEEP_MS)
    .sort((a, b) => b[1].at - a[1].at)
    .slice(0, MAX_ENTRIES);
  try {
    st.setItem(ANSWER_SENDS_STORAGE_KEY, JSON.stringify(Object.fromEntries(keep.map(([k, e]) => [k, { ...e, checking: false }]))));
  } catch {
    // 書けない（容量など）: 同じタブの中では持ち続ける
  }
}

let loaded = false;
function ensureLoaded(): void {
  if (loaded) return;
  loaded = true;
  entries = readStored();
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (ev) => {
      if (ev.key !== ANSWER_SENDS_STORAGE_KEY) return;
      // ほかのタブの書き込み: 決着していない物はそちらの見え方に合わせる（このタブの保存済みの一時状態は残す）
      const theirs = readStored();
      const next = new Map<string, AnswerSend>();
      for (const [k, e] of entries) if (!persistent(e.status)) next.set(k, e);
      for (const [k, e] of theirs) {
        const mine = entries.get(k);
        next.set(k, mine && mine.at > e.at ? mine : e);
      }
      entries = next;
      listeners.forEach((l) => l());
    });
  }
}

export function getAnswerSend(key: string | null): AnswerSend | null {
  if (!key) return null;
  ensureLoaded();
  return entries.get(key) ?? null;
}

/** 置き場を書き換える（null で消す）。部品が作り直されていても、送信の結果はここに残る */
export function setAnswerSend(key: string, e: AnswerSend | null): void {
  ensureLoaded();
  if (e) entries.set(key, { ...e, at: Date.now() });
  else entries.delete(key);
  writeStored();
  listeners.forEach((l) => l());
}

export function subscribeAnswerSends(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** 試験用: 置き場と保存先を差し替えて最初から読む */
export function resetAnswerSendsForTest(next: Storage | null): void {
  storage = next;
  loaded = false;
  entries = new Map();
  ensureLoaded();
}
