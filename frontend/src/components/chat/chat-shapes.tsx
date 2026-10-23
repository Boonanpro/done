'use client';

/**
 * ダンの返事の中の「部品」（OpenUI Lang の ```openui-lang ブロック）を描く。
 *
 * - 部品の定義（名前・引数）は lib/chat-shapes/schema.ts。ここでは見た目（React）を付けて
 *   OpenUI の部品一覧（library）にする。
 * - 描くのは @openuidev/react-lang の Renderer。生成の途中（閉じ ``` が無い）でも
 *   届いた分から描き（isStreaming）、その間は押せない。
 * - 押せるのは「保存された返事（id がある）の、閉じまで届いた部品」だけ。ライブ枠（保存前）の部品は
 *   閉じが届いても押せない（ターンの途中の送信は進行中のストリームを切るため）。
 * - 完成した部品は schema.ts の validateComplete で検証し、通らなければ元のコードブロックに戻す
 *   （選択肢の個数、表の列数、グラフの値の数など）。生成途中には検証しない（段階表示を妨げない）。
 * - 選択ボタンと入力欄の答えは、確認カードと同じ経路で「本人の発言」として部屋に送る
 *   （ShapeAnswerProvider の submit = project-chat-panel の answerShapeInRoom）。文面「<問い> → <答え>」に
 *   加えて、どの返事のどの部品への答えか（answer_to: message_id + part）を同じ発言に保存する。
 * - 「答えました」の根拠は部屋の記録（照合情報つきの、今ログインしている本人の保存済み発言だけ。同じ部屋の
 *   別の人の答えは数えない）。送信は idle → sending → saved（保存の echo が返り、その行がまだ画面の記録に載る前の
 *   一時状態）→ 記録に載ったら記録だけが根拠（取り消しで記録から消えれば、答えていない状態に戻って押し直せる）。
 * - 1回の答えの送信は、部品が決めた1つの送信 ID（client_message_id＝保存される行の id）を持ち続ける。送り直しは
 *   いつも同じ ID（サーバーは同じ ID の2回目を保存し直さず、保存済みの行を返す）。新しい ID になるのは、この表示が
 *   保存を確かめた後で取り消されたと確かめた時だけ（前にしか進まない。lib/chat-shapes/answer-sends.ts）。
 *   失敗（failed: サーバーが「その ID は保存されていない」と答えた）は選び直せる（同じ ID で送る）。保存できたか
 *   分からない時（unknown）は押せず、「確かめる」でその ID の保存を聞き直す。聞けなければ unknown のまま。
 * - 送信 ID と状態は部品の中ではなく answer-sends.ts の置き場に、本人＋部屋＋AI の発言＋部品ごとに持つ（部屋を
 *   離れて戻る・ページを読み直す・同じブラウザのほかのタブ、をまたいで同じ送信を続ける）。作り直された部品は、
 *   決着していない送信（分からない・失敗・このタブが送っていない送信中）があれば、押せるようにする前にその ID の
 *   保存をサーバーに確かめる。ほかのタブからの取り込みでは聞かない。
 * - 保存済みとダンの処理の開始は別の状態。始まったと確かでない答えは、サーバーの開始の状態に合わせて確かめ続け、
 *   始まっていない（started: false）と分かった時だけ同じ ID でもう一度送る（サーバーは1回しか始めない）。確かめを
 *   使い切っても分からなければ「確かめる」を出す。
 * - 答えの長さの契約は schema.ts の ANSWER_VALUE_MAX（サーバーと同じ数）。入力欄は長い値を受け付けない。
 * - 選択肢と表の見出し・セルは実物を持てる（{label, color?, image?}。表は色だけ）。色の値と画像の URL は plain.ts の
 *   safeColor・safeImageUrl を通った物だけを描き、通らなければ名前だけ。出すのは閉じまで届いてから（生成の途中の URL を
 *   読みに行かない）。読み込みに失敗した画像は枠ごと消す。押した答えは今までどおり名前（label）。
 *   外の画像（https://…）は認証情報を送らない要求（crossOrigin=anonymous）で読む: Referer だけでなく、その配信先の
 *   Cookie も送らない。CORS に応じない外の画像は読めず、読めない画像と同じく枠ごと消える。ダンのファイル
 *   （/api/v1/files/…。safeImageUrl が同じサイトの物は道だけで返す）は今までどおり同じサイトの要求（Cookie つき）。
 * - 描画で例外が起きても、その部品だけを元のコードブロック（文章）に戻し、画面全体は落とさない。
 */
import {
  Component, createContext, memo, useCallback, useContext, useEffect, useId, useMemo, useState, useSyncExternalStore, type ReactNode,
} from 'react';
// react-lang より先に読む（開発用画面の「OpenUI Inspect」小窓を付けさせない）
import '@/lib/chat-shapes/no-openui-devtools';
import {
  Renderer, createLibrary, defineComponent, useIsStreaming, useRenderNode, type ComponentRenderer, type ParseResult,
} from '@openuidev/react-lang';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { AlertCircle, Check, ExternalLink, Loader2, Send } from 'lucide-react';

import {
  ANSWER_VALUE_MAX, BadgeProps, ButtonProps, CardProps, ChartProps, ChoiceProps, ColumnProps, CompareProps, DividerProps, FactsProps,
  HeadingProps, ImageProps, InputProps, RowProps, StatProps, StepsProps, TextProps, checkShapeProgram, choiceOptions,
  type BadgeInput, type ButtonInput, type CardInput, type ChartInput, type ChoiceInput, type ColumnInput, type CompareInput,
  type FactsInput, type HeadingInput, type ImageInput, type InputInput, type RowInput, type StatInput, type StepsInput, type TextInput,
} from '@/lib/chat-shapes/schema';
import {
  choiceAnswerText, findChoiceAnswer, findInputAnswer, inputAnswerText, inputAnswerValue, readAnswerTo,
  type AnswerTo, type UserUtterance,
} from '@/lib/chat-shapes/answers';
import {
  PAGE, SEND_BUSY, SEND_UNKNOWN, STALE_SENDING_MS, answerSendHere, answerSendKey, answerSendVersion, attachAnswerSend, getAnswerSend,
  isGone, mustCheckBeforePress, needsCheck, noteInRecord, recheckAnswerSend, resumeAnswerSend, sendAnswer, subscribeAnswerSends,
  type AskSaved, type SubmitAnswer,
} from '@/lib/chat-shapes/answer-sends';
import { readLook, safeImageUrl, safeLinkUrl, type Look } from '@/lib/chat-shapes/plain';

// --- 答えの経路（部屋の本人の発言と、発言を送る関数） -------------------------------------

/**
 * 本人の発言として部屋へ送る。clientMessageId は部品が決めた送信 ID（保存される行の id）。
 * サーバーに保存されたら保存された行の id で resolve（echo が無く確かめて分かった時は、ダンの処理の開始の
 * started・start も）。保存されていないとサーバーが答えたら reject。保存できたか分からない（確かめにも失敗した）時は
 * reject(Error(SEND_UNKNOWN))。opts.onEnded はその送信の通信が終わった時に1回（ダンの処理が始まった印を見たか）。
 * opts.background（始まっていない答えの送り直し）は、ほかの送信の通信中なら送らず reject(Error(SEND_BUSY))。
 */
export type ShapeSubmit = SubmitAnswer;

/** その送信 ID の発言が保存されたかをサーバーに聞く（「確かめる」）。聞けなければ reject */
export type ShapeRecheck = AskSaved;

export { SEND_BUSY, SEND_UNKNOWN };

type ShapeAnswerContextValue = {
  /** 部屋にある本人の発言（照合情報つき）。答えた状態の判定に使う */
  utterances: UserUtterance[];
  /** 無ければ答えられない（閲覧だけ） */
  submit: ShapeSubmit | null;
  /** 保存できたか分からない時に押す「確かめる」 */
  recheck: ShapeRecheck | null;
  /** 送信の置き場の鍵の一部（本人・部屋）。どちらか無ければ答えられない */
  ownerId: string | null;
  roomId: string | null;
};

const ShapeAnswerContext = createContext<ShapeAnswerContextValue>({ utterances: [], submit: null, recheck: null, ownerId: null, roomId: null });

type UtteranceSource = {
  id: string; sender_id?: string | null; sender_type: string; content: string | null; created_at: string; ai_context?: unknown; pending?: boolean;
};

/**
 * ownerId: 今ログインしている本人の利用者 ID。「答えました」の根拠にするのは、その人の保存済みの発言だけ
 * （同じ部屋の別の人が同じ部品に答えても、本人の部品は答えたことにならない）。無ければ何も数えない。
 * roomId: この部屋。送信の置き場（answer-sends.ts）の鍵は本人＋部屋＋AI の発言＋部品。
 */
export function ShapeAnswerProvider({
  messages, ownerId, roomId = null, submit, recheck = null, children,
}: { messages: UtteranceSource[]; ownerId: string | null | undefined; roomId?: string | null; submit: ShapeSubmit | null; recheck?: ShapeRecheck | null; children: ReactNode }) {
  const utterances = useMemo<UserUtterance[]>(
    () => (ownerId ? messages : [])
      // 保存前（pending）の発言は数えない: 「答えました」はサーバーに残ってから
      .filter((m) => m.sender_type === 'human' && m.sender_id === ownerId && !m.pending && (m.content || '').trim())
      .map((m) => ({ id: m.id, text: m.content || '', at: Date.parse(m.created_at) || 0, answerTo: readAnswerTo(m.ai_context) })),
    [messages, ownerId],
  );
  const value = useMemo(
    () => ({ utterances, submit, recheck, ownerId: ownerId || null, roomId: roomId || null }),
    [utterances, submit, recheck, ownerId, roomId],
  );
  return <ShapeAnswerContext.Provider value={value}>{children}</ShapeAnswerContext.Provider>;
}

/** 新しい送信 ID（保存される行の id。サーバーは UUID の形の時だけそのまま使う） */
function newSendId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  const h = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`;
}

/** 1つの部品ブロックの素性: どの返事（id）のどの部品（part）か、閉じまで届いたか、ライブ枠（保存前）か */
type ShapeMeta = { messageId: string | null; part: string; complete: boolean; live: boolean };
const ShapeMetaContext = createContext<ShapeMeta>({ messageId: null, part: '', complete: false, live: false });

// --- 共通の見た目 --------------------------------------------------------------------------

const CARD = 'my-2 w-full max-w-full rounded-xl border border-border bg-card p-3 shadow-sm';
const CHOICE_BTN = 'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-sm transition-colors disabled:cursor-default';
// 画像つきの選択肢が並ぶ時のカード（画像を大きめに、名前はその下）
const CHOICE_CARD = 'flex min-w-0 flex-col items-stretch gap-1.5 rounded-lg border p-1.5 text-left text-sm transition-colors disabled:cursor-default';
/** 組み合わせ（Card・Row・Column）の中か。中の部品は自分の枠を付けず、外のカードの中に収まる */
const InsideContext = createContext(false);
/** 部品の外枠の class: 一番外側ならカード、組み合わせの中なら枠なし（Compare の表は細い枠だけ残す） */
function useBox(extra = ''): string {
  const inside = useContext(InsideContext);
  return inside ? `my-1 w-full max-w-full ${extra}` : `${CARD} ${extra}`;
}
const SEND_FAILED = '送れませんでした。もう一度押してください';
const SEND_UNKNOWN_TEXT = '送れたか確かめられませんでした';
const SEND_UNKNOWN_AGAIN = 'まだ確かめられません。通信が戻ってからもう一度押してください';
const SEND_VERIFYING = '前に送った答えが届いたか確かめています…';
const START_UNSURE = '答えは届きましたが、ダンが読み始めたか確かめられませんでした';
const TOO_LONG = `長すぎます（単位を含めて${ANSWER_VALUE_MAX}文字まで）`;

function Answered({ text }: { text: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <Check className="h-3.5 w-3.5" />{text}
    </span>
  );
}

const subscribeNothing = () => () => {};
/** ブラウザで描いている時だけ true（サーバーで先に作る HTML には実物の画像を入れない） */
function useOnClient(): boolean {
  return useSyncExternalStore(subscribeNothing, () => true, () => false);
}

/** この画面のホスト（https:// の画像の URL がこのサイトを指す時は、ダンのファイルの道の決まりで見る。plain.ts safeImageUrl） */
function siteHost(): string | null {
  return typeof window !== 'undefined' ? window.location.host : null;
}

/** 色見本。color は plain.ts safeColor を通った値だけ。暗い背景でも黒・濃紺が、明るい背景でも白が見えるよう縁を付ける */
function Swatch({ color, className = 'h-5 w-5' }: { color: string; className?: string }) {
  return (
    <span aria-hidden data-swatch={color} className={`inline-block shrink-0 rounded-md border border-foreground/40 ${className}`} style={{ backgroundColor: color }} />
  );
}

function Failed({ text, children }: { text: string; children?: ReactNode }) {
  return (
    <div className="mt-2 flex items-center gap-2 text-xs text-red-600" role="alert">
      <AlertCircle className="h-3.5 w-3.5 shrink-0" /><span>{text}</span>{children}
    </div>
  );
}

/**
 * 送信の状態（画面に出す形）: 押していない / 送信中 / 保存された（置き場の事実。行がこのタブの記録に載っていない間は
 * 置き場の答えを出す） / 失敗（保存されていない。選び直せる。送り直しも同じ id） / 保存できたか分からない（その id の
 * 保存を聞き直す。verifying は作り直された部品が押せるようにする前の確かめ）。
 * id はこの答えの送信 ID（保存されたと分かるまで変えない）。長すぎて送らなかった失敗は前の送信の id を持つ
 */
type SendState =
  | { status: 'idle' }
  | { status: 'sending'; value: string; id: string }
  | { status: 'saved'; value: string; id: string }
  | { status: 'failed'; value: string; id?: string; reason?: string }
  | { status: 'unknown'; value: string; id: string; checking?: boolean; again?: boolean; verifying?: boolean };

/** 答えられる条件: 送る先がある・本人と部屋が分かる・保存された返事・閉じまで届いた・ライブ枠でない・まだ答えていない */
function useCanAnswer(answered: boolean) {
  const { submit, ownerId, roomId } = useContext(ShapeAnswerContext);
  const { messageId, complete, live } = useContext(ShapeMetaContext);
  const streaming = useIsStreaming();
  return !!submit && !!ownerId && !!roomId && !!messageId && complete && !live && !streaming && !answered;
}

/**
 * 答えの送信と「答えた」の判定。
 * - recorded: 部屋の記録（照合情報つきの保存済み発言）にあるこの部品への答え。これが根拠
 * - 送信の状態は置き場（answer-sends.ts）にある。保存済みの行がまだ記録に載っていない間は、置き場の答えを出す。
 *   このタブの記録に一度載った後で消えた・照会で無いと分かった（取り消し）時だけ、押し直せる（新しい ID）
 * - 部品が描かれた時に1回、決着していない送信があればその ID の保存をサーバーに確かめる（押せるようにする前の確かめは
 *   この時だけ。ほかのタブからの取り込みでは聞かない）。確かめが済むまでと、分からない間は押せない
 */
function useAnswerSend(recorded: string | null) {
  const { utterances, submit, recheck: askSaved, ownerId, roomId } = useContext(ShapeAnswerContext);
  const { messageId, part } = useContext(ShapeMetaContext);
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

/** 答えは保存されたが、ダンの処理が始まったと確かめられないまま確かめを使い切った */
function StartProblem({ show, checking, recheck }: { show: boolean; checking: boolean; recheck: () => void }) {
  if (!show) return null;
  return (
    <Failed text={START_UNSURE}>
      <button type="button" onClick={recheck} disabled={checking} className="rounded border border-border px-2 py-0.5 text-xs text-foreground hover:bg-muted disabled:opacity-50">
        {checking ? '確かめています…' : '確かめる'}
      </button>
    </Failed>
  );
}

function SendProblem({ send, answered, recheck, id }: { send: SendState; answered: boolean; recheck: () => void; id?: string }) {
  if (answered) return null;
  if (send.status === 'unknown' && send.verifying) {
    return <div id={id} className="mt-2 flex items-center gap-2 text-xs text-muted-foreground" role="status"><Loader2 className="h-3.5 w-3.5 animate-spin" />{SEND_VERIFYING}</div>;
  }
  if (send.status === 'unknown') {
    return (
      <div id={id}>
        <Failed text={send.again ? SEND_UNKNOWN_AGAIN : SEND_UNKNOWN_TEXT}>
          <button type="button" onClick={recheck} disabled={!!send.checking} className="rounded border border-border px-2 py-0.5 text-xs text-foreground hover:bg-muted disabled:opacity-50">
            {send.checking ? '確かめています…' : '確かめる'}
          </button>
        </Failed>
      </div>
    );
  }
  if (send.status === 'failed') return <div id={id}><Failed text={send.reason === 'too long' ? TOO_LONG : SEND_FAILED} /></div>;
  return null;
}

// --- 部品 ---------------------------------------------------------------------------------

const ChoiceView: ComponentRenderer<ChoiceInput> = ({ props }) => {
  const box = useBox();
  const question = (props.question || '').trim();
  const options = choiceOptions(props.options, siteHost());
  const { utterances } = useContext(ShapeAnswerContext);
  const { messageId, part, complete } = useContext(ShapeMetaContext);
  // 実物は閉じまで届いてから・ブラウザでだけ出す。読み込みに失敗した画像は枠ごと消して名前だけにする
  const onClient = useOnClient();
  const looks = complete && onClient;
  const [broken, setBroken] = useState<ReadonlySet<string>>(() => new Set());
  const imageOf = (o: Look) => (looks && o.image && !broken.has(o.image) ? o.image : null);
  const cards = options.some((o) => imageOf(o));
  const recorded = messageId ? findChoiceAnswer(utterances, messageId, part) : null;
  const { send, answer, run, recheck, startUnsure, checking } = useAnswerSend(recorded);
  const canAnswer = useCanAnswer(!!answer);
  const disabled = !canAnswer || send.status === 'sending' || send.status === 'unknown';
  const choose = (o: string) => {
    if (disabled || !messageId) return;
    run(choiceAnswerText(question, o), { message_id: messageId, part, kind: 'choice', value: o, question }, o);
  };
  return (
    <div className={box} data-shape="Choice" data-answered={answer ? 'true' : 'false'} data-send={send.status}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-semibold leading-snug">{question}</div>
        {answer ? <Answered text="答えました" /> : send.status === 'sending' ? <span className="text-xs text-muted-foreground">送っています…</span> : null}
      </div>
      {/* カードは上詰め（画像の無い・読めなかった選択肢を、隣の画像の高さまで空の枠として伸ばさない） */}
      <div className={cards ? 'mt-2 grid grid-cols-2 items-start gap-2 sm:grid-cols-3' : 'mt-2 flex flex-col gap-1.5'} data-choice-layout={cards ? 'cards' : 'list'}>
        {options.map((o) => {
          const picked = answer === o.label;
          const sending = send.status === 'sending' && send.value === o.label;
          const failedPick = send.status === 'failed' && send.value === o.label;
          const cls = picked ? 'border-primary bg-primary/10 font-medium'
            : answer ? 'border-border opacity-50'
            : failedPick ? 'border-red-500/60 hover:bg-muted'
            : 'border-border hover:bg-muted';
          const image = imageOf(o);
          const color = looks ? o.color : null;
          return (
            <button key={o.label} type="button" disabled={disabled} onClick={() => choose(o.label)} aria-pressed={picked} className={`${cards ? CHOICE_CARD : CHOICE_BTN} ${cls}`}>
              {image ? (
                <span className="block w-full overflow-hidden rounded-md bg-muted/60" data-option-image>
                  {/* eslint-disable-next-line @next/next/no-img-element -- 本人のファイルか https の縮小画像をそのまま見せる */}
                  <img
                    src={image} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" draggable={false}
                    crossOrigin={image.startsWith('/') ? undefined : 'anonymous'}
                    onError={() => setBroken((b) => (b.has(image) ? b : new Set(b).add(image)))}
                    className="block aspect-[4/3] w-full object-contain"
                  />
                </span>
              ) : null}
              <span className="inline-flex min-w-0 items-center gap-2">
                {sending ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" /> : null}
                {color ? <Swatch color={color} /> : null}
                <span className="min-w-0 break-words">{o.label}</span>
              </span>
            </button>
          );
        })}
        {options.length === 0 ? <div className="h-8 animate-pulse rounded-lg bg-muted/40" /> : null}
      </div>
      <SendProblem send={send} answered={!!answer} recheck={recheck} />
      <StartProblem show={!!answer && startUnsure} checking={checking} recheck={recheck} />
    </div>
  );
};

const InputView: ComponentRenderer<InputInput> = ({ props }) => {
  const box = useBox();
  const label = (props.label || '').trim();
  const isNumber = props.kind === 'number';
  const unit = props.unit || '';
  const { utterances } = useContext(ShapeAnswerContext);
  const { messageId, part } = useContext(ShapeMetaContext);
  const inputId = useId();
  const recorded = messageId ? findInputAnswer(utterances, messageId, part) : null;
  const { send, setTooLong, answer, run, recheck, raw, startUnsure, checking } = useAnswerSend(recorded);
  // 作り直された部品は、決着していない送信で打った値を入力欄に戻す
  const [value, setValue] = useState(() => raw ?? '');
  const canAnswer = useCanAnswer(!!answer);
  const disabled = !canAnswer || send.status === 'sending' || send.status === 'unknown';
  // 入力欄が受け付ける長さ: 答えの値（単位つき）が契約の上限に収まる分だけ
  const maxLength = Math.max(1, ANSWER_VALUE_MAX - (isNumber ? unit.length : 0));
  const doSend = () => {
    const v = value.trim();
    if (disabled || !v || !messageId) return;
    const shown = inputAnswerValue(label, v, isNumber ? unit : undefined);
    // 黙って切らない。送らないので、前の送信（保存されていないと分かった物）の ID は置き場にそのまま残る
    if (shown.length > ANSWER_VALUE_MAX) { setTooLong(shown); return; }
    run(inputAnswerText(label, v, isNumber ? unit : undefined), { message_id: messageId, part, kind: 'input', value: shown, question: label }, shown, v);
    // 入力した値は失敗しても残す（value はそのまま）
  };
  const problem = send.status === 'failed' || send.status === 'unknown';
  return (
    <div className={box} data-shape="Input" data-answered={answer ? 'true' : 'false'} data-send={send.status}>
      <div className="flex items-start justify-between gap-2">
        <label htmlFor={inputId} className="text-sm font-semibold leading-snug">{label}</label>
        {answer ? <Answered text={`答えました: ${answer}`} /> : null}
      </div>
      {!answer ? (
        <form className="mt-2 flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); doSend(); }}>
          <input
            id={inputId}
            name={`shape-input-${part}`}
            type={isNumber ? 'number' : 'text'}
            inputMode={isNumber ? 'decimal' : 'text'}
            step={isNumber ? 'any' : undefined}
            value={value}
            maxLength={maxLength}
            onChange={(e) => setValue(e.target.value)}
            disabled={disabled}
            placeholder={props.placeholder || ''}
            aria-invalid={problem ? true : undefined}
            aria-describedby={problem ? `${inputId}-error` : undefined}
            className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-sm outline-none focus-visible:border-ring disabled:opacity-60"
          />
          {isNumber && unit ? <span className="shrink-0 text-sm text-muted-foreground">{unit}</span> : null}
          <button
            type="submit" disabled={disabled || !value.trim()}
            className="inline-flex h-9 shrink-0 items-center gap-1 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {send.status === 'sending' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            {send.status === 'sending' ? '送っています' : '送る'}
          </button>
        </form>
      ) : null}
      <SendProblem send={send} answered={!!answer} recheck={recheck} id={`${inputId}-error`} />
      <StartProblem show={!!answer && startUnsure} checking={checking} recheck={recheck} />
    </div>
  );
};

/** 表の見出し・セル: 文字と、色見本があればその左に（looks の時だけ） */
function CellBody({ look, looks }: { look: Look | null; looks: boolean }) {
  const text = look?.label ?? '';
  const color = looks ? look?.color : null;
  if (!color) return <>{text}</>;
  return <span className="inline-flex items-center gap-1.5"><Swatch color={color} className="h-4 w-4" /><span>{text}</span></span>;
}

const CompareView: ComponentRenderer<CompareInput> = ({ props }) => {
  const box = useBox('overflow-x-auto p-0');
  const { complete } = useContext(ShapeMetaContext);
  // 色見本は閉じまで届いてから（生成の途中の色の値を描かない）
  const onClient = useOnClient();
  const looks = complete && onClient;
  const columns = (props.columns || []).map((c) => readLook(c));
  const rows = ((props.rows || []).filter(Array.isArray) as unknown[][]).map((r) => r.map((c) => readLook(c)));
  // 表は吹き出しの幅いっぱいに使う。候補の列には読める最小幅を確保し、入り切らない時は表の中だけ横に動かす
  return (
    <div className={box} data-shape="Compare">
      {props.caption ? <div className="px-3 pt-2.5 text-sm font-semibold">{props.caption}</div> : null}
      <table className="w-full min-w-full table-auto text-sm">
        {columns.length > 0 ? (
          <thead>
            <tr className="border-b border-border">
              {columns.map((c, i) => (
                <th key={i} className={`whitespace-nowrap px-3 py-2 text-left font-medium ${i === 0 ? 'text-muted-foreground' : 'min-w-[9rem]'}`}><CellBody look={c} looks={looks} /></th>
              ))}
            </tr>
          </thead>
        ) : null}
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="border-b border-border last:border-0">
              {(columns.length ? columns : r).map((_, ci) => {
                const look = r[ci] ?? null;
                // 先頭列（観点）は短ければ折らない。長い観点名は普通に折り返す
                const nowrap = ci === 0 && (look?.label ?? '').length <= 12;
                return (
                  <td key={ci} className={`px-3 py-2 align-top ${ci === 0 ? 'text-muted-foreground' : 'min-w-[9rem]'} ${nowrap ? 'whitespace-nowrap' : 'break-words'}`}>
                    <CellBody look={look} looks={looks} />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const StepsView: ComponentRenderer<StepsInput> = ({ props }) => {
  const box = useBox();
  const steps = (props.steps || []).filter((s): s is string => typeof s === 'string' && !!s.trim());
  return (
    <div className={box} data-shape="Steps">
      {props.title ? <div className="mb-2 text-sm font-semibold">{props.title}</div> : null}
      <ol className="flex flex-col gap-2">
        {steps.map((s, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm leading-relaxed">
            <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-[11px] font-medium text-muted-foreground">
              {i + 1}
            </span>
            <span className="min-w-0 break-words">{s}</span>
          </li>
        ))}
      </ol>
    </div>
  );
};

// 単色のテーマ（白のアクセント）に合わせ、系列は同じ色の濃さと線種で分ける。凡例も同じ見た目で描く
const SERIES_STYLE = [
  { color: 'var(--primary)', opacity: 1, dash: undefined as string | undefined },
  { color: 'var(--primary)', opacity: 0.55, dash: '6 3' },
  { color: 'var(--primary)', opacity: 0.3, dash: '2 3' },
  { color: 'var(--muted-foreground)', opacity: 0.8, dash: '4 2' },
];

function SeriesLegend({ names, kind }: { names: string[]; kind: 'line' | 'bar' }) {
  return (
    <ul className="mt-1 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs text-muted-foreground" data-shape-legend>
      {names.map((n, i) => {
        const st = SERIES_STYLE[i % SERIES_STYLE.length];
        return (
          <li key={n} className="inline-flex items-center gap-1.5">
            {kind === 'bar' ? (
              <span className="inline-block h-3 w-3 rounded-sm" style={{ background: st.color, opacity: st.opacity }} aria-hidden />
            ) : (
              <svg width="22" height="8" aria-hidden><line x1="0" y1="4" x2="22" y2="4" stroke={st.color} strokeOpacity={st.opacity} strokeWidth="2" strokeDasharray={st.dash} /></svg>
            )}
            <span>{n}</span>
          </li>
        );
      })}
    </ul>
  );
}

const ChartView: ComponentRenderer<ChartInput> = ({ props }) => {
  const box = useBox();
  const labels = (props.labels || []).map((l) => (typeof l === 'string' ? l : String(l ?? '')));
  const series = (props.series || []).filter((s) => s && typeof s === 'object' && Array.isArray(s.values));
  const unit = props.unit || '';
  const names = series.map((s, si) => s.name || `系列${si + 1}`);
  // まだ届いていない・数値でない値は null（描かない）。0 にすると存在しない下降が見える
  const data = useMemo(
    () => labels.map((label, i) => {
      const row: Record<string, string | number | null> = { label };
      series.forEach((s, si) => {
        const v = s.values[i];
        row[names[si]] = typeof v === 'number' && Number.isFinite(v) ? v : null;
      });
      return row;
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(labels), JSON.stringify(series)],
  );
  const fmt = (v: unknown) => (typeof v === 'number' ? `${v.toLocaleString('ja-JP')}${unit}` : v == null ? '—' : `${String(v)}${unit}`);
  const kind: 'line' | 'bar' = props.kind === 'line' ? 'line' : 'bar';
  const common = { data, margin: { top: 8, right: 12, left: 0, bottom: 0 } };
  const axisStyle = { fontSize: 11, fill: 'var(--muted-foreground)' };
  const tooltipStyle = {
    contentStyle: { background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 },
    labelStyle: { color: 'var(--foreground)' },
    itemStyle: { color: 'var(--foreground)' },
  };
  return (
    <div className={box} data-shape="Chart">
      {props.title ? <div className="mb-1 text-sm font-semibold">{props.title}</div> : null}
      <div className="h-[220px] w-full">
        {data.length > 0 && names.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            {kind === 'line' ? (
              <LineChart {...common}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" tick={axisStyle} axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={72} tickFormatter={(v) => fmt(v)} />
                <Tooltip {...tooltipStyle} formatter={(v) => fmt(v)} />
                {names.length > 1 ? <Legend content={() => <SeriesLegend names={names} kind="line" />} /> : null}
                {names.map((n, i) => {
                  const st = SERIES_STYLE[i % SERIES_STYLE.length];
                  return (
                    <Line key={n} type="monotone" dataKey={n} stroke={st.color} strokeOpacity={st.opacity} connectNulls={false}
                      strokeWidth={2} strokeDasharray={st.dash} dot={{ r: 3, strokeOpacity: st.opacity }} isAnimationActive={false} />
                  );
                })}
              </LineChart>
            ) : (
              <BarChart {...common}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" tick={axisStyle} axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={72} tickFormatter={(v) => fmt(v)} />
                <Tooltip {...tooltipStyle} cursor={{ fill: 'var(--muted)' }} formatter={(v) => fmt(v)} />
                {names.length > 1 ? <Legend content={() => <SeriesLegend names={names} kind="bar" />} /> : null}
                {names.map((n, i) => {
                  const st = SERIES_STYLE[i % SERIES_STYLE.length];
                  return <Bar key={n} dataKey={n} fill={st.color} fillOpacity={st.opacity} radius={[4, 4, 0, 0]} isAnimationActive={false} />;
                })}
              </BarChart>
            )}
          </ResponsiveContainer>
        ) : (
          <div className="h-full animate-pulse rounded-lg bg-muted/40" />
        )}
      </div>
    </div>
  );
};

// --- 組み合わせて画面を作る小さな部品（2026-10-23） ---------------------------------------------------
// Card・Row・Column の子は lang-core の要素（useRenderNode で描く）か、文字だけの子。子は InsideContext の中で描き、
// 中の部品（表・選択ボタンなど）は自分の枠を付けない。写真は plain.ts safeImageUrl、ボタンの行き先は safeLinkUrl を通った物だけ。

/** 子の部品の名前（lang-core の要素なら typeName） */
const childName = (c: unknown): string => (c && typeof c === 'object' && typeof (c as { typeName?: unknown }).typeName === 'string' ? (c as { typeName: string }).typeName : '');
/** 横並びの中で幅を分け合う部品（カード・縦並び・表・グラフ）。ほかの部品（数字・札・ボタン）は中身の幅のまま */
const WIDE = new Set(['Card', 'Column', 'Compare', 'Chart', 'Steps', 'Facts']);

function ChildList({ items, row = false }: { items: unknown; row?: boolean }) {
  const renderNode = useRenderNode();
  const list = Array.isArray(items) ? items : [];
  return (
    <InsideContext.Provider value={true}>
      {list.map((c, i) => (typeof c === 'string'
        ? <p key={i} className="text-sm leading-relaxed">{c}</p>
        : <div key={i} className={row && WIDE.has(childName(c)) ? 'min-w-0 flex-1 basis-44' : 'min-w-0'}>{renderNode(c)}</div>))}
    </InsideContext.Provider>
  );
}

/** 写真1枚。読めなければ枠ごと消す。外の写真は Cookie・Referer を送らずに読む */
function ShapeImage({ src, alt, className }: { src: unknown; alt?: string; className: string }) {
  const { complete } = useContext(ShapeMetaContext);
  const onClient = useOnClient();
  const url = complete && onClient ? safeImageUrl(src, siteHost()) : null;
  const [broken, setBroken] = useState<string | null>(null);
  if (!url || broken === url) return null;
  return (
    <img
      src={url} alt={alt || ''} loading="lazy" decoding="async" referrerPolicy="no-referrer" draggable={false}
      crossOrigin={url.startsWith('/') ? undefined : 'anonymous'} onError={() => setBroken(url)}
      className={`w-full rounded-lg border border-border bg-muted/30 object-cover ${className}`}
    />
  );
}

const TONE_TEXT: Record<string, string> = {
  good: 'text-emerald-700 dark:text-emerald-400', warn: 'text-amber-700 dark:text-amber-400',
  bad: 'text-red-600 dark:text-red-400', info: 'text-sky-700 dark:text-sky-400', neutral: '', normal: '',
};
const TONE_BADGE: Record<string, string> = {
  good: 'border-emerald-600/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300',
  warn: 'border-amber-600/30 bg-amber-500/10 text-amber-800 dark:text-amber-300',
  bad: 'border-red-600/30 bg-red-500/10 text-red-700 dark:text-red-300',
  info: 'border-sky-600/30 bg-sky-500/10 text-sky-800 dark:text-sky-300',
  neutral: 'border-border bg-muted text-muted-foreground',
};

const CardView: ComponentRenderer<CardInput> = ({ props }) => {
  // 組み合わせの中のカードは、外のカードと区別できるよう細い枠だけ付ける
  const inside = useContext(InsideContext);
  const outer = useBox('flex flex-col gap-2');
  const box = inside ? 'flex h-full w-full flex-col gap-1.5 rounded-lg border border-border p-2.5' : outer;
  return (
    <div className={box} data-shape="Card">
      <ShapeImage src={props.image} className="aspect-[16/9] max-h-56" />
      {props.title ? <div className="text-sm font-semibold">{props.title}</div> : null}
      <ChildList items={props.children} />
    </div>
  );
};

const RowView: ComponentRenderer<RowInput> = ({ props }) => {
  const justify = props.align === 'center' ? 'justify-center' : props.align === 'between' ? 'justify-between' : 'justify-start';
  return (
    <div className={`flex w-full flex-wrap items-stretch gap-x-4 gap-y-2 ${justify}`} data-shape="Row">
      <ChildList items={props.children} row />
    </div>
  );
};

const ColumnView: ComponentRenderer<ColumnInput> = ({ props }) => (
  <div className="flex w-full flex-col gap-2" data-shape="Column">
    <ChildList items={props.children} />
  </div>
);

const HeadingView: ComponentRenderer<HeadingInput> = ({ props }) => (
  <div data-shape="Heading">
    <div className="text-base font-semibold leading-snug">{props.text}</div>
    {props.sub ? <div className="text-sm text-muted-foreground">{props.sub}</div> : null}
  </div>
);

const TextView: ComponentRenderer<TextInput> = ({ props }) => {
  const tone = props.tone === 'muted' ? 'text-sm text-muted-foreground' : props.tone === 'strong' ? 'text-sm font-semibold'
    : props.tone === 'small' ? 'text-xs text-muted-foreground' : 'text-sm';
  return <p className={`leading-relaxed ${tone}`} data-shape="Text">{props.text}</p>;
};

const ImageView: ComponentRenderer<ImageInput> = ({ props }) => {
  const shape = props.shape === 'square' ? 'aspect-square max-w-[16rem]' : props.shape === 'tall' ? 'aspect-[3/4] max-w-[16rem]' : 'aspect-[16/9]';
  return <div className="w-full" data-shape="Image"><ShapeImage src={props.src} alt={props.alt} className={shape} /></div>;
};

const StatView: ComponentRenderer<StatInput> = ({ props }) => {
  const value = typeof props.value === 'number' ? props.value.toLocaleString('ja-JP') : props.value;
  return (
    <div className="min-w-[6rem]" data-shape="Stat">
      <div className="text-xs text-muted-foreground">{props.label}</div>
      <div className={`text-xl font-semibold tabular-nums leading-tight ${TONE_TEXT[props.tone || 'neutral'] || ''}`}>
        {value}{props.unit ? <span className="ml-0.5 text-sm font-medium">{props.unit}</span> : null}
      </div>
      {props.note ? <div className="text-xs text-muted-foreground">{props.note}</div> : null}
    </div>
  );
};

const FactsView: ComponentRenderer<FactsInput> = ({ props }) => (
  <dl className="grid w-full grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm" data-shape="Facts">
    {(props.items || []).map((x, i) => (
      <div key={i} className="contents">
        <dt className="text-muted-foreground">{x.label}</dt>
        <dd className="min-w-0 break-words">{typeof x.value === 'number' ? x.value.toLocaleString('ja-JP') : x.value}</dd>
      </div>
    ))}
  </dl>
);

const BadgeView: ComponentRenderer<BadgeInput> = ({ props }) => (
  <span className={`inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_BADGE[props.tone || 'neutral'] || TONE_BADGE.neutral}`} data-shape="Badge">
    {props.text}
  </span>
);

const ButtonView: ComponentRenderer<ButtonInput> = ({ props }) => {
  const { complete } = useContext(ShapeMetaContext);
  const url = complete ? safeLinkUrl(props.url) : null;
  const cls = 'inline-flex w-fit items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium';
  if (!url) return <span className={`${cls} border border-border text-muted-foreground`} data-shape="Button">{props.label}</span>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className={`${cls} bg-primary text-primary-foreground hover:bg-primary/90`} data-shape="Button">
      {props.label}<ExternalLink className="h-3.5 w-3.5" />
    </a>
  );
};

const DividerView: ComponentRenderer<Record<string, never>> = () => <hr className="my-1 w-full border-border" data-shape="Divider" />;

// --- 部品一覧（OpenUI の library） ----------------------------------------------------------

export const shapeLibrary = createLibrary({
  components: [
    defineComponent({ name: 'Compare', description: '横並びの表', props: CompareProps, component: CompareView }),
    defineComponent({ name: 'Choice', description: '選択ボタン', props: ChoiceProps, component: ChoiceView }),
    defineComponent({ name: 'Input', description: '入力欄', props: InputProps, component: InputView }),
    defineComponent({ name: 'Steps', description: '手順', props: StepsProps, component: StepsView }),
    defineComponent({ name: 'Chart', description: 'グラフ', props: ChartProps, component: ChartView }),
    defineComponent({ name: 'Card', description: 'カード', props: CardProps, component: CardView }),
    defineComponent({ name: 'Row', description: '横並び', props: RowProps, component: RowView }),
    defineComponent({ name: 'Column', description: '縦並び', props: ColumnProps, component: ColumnView }),
    defineComponent({ name: 'Heading', description: '見出し', props: HeadingProps, component: HeadingView }),
    defineComponent({ name: 'Text', description: '文', props: TextProps, component: TextView }),
    defineComponent({ name: 'Image', description: '写真', props: ImageProps, component: ImageView }),
    defineComponent({ name: 'Stat', description: '数字', props: StatProps, component: StatView }),
    defineComponent({ name: 'Facts', description: '事実の並び', props: FactsProps, component: FactsView }),
    defineComponent({ name: 'Badge', description: '札', props: BadgeProps, component: BadgeView }),
    defineComponent({ name: 'Button', description: 'ボタン', props: ButtonProps, component: ButtonView }),
    defineComponent({ name: 'Divider', description: '区切り線', props: DividerProps, component: DividerView }),
  ],
});

/**
 * 完成したブロックの検証: ブロック全体（root と名前で指す文、入れ子の部品）を読み、部品ごとに schema.ts の検証と
 * 組み合わせの決まりにかける（checkShapeProgram）。通らなければ理由（画面は元のコードに戻す）。
 */
export function checkCompleteShape(code: string): { ok: true; name: string } | { ok: false; reason: string } {
  const r = checkShapeProgram(code);
  return r.ok ? { ok: true, name: r.root.name } : r;
}

// --- 1ブロックの描画（例外はその部品だけ文章に戻す） --------------------------------------------

class ShapeErrorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.warn('[chat-shapes] render failed; showing the block as text', error); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export const ShapeBlock = memo(function ShapeBlock({
  code, complete, live = false, messageId = null, part, renderFallback,
}: {
  /** ```openui-lang ブロックの中身（途中まででもよい） */
  code: string;
  /** 閉じ ``` まで届いたか。false の間は生成中として扱い、押せない */
  complete: boolean;
  /** ライブ枠（ターンの途中、保存前）か。true の間は閉じが届いても押せない */
  live?: boolean;
  /** 保存された返事の id。無ければ（ライブ枠）答えられない */
  messageId?: string | null;
  /** この返事の中での部品の鍵（answers.ts の partKeys）。答えの照合に使う */
  part: string;
  /** 部品として描けない時に、同じ中身を文章（コードブロック）として描く */
  renderFallback: (code: string) => ReactNode;
}) {
  const trimmed = code.trim();
  // 読めたかどうかは「今の中身」に対する結果だけを見る。生成の途中（まだ root が無い）の結果を、
  // 閉じが届いた瞬間に流用すると、文章に戻した上で Renderer が外れて二度と読み直さない。
  const [parse, setParse] = useState<{ forCode: string; root: boolean } | null>(null);
  const onParseResult = useCallback((r: ParseResult | null) => {
    setParse(r ? { forCode: trimmed, root: !!r.root } : null);
  }, [trimmed]);
  const meta = useMemo<ShapeMeta>(() => ({ messageId, part, complete, live }), [messageId, part, complete, live]);
  // 完成した部品の検証（閉じが届いた時だけ。途中は段階表示を妨げない）
  const check = useMemo(() => (complete && trimmed ? checkCompleteShape(trimmed) : null), [complete, trimmed]);
  const parsed = parse && parse.forCode === trimmed ? parse : null;
  if (complete && (!trimmed || (parsed && !parsed.root) || (check && !check.ok))) {
    // 中身が無い／部品として読めない（知らない部品名、必須の引数が無い）／完成の検証に通らない: 文章として出す
    if (check && !check.ok && trimmed) console.warn('[chat-shapes] block shown as text:', check.reason);
    return <>{renderFallback(code)}</>;
  }
  return (
    <ShapeErrorBoundary fallback={renderFallback(code)}>
      <ShapeMetaContext.Provider value={meta}>
        <div className="not-prose" data-shape-block={complete ? 'complete' : 'streaming'} data-shape-live={live ? 'true' : 'false'}>
          {!complete && (!parsed || !parsed.root) ? (
            <div className={`${CARD} h-16 animate-pulse bg-muted/30`} aria-label="部品を準備中" />
          ) : null}
          <Renderer
            response={trimmed}
            library={shapeLibrary}
            isStreaming={!complete}
            onParseResult={onParseResult}
            publishObservability={false}
          />
        </div>
      </ShapeMetaContext.Provider>
    </ShapeErrorBoundary>
  );
});
