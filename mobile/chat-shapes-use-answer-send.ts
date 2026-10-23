// スマホのアプリ用の写し: frontend/src/lib/chat-shapes/use-answer-send.ts と同じ中身（同じフォルダの読み込みの名前だけ違う）。
// frontend/scripts/sync-mobile-chat-shapes.mjs が作る。手で直さず、元を直して写し直す
// （tests/chat_shapes_program.test.mjs が同じ中身かを見る）。
/**
 * 部品（選択ボタン・入力欄）の答えの送信の状態を、画面の部品に渡す形にする React の決まり（useAnswerSend）と、画面に出す文。
 * PC（components/chat/chat-shapes.tsx）とスマホ（mobile/chat-shapes.tsx。写しは mobile/chat-shapes-use-answer-send.ts）が
 * 同じ物を使う（2026-10-23。スマホは送れなかった時に「送っています…」で固まっていた）。写しは
 * frontend/scripts/sync-mobile-chat-shapes.mjs が作り、tests/chat_shapes_program.test.mjs が同じ中身か見る。
 * 置き場（answer-sends.ts）と同じく DOM には依存しない（React の useState・useEffect・useSyncExternalStore だけ）。
 */
import { useEffect, useState, useSyncExternalStore } from 'react';

import { ANSWER_VALUE_MAX } from './chat-shapes-schema';
import type { AnswerTo, UserUtterance } from './chat-shapes-answers';
import {
  PAGE, STALE_SENDING_MS, answerSendHere, answerSendKey, answerSendVersion, attachAnswerSend, getAnswerSend,
  isGone, mustCheckBeforePress, needsCheck, noteInRecord, recheckAnswerSend, resumeAnswerSend, sendAnswer, subscribeAnswerSends,
  type AskSaved, type SubmitAnswer,
} from './chat-shapes-answer-sends';

/** 1つの答えの部品が置かれた所: 部屋の本人の発言・送る先・聞き直す先・本人・部屋・返事の id・部品の鍵 */
export type AnswerEnv = {
  utterances: UserUtterance[];
  submit: SubmitAnswer | null;
  askSaved: AskSaved | null;
  ownerId: string | null;
  roomId: string | null;
  messageId: string | null;
  part: string;
};

export const SEND_FAILED = '送れませんでした。もう一度押してください';
export const SEND_UNKNOWN_TEXT = '送れたか確かめられませんでした';
export const SEND_UNKNOWN_AGAIN = 'まだ確かめられません。通信が戻ってからもう一度押してください';
export const SEND_VERIFYING = '前に送った答えが届いたか確かめています…';
export const START_UNSURE = '答えは届きましたが、ダンが読み始めたか確かめられませんでした';
export const TOO_LONG = `長すぎます（単位を含めて${ANSWER_VALUE_MAX}文字まで）`;
export const SENDING_TEXT = '送っています…';
export const CHECKING_TEXT = '確かめています…';
export const CHECK_BUTTON = '確かめる';

/** 新しい送信 ID（保存される行の id。サーバーは UUID の形の時だけそのまま使う） */
export function newSendId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  const h = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`;
}

/** 答えられる条件: 送る先がある・本人と部屋が分かる・保存された返事・閉じまで届いた・ライブ枠でない・生成中でない・まだ答えていない */
export function canAnswer(env: AnswerEnv, o: { complete: boolean; live: boolean; streaming: boolean; answered: boolean }): boolean {
  return !!env.submit && !!env.ownerId && !!env.roomId && !!env.messageId && o.complete && !o.live && !o.streaming && !o.answered;
}

/**
 * 送信の状態（画面に出す形）: 押していない / 送信中 / 保存された（置き場の事実。行がこのタブの記録に載っていない間は
 * 置き場の答えを出す） / 失敗（保存されていない。選び直せる。送り直しも同じ id） / 保存できたか分からない（その id の
 * 保存を聞き直す。verifying は作り直された部品が押せるようにする前の確かめ）。
 * id はこの答えの送信 ID（保存されたと分かるまで変えない）。長すぎて送らなかった失敗は前の送信の id を持つ
 */
export type SendState =
  | { status: 'idle' }
  | { status: 'sending'; value: string; id: string }
  | { status: 'saved'; value: string; id: string }
  | { status: 'failed'; value: string; id?: string; reason?: string }
  | { status: 'unknown'; value: string; id: string; checking?: boolean; again?: boolean; verifying?: boolean };

/**
 * 答えの送信と「答えた」の判定。
 * - recorded: 部屋の記録（照合情報つきの保存済み発言）にあるこの部品への答え。これが根拠
 * - 送信の状態は置き場（answer-sends.ts）にある。保存済みの行がまだ記録に載っていない間は、置き場の答えを出す。
 *   このタブの記録に一度載った後で消えた・照会で無いと分かった（取り消し）時だけ、押し直せる（新しい ID）
 * - 部品が描かれた時に1回、決着していない送信があればその ID の保存をサーバーに確かめる（押せるようにする前の確かめは
 *   この時だけ。ほかのタブからの取り込みでは聞かない）。確かめが済むまでと、分からない間は押せない
 */
export function useAnswerSend(env: AnswerEnv, recorded: string | null) {
  const { utterances, submit, askSaved, ownerId, roomId, messageId, part } = env;
  const key = ownerId && roomId && messageId ? answerSendKey(ownerId, roomId, messageId, part) : null;
  useSyncExternalStore(subscribeAnswerSends, () => answerSendVersion(key), () => 0);
  const entry = getAnswerSend(key);
  const h = answerSendHere(key);
  // 長すぎて送らなかった値（送っていないので置き場は変えない）
  const [tooLong, setTooLong] = useState<string | null>(null);
  const inRecord = !!entry && utterances.some((u) => u.id === entry.id);
  const gone = !!entry && isGone(entry, inRecord);
  // この部品が描いている間、送り先を置き場に結び付ける（開始の確かめはその間だけ続く）
  useEffect(() => (key ? attachAnswerSend(key, { ask: askSaved, submit }) : undefined), [key, askSaved, submit]);
  useEffect(() => {
    if (entry && inRecord) noteInRecord(entry.id);   // このタブの記録に載った: このタブで保存を確かめた
  }, [entry, inRecord]);
  // 描かれた時に1回だけ確かめる（取り込みで変わっても聞き直さない）
  const [mountChecked, setMountChecked] = useState(false);
  useEffect(() => {
    if (!key) return undefined;
    let alive = true;
    const e = getAnswerSend(key);
    if (e && needsCheck(e, utterances.some((u) => u.id === e.id), answerSendHere(key).sending)) {
      void resumeAnswerSend(key).finally(() => { if (alive) setMountChecked(true); });
    } else setMountChecked(true);
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  // ほかのタブ・前のページの「送信中」が長く変わらない: その通信はもう無いとみなして「確かめる」を出す（聞きはしない）
  const [, setTick] = useState(0);
  const otherSending = !!entry && entry.status === 'sending' && !h.sending;
  const staleIn = otherSending ? STALE_SENDING_MS - (Date.now() - entry.at) : 0;
  useEffect(() => {
    if (!otherSending || staleIn <= 0) return undefined;
    const t = setTimeout(() => setTick((x) => x + 1), staleIn + 50);
    return () => clearTimeout(t);
  }, [otherSending, staleIn]);
  const verifying = !mountChecked && !!entry && !gone && mustCheckBeforePress(entry, h.sending);
  const answer = recorded ?? (entry && entry.status === 'saved' && !gone && !inRecord ? entry.value : null);
  let send: SendState;
  if (tooLong !== null) send = { status: 'failed', value: tooLong, reason: 'too long', id: entry?.id };
  else if (!entry || gone) send = { status: 'idle' };
  else if (entry.status === 'saved') send = { status: 'saved', value: entry.value, id: entry.id };
  else if (verifying || h.checking) send = { status: 'unknown', value: entry.value, id: entry.id, checking: true, verifying };
  else if (entry.status === 'sending' && (h.sending || staleIn > 0)) send = { status: 'sending', value: entry.value, id: entry.id };
  else if (entry.status === 'sending' || entry.status === 'unknown') send = { status: 'unknown', value: entry.value, id: entry.id, again: h.unsure === entry.id };
  else send = { status: 'failed', value: entry.value, id: entry.id };
  const run = (text: string, answerTo: AnswerTo, value: string, raw?: string) => {
    if (!submit || !key) return;
    const prev = getAnswerSend(key);
    // 保存されたと分かっていない送信の続きは同じ送信 ID（二重に保存されない）。新しい ID は、初めて（置き場に無い）か、
    // この表示が保存を確かめた後で取り消されたと確かめた時だけ（前の ID を prev に持つ）
    let id: string;
    let prevIds: string[] | undefined;
    if (!prev) id = newSendId();
    else if (prev.status === 'saved') {
      if (!isGone(prev, utterances.some((u) => u.id === prev.id))) return;
      id = newSendId();
      prevIds = [prev.id, ...(prev.prev ?? [])].slice(0, 10);
    } else {
      id = prev.id;
      prevIds = prev.prev;
    }
    setTooLong(null);
    sendAnswer(key, { id, value, text, answerTo, raw, page: PAGE, ...(prevIds ? { prev: prevIds } : {}) });
  };
  // 保存できたか分からない時・ダンが読み始めたか分からない時の「確かめる」
  const recheck = () => {
    if (key && entry && !h.checking) void recheckAnswerSend(key);
  };
  const startUnsure = !!entry && entry.status === 'saved' && entry.start === 'pending' && h.gaveUp === entry.id && !gone;
  return { send, setTooLong, answer, run, recheck, raw: entry?.raw, startUnsure, checking: h.checking };
}

