// スマホのアプリ用の写し: frontend/src/lib/chat-shapes/answer-sends.ts と同じ中身（同じフォルダの読み込みの名前だけ違う）。
// frontend/scripts/sync-mobile-chat-shapes.mjs が作る。手で直さず、元を直して写し直す
// （tests/chat_shapes_program.test.mjs が同じ中身かを見る）。
/**
 * 部品（選択ボタン・入力欄）の答えの送信の置き場。
 *
 * 1回の答えの送信は1つの送信 ID（client_message_id＝保存される行の id）を持ち、送り直しはいつも同じ ID で行う
 * （サーバーは同じ ID の2回目を保存し直さない）。その ID と状態を部品の外のこの置き場に、
 *   本人（利用者 ID）＋部屋＋AI の発言（返事の id）＋部品（部品の鍵）
 * ごとに持つ。部品はここを読み書きするだけで、作り直されても（部屋を離れて戻る・ページを読み直す）同じ送信を続ける。
 *
 * 送信の状態は「前にしか進まない」（VERIFY5 P1-1）:
 * - 一度送信 ID を持った答えは、その ID の行が保存されたとこの表示が自分で確かめ（自分の記録に載る・同じ ID の
 *   照会）、その後で取り消されたと確かめるまで、新しい ID に移らない。新しい ID の送信は、取り消された前の ID を
 *   prev に持つ（ほかのタブはそれを見て、前の ID の続きだと分かる）。
 * - ほかのタブで項目が消えた・置き場が空になった・storage の知らせが来た、は「送っていない」の根拠にしない
 *   （取り込みは足すだけで消さない）。同じ ID なら保存済みは戻らない。違う ID は、こちらの続き（prev にこちらの ID が
 *   ある）の時だけ取り込む。関係の分からない ID には移らない。
 * - 共有する（localStorage に書く）のは、送信 ID と、確定した事実（保存済み／保存されていない、ダンの処理の開始）と、
 *   送り直しに要る中身だけ。「このタブで確かめた」「聞いている途中」「聞けなかった」のような表示ごとの印は、
 *   このタブのメモリにだけ持つ（here・confirmedHere など）。
 * - 「保存済み」と「ダンの処理が始まった」は別の状態（start）。保存済みでも始まったと確かでない答えは、サーバーの
 *   開始の状態に合わせて確かめ続け、始まっていないと分かった時だけ同じ ID で送り直す（サーバーは送信 ID ごとに1回
 *   しか始めないので、二重には始まらない）。
 *
 * サーバーに聞く（照会）のは、部品が描かれた時（決着していない送信がある時）・自分の送信が終わった後・「確かめる」を
 * 押した時・開始を確かめている間の間隔（START_CHECK_DELAYS）だけ。storage の取り込みでは聞かない。このタブでは、
 * 同じ答えの照会は同時に1つ（checks）。
 *
 * 寿命: 同じタブはメモリ。ページの読み直し・同じブラウザのほかのタブには localStorage（KEEP_MS＝最後に変わってから
 * 7日、新しい方から MAX_ENTRIES 件）。それを過ぎた物・別のブラウザ・localStorage を消した時は持っていない（その時は
 * 部屋の記録が根拠。記録にあれば「答えました」、無ければ新しい ID）。
 *
 * 依存なし（node:test から読み込んで試験する）。
 */
import type { AnswerTo } from './chat-shapes-answers';

export type AnswerSendStatus = 'sending' | 'unknown' | 'failed' | 'saved';

/** 保存済みの答えのダンの処理: pending（始まったと確かでない）/ started（始まった）/ unknowable（サーバーが知らない。始めない） */
export type AnswerStart = 'pending' | 'started' | 'unknowable';

/** サーバーが答えた開始の状態 */
export type StartReply = 'started' | 'not_started' | 'starting' | 'unknown';

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
  /** この送信を始めたページ（同じページの、通信中の送信だけが本当に「送信中」） */
  page: string;
  /** 最後に変わった時刻（Date.now()） */
  at: number;
  /** 保存済みの時の、ダンの処理の開始 */
  start?: AnswerStart;
  /** この送信の前に同じ部品へ送って、保存され、取り消された送信 ID（新しい順） */
  prev?: string[];
};

/** サーバーの「保存されたか」の答え（started: true/false/null、start: サーバーの権利の状態） */
export type SavedReply = { saved: boolean; started?: boolean | null; start?: string | null };
/** その送信 ID の保存を聞く。聞けなければ reject */
export type AskSaved = (id: string) => Promise<SavedReply>;
/**
 * 部屋に答えを送る。保存されたら resolve（echo が無く確かめて分かった時は started/start も）。保存されていないと
 * サーバーが答えたら reject、分からなければ reject(Error(SEND_UNKNOWN))、ほかの送信の通信中で今は送らなかったら
 * reject(Error(SEND_BUSY))（background の時だけ）。onEnded はその送信の通信が終わった時に1回（startSeen: その通信の
 * 中でダンの処理が始まった印＝追い連絡を入れた・返事が来た、を見た）。
 */
export type SubmitAnswer = (
  text: string, answerTo: AnswerTo, id: string,
  opts?: { onEnded?: (startSeen: boolean) => void; background?: boolean },
) => Promise<{ id: string; started?: boolean | null; start?: string | null }>;

export const SEND_UNKNOWN = 'unknown';
export const SEND_BUSY = 'busy';

export const ANSWER_SENDS_STORAGE_KEY = 'dan.chatShapes.answerSends.v1';
export const KEEP_MS = 7 * 24 * 60 * 60 * 1000;
export const MAX_ENTRIES = 200;
const MAX_PREV = 10;
/** 開始を確かめる間隔（サーバーで誰かが始めようとしている／聞けなかった時。使い切ったら止めて「確かめる」を出す） */
export const START_CHECK_DELAYS = [1000, 2000, 4000, 8000, 16000, 32000, 64000];
/** 始まっていないと分かった時に同じ ID で送り直すまでの間（回数もこの数まで） */
export const KICK_DELAYS = [0, 2000, 8000];
/** ほかのページの「送信中」が、この間変わらなければ、その通信はもう無いとみなす（聞かずに「確かめる」を出す） */
export const STALE_SENDING_MS = 30000;

/** このページ（読み込み）の印。 */
export const PAGE = typeof crypto !== 'undefined' && 'randomUUID' in crypto
  ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

/** 置き場の鍵: 本人＋部屋＋AI の発言＋部品 */
export function answerSendKey(ownerId: string, roomId: string, messageId: string, part: string): string {
  return `${ownerId}|${roomId}|${messageId}|${part}`;
}

/** サーバーの答えから開始の状態を読む。fromSaved: 「保存されたか」の口の答え（started が無ければ古い Core＝送り直さない） */
export function startReplyOf(r: { started?: boolean | null; start?: string | null } | null | undefined, fromSaved: boolean): StartReply | null {
  if (!r || r.started === undefined) return fromSaved ? 'unknown' : null;
  if (r.started === true) return 'started';
  if (r.started === false) return 'not_started';
  return r.start === 'unknown' ? 'unknown' : 'starting';
}

// --- 共有する状態（メモリ＋localStorage） ------------------------------------------------------

type Storage = { getItem(k: string): string | null; setItem(k: string, v: string): void };

let entries = new Map<string, AnswerSend>();
let storage: Storage | null = null;
const listeners = new Set<() => void>();
const versions = new Map<string, number>();
let version = 0;

function bump(key: string): void {
  version += 1;
  versions.set(key, version);
}

function notify(): void {
  listeners.forEach((l) => l());
}

function storageNow(): Storage | null {
  if (storage) return storage;
  try {
    if (typeof window !== 'undefined' && window.localStorage) storage = window.localStorage;
  } catch {
    storage = null;   // 使えない（プライベート窓など）: 同じタブの中だけで持つ
  }
  return storage;
}

const STATUSES: AnswerSendStatus[] = ['sending', 'unknown', 'failed', 'saved'];
const STARTS: AnswerStart[] = ['pending', 'started', 'unknowable'];

/** 保存先から読んだ1件（形の違う物・知らない印は捨てる） */
function cleanSend(v: unknown): AnswerSend | null {
  if (!v || typeof v !== 'object') return null;
  const e = v as Record<string, unknown>;
  if (typeof e.id !== 'string' || typeof e.value !== 'string' || typeof e.text !== 'string' || typeof e.page !== 'string'
    || typeof e.at !== 'number' || !STATUSES.includes(e.status as AnswerSendStatus) || !e.answerTo || typeof e.answerTo !== 'object') return null;
  const out: AnswerSend = { id: e.id, status: e.status as AnswerSendStatus, value: e.value, text: e.text, answerTo: e.answerTo as AnswerTo, page: e.page, at: e.at };
  if (typeof e.raw === 'string') out.raw = e.raw;
  if (out.status === 'saved' && STARTS.includes(e.start as AnswerStart)) out.start = e.start as AnswerStart;
  if (Array.isArray(e.prev)) {
    const prev = e.prev.filter((x): x is string => typeof x === 'string').slice(0, MAX_PREV);
    if (prev.length) out.prev = prev;
  }
  return out;
}

function readStored(now = Date.now()): Map<string, AnswerSend> {
  const out = new Map<string, AnswerSend>();
  const st = storageNow();
  if (!st) return out;
  try {
    const raw = JSON.parse(st.getItem(ANSWER_SENDS_STORAGE_KEY) || '{}') as Record<string, unknown>;
    for (const [k, v] of Object.entries(raw || {})) {
      const e = cleanSend(v);
      if (e && now - e.at <= KEEP_MS) out.set(k, e);
    }
  } catch {
    // 壊れた中身は読まない
  }
  return out;
}

const START_RANK: Record<string, number> = { pending: 1, unknowable: 2, started: 3 };
const startRank = (s?: AnswerStart) => (s ? START_RANK[s] : 0);

function sameSend(a: AnswerSend, b: AnswerSend): boolean {
  return a.id === b.id && a.status === b.status && a.value === b.value && a.text === b.text && a.raw === b.raw && a.page === b.page
    && a.at === b.at && a.start === b.start && (a.prev ?? []).join(',') === (b.prev ?? []).join(',')
    && JSON.stringify(a.answerTo) === JSON.stringify(b.answerTo);
}

/**
 * 同じ答えの2つの見え方を1つにする（mine＝このタブ、theirs＝保存先・ほかのタブ）。前にしか進まない:
 * - 違う送信 ID: theirs がこちらの続き（theirs.prev にこちらの ID）の時だけ theirs。それ以外（こちらが新しい・関係が
 *   分からない）はこちらのまま（確かめていない別の ID には移らない）
 * - 同じ送信 ID: 保存済みは戻らない（どちらかが保存済みなら保存済み）。開始は started が最後。保存されていない同士は
 *   新しく変わった方
 * - 片方しか無い: ある方（無いことは「送っていない」の根拠にしない）
 * 何も変わらない時はこちらの物をそのまま返す。
 */
export function mergeAnswerSend(mine: AnswerSend | undefined, theirs: AnswerSend | undefined): AnswerSend | undefined {
  if (!mine) return theirs;
  if (!theirs) return mine;
  if (mine.id !== theirs.id) return (theirs.prev ?? []).includes(mine.id) ? theirs : mine;
  const saved = mine.status === 'saved' ? mine : theirs.status === 'saved' ? theirs : null;
  const base = saved ?? (theirs.at > mine.at ? theirs : mine);
  const out: AnswerSend = { ...base };
  if (saved) {
    const start = startRank(mine.start) >= startRank(theirs.start) ? mine.start : theirs.start;
    if (start) out.start = start; else delete out.start;
  } else delete out.start;
  const prev = (mine.prev?.length ?? 0) >= (theirs.prev?.length ?? 0) ? mine.prev : theirs.prev;
  if (prev?.length) out.prev = prev; else delete out.prev;
  return sameSend(out, mine) ? mine : out;
}

/** 保存先・ほかのタブの見え方を取り込む（足すだけ。このタブが送っている間のその送信は、その結果を待つ） */
function absorb(theirs: Map<string, AnswerSend>): boolean {
  let changed = false;
  for (const [k, t] of theirs) {
    const m = entries.get(k);
    let next = mergeAnswerSend(m, t)!;
    if (m && here.get(k)?.sending && next.id === m.id && next.status !== 'saved') next = m;
    if (next !== m) {
      entries.set(k, next);
      bump(k);
      changed = true;
    }
  }
  return changed;
}

function writeStored(): void {
  const st = storageNow();
  if (!st) return;
  absorb(readStored());   // ほかのタブがまだ知らせていない書き込みを、上書きで消さない
  const now = Date.now();
  const keep = [...entries.entries()]
    .filter(([, e]) => now - e.at <= KEEP_MS)
    .sort((a, b) => b[1].at - a[1].at)
    .slice(0, MAX_ENTRIES);
  try {
    st.setItem(ANSWER_SENDS_STORAGE_KEY, JSON.stringify(Object.fromEntries(keep)));
  } catch {
    // 書けない（容量など）: 同じタブの中では持ち続ける
  }
}

let loaded = false;
function onStorage(ev: { key: string | null }): void {
  if (ev.key !== ANSWER_SENDS_STORAGE_KEY && ev.key !== null) return;
  // ほかのタブの書き込み: 取り込むだけ（消えた物は消さない・ここからは聞かない）
  if (absorb(readStored())) notify();
}

function ensureLoaded(): void {
  if (loaded) return;
  loaded = true;
  entries = readStored();
  for (const k of entries.keys()) bump(k);
  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') window.addEventListener('storage', onStorage);
}

export function getAnswerSend(key: string | null): AnswerSend | null {
  if (!key) return null;
  ensureLoaded();
  return entries.get(key) ?? null;
}

/** 置き場を書き換える（同じ答えの今の見え方と mergeAnswerSend で合わせる＝保存済みは戻らない）。部品が作り直されていても、送信の結果はここに残る */
export function setAnswerSend(key: string, e: AnswerSend): void {
  ensureLoaded();
  const clean = cleanSend({ ...e, at: Date.now() });   // 置き場に入るのは送信 ID・事実・送り直しの中身だけ（表示ごとの印は入らない）
  if (!clean) return;
  const cur = entries.get(key);
  const next = cur && cur.id !== clean.id && !(clean.prev ?? []).includes(cur.id) ? cur : mergeAnswerSend(clean, cur)!;
  if (next !== cur) {
    entries.set(key, next);
    bump(key);
  }
  writeStored();
  notify();
}

export function subscribeAnswerSends(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** その答えの見え方が変わるたびに変わる数（useSyncExternalStore の snapshot） */
export function answerSendVersion(key: string | null): number {
  if (!key) return 0;
  ensureLoaded();
  return versions.get(key) ?? 0;
}

// --- このタブだけの印 -----------------------------------------------------------------------

type Here = {
  /** このタブがこの答えを送っている（通信中） */
  sending?: boolean;
  /** このタブがこの答えの保存を聞いている */
  checking?: boolean;
  /** このタブで最後に聞いて分からなかった送信 ID */
  unsure?: string;
  /** 開始の確かめ: 聞いた回数・送り直した回数・次の確かめ・使い切った送信 ID */
  tries: number;
  kicks: number;
  timer?: ReturnType<typeof setTimeout>;
  gaveUp?: string;
};

const here = new Map<string, Here>();
/** このタブが保存を確かめた送信 ID（自分の送信の保存・自分の照会・自分の記録） */
const confirmedHere = new Set<string>();
/** このタブの部屋の記録に載った送信 ID */
const seenHere = new Set<string>();
/** このタブが、保存済みの行がもう無いと照会で確かめた送信 ID（取り消し） */
const goneHere = new Set<string>();
/** この答えを描いている部品の数（0 になったら開始の確かめは止め、次に描かれた時に続ける） */
const mounted = new Map<string, number>();
/** 最後に描いた部品の送り先 */
const io = new Map<string, { ask: AskSaved | null; submit: SubmitAnswer | null }>();
/** このタブで今聞いている照会（同じ答えは同時に1つ） */
const checks = new Map<string, Promise<void>>();

function hereOf(key: string): Here {
  let h = here.get(key);
  if (!h) {
    h = { tries: 0, kicks: 0 };
    here.set(key, h);
  }
  return h;
}

function touch(key: string): void {
  bump(key);
  notify();
}

/** 画面に出すこのタブの印（読むだけ） */
export function answerSendHere(key: string | null): { sending: boolean; checking: boolean; unsure: string | null; gaveUp: string | null } {
  const h = key ? here.get(key) : undefined;
  return { sending: !!h?.sending, checking: !!h?.checking, unsure: h?.unsure ?? null, gaveUp: h?.gaveUp ?? null };
}

/** その送信の行がこのタブの部屋の記録に載った（以後この ID はこのタブで保存を確かめ済み） */
export function noteInRecord(id: string): void {
  confirmedHere.add(id);
  seenHere.add(id);
}

/** 保存済みの答えが取り消された（このタブで保存を確かめた後、記録から消えた／照会で無いと分かった） */
export function isGone(e: AnswerSend, inRecord: boolean): boolean {
  return e.status === 'saved' && !inRecord && (seenHere.has(e.id) || goneHere.has(e.id));
}

/**
 * 部品が描かれた時、押せるようにする前（または答えを出す前）にこのタブで確かめが要るか:
 * 分からない・失敗（その後で前の通信が保存したかもしれない）・このタブが送っていない「送信中」（読み直す前のページ・
 * ほかのタブ）、保存済みだがこのタブではまだ確かめていない（記録に無い。取り消されたかもしれない）、
 * 保存済みだがダンの処理が始まったと確かでない。
 */
export function needsCheck(e: AnswerSend, inRecord = false, sendingHere = false): boolean {
  if (e.status === 'unknown' || e.status === 'failed') return true;
  if (e.status === 'sending') return !sendingHere;
  return (!inRecord && !confirmedHere.has(e.id) && !goneHere.has(e.id)) || e.start === 'pending';
}

/** 押せるようにする前の確かめ（needsCheck のうち、押せるかどうかに関わる物） */
export function mustCheckBeforePress(e: AnswerSend, sendingHere = false): boolean {
  return e.status === 'unknown' || e.status === 'failed' || (e.status === 'sending' && !sendingHere);
}

/** 部品がこの答えを描いている間、送り先を結び付ける。戻り値で外す */
export function attachAnswerSend(key: string, ports: { ask: AskSaved | null; submit: SubmitAnswer | null }): () => void {
  io.set(key, ports);
  mounted.set(key, (mounted.get(key) ?? 0) + 1);
  return () => {
    const n = (mounted.get(key) ?? 1) - 1;
    if (n > 0) mounted.set(key, n);
    else {
      mounted.delete(key);
      const h = here.get(key);
      if (h?.timer) { clearTimeout(h.timer); h.timer = undefined; }
    }
  };
}

function setStart(key: string, start: AnswerStart): void {
  const cur = entries.get(key);
  if (!cur || cur.status !== 'saved') return;
  if (start === 'started' || start === 'unknowable') {
    const h = hereOf(key);
    if (h.timer) { clearTimeout(h.timer); h.timer = undefined; }
    h.gaveUp = undefined;
  }
  setAnswerSend(key, { ...cur, start });
}

/** 開始の確かめを、間隔をあけて続ける（使い切ったら止めて「確かめる」を出す） */
function scheduleStartCheck(key: string): void {
  const h = hereOf(key);
  const cur = entries.get(key);
  if (!cur || cur.status !== 'saved' || cur.start !== 'pending') return;
  if (h.timer) clearTimeout(h.timer);
  h.timer = undefined;
  if (h.tries >= START_CHECK_DELAYS.length) {
    h.gaveUp = cur.id;
    touch(key);
    return;
  }
  const delay = START_CHECK_DELAYS[h.tries];
  h.tries += 1;
  h.timer = setTimeout(() => {
    h.timer = undefined;
    if (mounted.get(key)) void checkAnswerSend(key);
  }, delay);
}

/** 保存済みの答えについてサーバーが答えた開始の状態に合わせる */
function onStartReply(key: string, reply: StartReply | null): void {
  const cur = entries.get(key);
  if (!cur || cur.status !== 'saved' || cur.start === 'started' || cur.start === 'unknowable') return;
  if (reply === 'started') setStart(key, 'started');
  else if (reply === 'unknown') setStart(key, 'unknowable');
  else if (reply === 'not_started') kick(key);
  else scheduleStartCheck(key);   // 誰かが始めようとしている・聞けなかった: 間をあけてまた聞く
}

/** 保存済みなのにダンの処理が始まっていない答えを、同じ ID でもう一度送る（サーバーはそれで始める。1回しか始まらない） */
function kick(key: string): void {
  const h = hereOf(key);
  const cur = entries.get(key);
  if (!cur || h.sending) return;
  if (h.timer) clearTimeout(h.timer);
  h.timer = undefined;
  if (h.kicks >= KICK_DELAYS.length) {
    h.gaveUp = cur.id;
    touch(key);
    return;
  }
  const delay = KICK_DELAYS[h.kicks];
  h.kicks += 1;
  const go = () => {
    h.timer = undefined;
    const e = entries.get(key);
    const ports = io.get(key);
    if (!mounted.get(key) || !e || e.id !== cur.id || e.status !== 'saved' || e.start !== 'pending' || !ports?.submit) return;
    transmit(key, e, ports.submit, true);
  };
  if (delay <= 0) go();
  else h.timer = setTimeout(go, delay);
}

/**
 * 送る（初めて・送り直し・始まっていない答えの送り直し）。結果は置き場に書く（部品が作り直されていても残る）。
 * 通信が終わったら、保存されていればダンの処理の開始を確かめる。
 */
function transmit(key: string, e: AnswerSend, submit: SubmitAnswer, background: boolean): void {
  const h = hereOf(key);
  h.sending = true;
  h.unsure = undefined;
  touch(key);
  // 開始の確かめは、通信が終わり（onEnded）、送信の結果も決まった（finally）後に1回だけ
  let ended: boolean | null = null;
  let outcome: 'saved' | 'other' | null = null;
  let reply: StartReply | null = null;
  let settled = false;
  let finished = false;
  const finish = () => {
    if (ended === null || !settled || finished) return;
    finished = true;
    const cur = entries.get(key);
    if (outcome !== 'saved' || !cur || cur.id !== e.id || cur.status !== 'saved') return;
    if (ended) setStart(key, 'started');                  // 通信の中でダンの処理が始まった印を見た
    else if (reply) onStartReply(key, reply);              // echo が無く「保存されたか」で分かった開始の状態
    else if (!checks.has(key)) void checkAnswerSend(key);  // echo だけ: 始まったかを聞く
  };
  submit(e.text, e.answerTo, e.id, { background, onEnded: (startSeen) => { ended = startSeen; finish(); } })
    .then((r) => {
      // 置き場の鍵の送信 ID は送った ID のまま（サーバーは UUID の形の送信 ID をそのまま行の id にする）
      confirmedHere.add(e.id);
      confirmedHere.add(r.id);
      reply = startReplyOf(r, false);
      const cur = entries.get(key);
      const base = cur && cur.id === e.id ? cur : e;
      setAnswerSend(key, { ...base, status: 'saved', start: base.start === 'started' || base.start === 'unknowable' ? base.start : 'pending' });
      outcome = 'saved';
    })
    .catch((err: unknown) => {
      const why = err instanceof Error ? err.message : '';
      const cur = entries.get(key);
      outcome = 'other';
      if (background) {
        // 始まっていない答えの送り直しが届かなかった: 答えは保存済み。間をあけて開始をまた確かめる
        if (cur && cur.id === e.id && cur.status === 'saved') scheduleStartCheck(key);
        return;
      }
      if (cur && cur.id === e.id) setAnswerSend(key, { ...cur, status: why === SEND_UNKNOWN ? 'unknown' : 'failed' });
    })
    .finally(() => {
      h.sending = false;
      settled = true;
      touch(key);
      finish();
    });
}

/** 部品から答えを送る（id は呼ぶ側が決める: 続きは同じ ID、取り消しの後は新しい ID と prev） */
export function sendAnswer(key: string, e: Omit<AnswerSend, 'status' | 'at'>): void {
  const ports = io.get(key);
  if (!ports?.submit) return;
  const h = hereOf(key);
  h.tries = 0;
  h.kicks = 0;
  h.gaveUp = undefined;
  const entry: AnswerSend = { ...e, status: 'sending', at: 0 };
  setAnswerSend(key, entry);
  transmit(key, entry, ports.submit, false);
}

/**
 * その答えの送信 ID の保存をサーバーに聞いて、置き場を決める: 保存済み（ダンの処理の開始も合わせる）／保存されて
 * いない＝失敗（同じ ID で送り直せる。保存済みだった物なら取り消された）／聞けない＝分からない（押せない）。
 * このタブで同じ答えを聞いている途中なら、その答えを待つ。
 */
export function checkAnswerSend(key: string): Promise<void> {
  const running = checks.get(key);
  if (running) return running;
  ensureLoaded();
  const e = entries.get(key);
  if (!e) return Promise.resolve();
  const h = hereOf(key);
  const ask = io.get(key)?.ask ?? null;
  if (!ask) {
    h.unsure = e.id;
    if (e.status !== 'saved' && e.status !== 'unknown') setAnswerSend(key, { ...e, status: 'unknown' });
    else touch(key);
    return Promise.resolve();
  }
  h.checking = true;
  touch(key);
  const p = ask(e.id)
    .then((r) => {
      const cur = entries.get(key);
      if (!cur || cur.id !== e.id) return;
      h.unsure = undefined;
      if (r.saved) {
        confirmedHere.add(e.id);
        goneHere.delete(e.id);
        setAnswerSend(key, { ...cur, status: 'saved', start: cur.start === 'started' || cur.start === 'unknowable' ? cur.start : 'pending' });
        onStartReply(key, startReplyOf(r, true));
      } else if (cur.status === 'saved') {
        goneHere.add(e.id);   // 保存されていた行がもう無い（取り消された）
      } else {
        setAnswerSend(key, { ...cur, status: 'failed' });
      }
    }, () => {
      const cur = entries.get(key);
      if (!cur || cur.id !== e.id) return;
      h.unsure = e.id;
      if (cur.status === 'saved') {
        if (cur.start === 'pending') scheduleStartCheck(key);   // 聞けなかった: 間をあけてまた聞く
      } else if (cur.status !== 'unknown') {
        setAnswerSend(key, { ...cur, status: 'unknown' });
      }
    })
    .finally(() => {
      checks.delete(key);
      h.checking = false;
      touch(key);
    });
  checks.set(key, p);
  return p;
}

/** 部品が描かれた時の確かめ（開始の確かめを使い切っていたら、もう一度最初から） */
export function resumeAnswerSend(key: string): Promise<void> {
  const h = hereOf(key);
  if (h.gaveUp) {
    h.gaveUp = undefined;
    h.tries = 0;
    h.kicks = 0;
  }
  if (h.timer) return checks.get(key) ?? Promise.resolve();   // 開始の確かめが続いている
  return checkAnswerSend(key);
}

/** 「確かめる」を押した */
export function recheckAnswerSend(key: string): Promise<void> {
  const h = hereOf(key);
  if (h.timer) { clearTimeout(h.timer); h.timer = undefined; }
  h.gaveUp = undefined;
  h.tries = 0;
  h.kicks = 0;
  return checkAnswerSend(key);
}

/** 試験用: 置き場と保存先を差し替えて最初から読む（ページの読み直し。このタブの印も消える） */
export function resetAnswerSendsForTest(next: Storage | null): void {
  for (const h of here.values()) if (h.timer) clearTimeout(h.timer);
  storage = next;
  loaded = false;
  entries = new Map();
  here.clear();
  confirmedHere.clear();
  seenHere.clear();
  goneHere.clear();
  mounted.clear();
  io.clear();
  checks.clear();
  if (typeof window !== 'undefined' && typeof window.removeEventListener === 'function') window.removeEventListener('storage', onStorage);
  ensureLoaded();
}

/** 試験用: ほかのタブの書き込みの知らせ（storage イベント）を受けたことにする */
export function storageEventForTest(): void {
  onStorage({ key: ANSWER_SENDS_STORAGE_KEY });
}
