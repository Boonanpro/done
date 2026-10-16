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
 * - 1回の答えの送信は、部品が決めた1つの送信 ID（client_message_id＝保存される行の id）を持ち続ける。保存されたと
 *   分かるまで、送り直しはいつも同じ ID（サーバーは同じ ID の2回目を保存し直さず、保存済みの行を返す）。
 *   失敗（failed: サーバーが「その ID は保存されていない」と答えた）は選び直せる（同じ ID で送る）。保存できたか
 *   分からない時（unknown）は押せず、「確かめる」でその ID の保存を聞き直す。聞けなければ unknown のまま。
 * - 答えの長さの契約は schema.ts の ANSWER_VALUE_MAX（サーバーと同じ数）。入力欄は長い値を受け付けない。
 * - 描画で例外が起きても、その部品だけを元のコードブロック（文章）に戻し、画面全体は落とさない。
 */
import {
  Component, createContext, memo, useCallback, useContext, useId, useMemo, useState, type ReactNode,
} from 'react';
import {
  Renderer, createLibrary, defineComponent, useIsStreaming, type ComponentRenderer, type ParseResult,
} from '@openuidev/react-lang';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { AlertCircle, Check, Loader2, Send } from 'lucide-react';

import {
  ANSWER_VALUE_MAX, ChartProps, ChoiceProps, CompareProps, InputProps, SHAPE_SPECS, StepsProps, normalizeOptions, validateComplete,
  type ChartInput, type ChoiceInput, type CompareInput, type InputInput, type StepsInput,
} from '@/lib/chat-shapes/schema';
import {
  choiceAnswerText, findChoiceAnswer, findInputAnswer, inputAnswerText, inputAnswerValue, readAnswerTo,
  type AnswerTo, type UserUtterance,
} from '@/lib/chat-shapes/answers';
import { parseShapeCall } from '@/lib/chat-shapes/plain';

// --- 答えの経路（部屋の本人の発言と、発言を送る関数） -------------------------------------

/**
 * 本人の発言として部屋へ送る。clientMessageId は部品が決めた送信 ID（保存される行の id）。
 * サーバーに保存されたら保存された行の id で resolve。保存されていないとサーバーが答えたら reject。
 * 保存できたか分からない（確かめにも失敗した）時は reject(Error(SEND_UNKNOWN))。
 */
export type ShapeSubmit = (text: string, answerTo: AnswerTo, clientMessageId: string) => Promise<{ id: string }>;

/** その送信 ID の発言が保存されたかをサーバーに聞く（「確かめる」）。聞けなければ reject */
export type ShapeRecheck = (clientMessageId: string) => Promise<{ saved: boolean }>;

/** submit が「保存できたか分からない」で reject する時の message */
export const SEND_UNKNOWN = 'unknown';

type ShapeAnswerContextValue = {
  /** 部屋にある本人の発言（照合情報つき）。答えた状態の判定に使う */
  utterances: UserUtterance[];
  /** 無ければ答えられない（閲覧だけ） */
  submit: ShapeSubmit | null;
  /** 保存できたか分からない時に押す「確かめる」 */
  recheck: ShapeRecheck | null;
};

const ShapeAnswerContext = createContext<ShapeAnswerContextValue>({ utterances: [], submit: null, recheck: null });

type UtteranceSource = {
  id: string; sender_id?: string | null; sender_type: string; content: string | null; created_at: string; ai_context?: unknown; pending?: boolean;
};

/**
 * ownerId: 今ログインしている本人の利用者 ID。「答えました」の根拠にするのは、その人の保存済みの発言だけ
 * （同じ部屋の別の人が同じ部品に答えても、本人の部品は答えたことにならない）。無ければ何も数えない。
 */
export function ShapeAnswerProvider({
  messages, ownerId, submit, recheck = null, children,
}: { messages: UtteranceSource[]; ownerId: string | null | undefined; submit: ShapeSubmit | null; recheck?: ShapeRecheck | null; children: ReactNode }) {
  const utterances = useMemo<UserUtterance[]>(
    () => (ownerId ? messages : [])
      // 保存前（pending）の発言は数えない: 「答えました」はサーバーに残ってから
      .filter((m) => m.sender_type === 'human' && m.sender_id === ownerId && !m.pending && (m.content || '').trim())
      .map((m) => ({ id: m.id, text: m.content || '', at: Date.parse(m.created_at) || 0, answerTo: readAnswerTo(m.ai_context) })),
    [messages, ownerId],
  );
  const value = useMemo(() => ({ utterances, submit, recheck }), [utterances, submit, recheck]);
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
const SEND_FAILED = '送れませんでした。もう一度押してください';
const SEND_UNKNOWN_TEXT = '送れたか確かめられませんでした';
const SEND_UNKNOWN_AGAIN = 'まだ確かめられません。通信が戻ってからもう一度押してください';
const TOO_LONG = `長すぎます（単位を含めて${ANSWER_VALUE_MAX}文字まで）`;

function Answered({ text }: { text: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <Check className="h-3.5 w-3.5" />{text}
    </span>
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
 * 送信の状態: 押していない / 送信中 / 保存された（echo の行 id。その行が画面の記録に載るまでの一時状態） /
 * 失敗（保存されていない。選び直せる。送り直しも同じ id） / 保存できたか分からない（その id の保存を聞き直す）。
 * id はこの答えの送信 ID（保存されたと分かるまで変えない）。長すぎて送らなかった失敗には無い
 */
type SendState =
  | { status: 'idle' }
  | { status: 'sending'; value: string; id: string }
  | { status: 'saved'; value: string; id: string }
  | { status: 'failed'; value: string; id?: string; reason?: string }
  | { status: 'unknown'; value: string; id: string; checking?: boolean; again?: boolean };

/** 答えられる条件: 送る先がある・保存された返事・閉じまで届いた・ライブ枠でない・まだ答えていない */
function useCanAnswer(answered: boolean) {
  const { submit } = useContext(ShapeAnswerContext);
  const { messageId, complete, live } = useContext(ShapeMetaContext);
  const streaming = useIsStreaming();
  return !!submit && !!messageId && complete && !live && !streaming && !answered;
}

/**
 * 答えの送信と「答えた」の判定。
 * - recorded: 部屋の記録（照合情報つきの保存済み発言）にあるこの部品への答え。これが根拠
 * - saved は、保存の echo が返ってからその行が記録（utterances）に現れるまでの一時状態。行が一度記録に現れたら
 *   （seenSaved）以後は記録だけを見る。取り消しで記録から消えれば answered は false に戻り、押し直せる
 *   （「現れた」の印は描画中に合わせる: React の「prop の変化で state を直す」手順。effect で setState しない）
 */
function useAnswerSend(recorded: string | null) {
  const { utterances, submit, recheck: askSaved } = useContext(ShapeAnswerContext);
  const [send, setSend] = useState<SendState>({ status: 'idle' });
  const [seenSaved, setSeenSaved] = useState<string | null>(null);
  const savedInRecord = send.status === 'saved' && utterances.some((u) => u.id === send.id);
  if (savedInRecord && seenSaved !== send.id) setSeenSaved(send.id);
  const seen = send.status === 'saved' && seenSaved === send.id;
  const answer = recorded ?? (send.status === 'saved' && !seen ? send.value : null);
  // 記録に現れた後で記録から消えた（取り消し）: 送信の状態としては何もしていないのと同じ
  const shown: SendState = seen && !savedInRecord ? { status: 'idle' } : send;
  const run = (text: string, answerTo: AnswerTo, value: string) => {
    if (!submit) return;
    // 保存されたと分かっていない送信の続きは同じ送信 ID（二重に保存されない）。保存済み・初めては新しい ID
    const id = (send.status === 'failed' || send.status === 'unknown') && send.id ? send.id : newSendId();
    setSend({ status: 'sending', value, id });
    submit(text, answerTo, id)
      .then((saved) => setSend({ status: 'saved', value, id: saved.id }))
      .catch((e: unknown) => setSend(e instanceof Error && e.message === SEND_UNKNOWN ? { status: 'unknown', value, id } : { status: 'failed', value, id }));
  };
  // 保存できたか分からない時: その送信 ID の保存をサーバーに聞き直す。保存済みなら答えた、保存されていなければ
  // 失敗（同じ ID で送り直せる）、聞けなければ分からないまま（押せないまま）
  const recheck = () => {
    if (send.status !== 'unknown' || send.checking || !askSaved) return;
    const { value, id } = send;
    setSend({ status: 'unknown', value, id, checking: true });
    askSaved(id)
      .then((r) => setSend(r.saved ? { status: 'saved', value, id } : { status: 'failed', value, id }))
      .catch(() => setSend({ status: 'unknown', value, id, again: true }));
  };
  return { send: shown, setSend, answer, run, recheck };
}

function SendProblem({ send, answered, recheck, id }: { send: SendState; answered: boolean; recheck: () => void; id?: string }) {
  if (answered) return null;
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
  const question = (props.question || '').trim();
  const options = normalizeOptions(props.options);
  const { utterances } = useContext(ShapeAnswerContext);
  const { messageId, part } = useContext(ShapeMetaContext);
  const recorded = messageId ? findChoiceAnswer(utterances, messageId, part) : null;
  const { send, answer, run, recheck } = useAnswerSend(recorded);
  const canAnswer = useCanAnswer(!!answer);
  const disabled = !canAnswer || send.status === 'sending' || send.status === 'unknown';
  const choose = (o: string) => {
    if (disabled || !messageId) return;
    run(choiceAnswerText(question, o), { message_id: messageId, part, kind: 'choice', value: o, question }, o);
  };
  return (
    <div className={CARD} data-shape="Choice" data-answered={answer ? 'true' : 'false'} data-send={send.status}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-semibold leading-snug">{question}</div>
        {answer ? <Answered text="答えました" /> : send.status === 'sending' ? <span className="text-xs text-muted-foreground">送っています…</span> : null}
      </div>
      <div className="mt-2 flex flex-col gap-1.5">
        {options.map((o) => {
          const picked = answer === o;
          const sending = send.status === 'sending' && send.value === o;
          const failedPick = send.status === 'failed' && send.value === o;
          const cls = picked ? 'border-primary bg-primary/10 font-medium'
            : answer ? 'border-border opacity-50'
            : failedPick ? 'border-red-500/60 hover:bg-muted'
            : 'border-border hover:bg-muted';
          return (
            <button key={o} type="button" disabled={disabled} onClick={() => choose(o)} aria-pressed={picked} className={`${CHOICE_BTN} ${cls}`}>
              {sending ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" /> : null}
              <span>{o}</span>
            </button>
          );
        })}
        {options.length === 0 ? <div className="h-8 animate-pulse rounded-lg bg-muted/40" /> : null}
      </div>
      <SendProblem send={send} answered={!!answer} recheck={recheck} />
    </div>
  );
};

const InputView: ComponentRenderer<InputInput> = ({ props }) => {
  const label = (props.label || '').trim();
  const isNumber = props.kind === 'number';
  const unit = props.unit || '';
  const { utterances } = useContext(ShapeAnswerContext);
  const { messageId, part } = useContext(ShapeMetaContext);
  const inputId = useId();
  const [value, setValue] = useState('');
  const recorded = messageId ? findInputAnswer(utterances, messageId, part) : null;
  const { send, setSend, answer, run, recheck } = useAnswerSend(recorded);
  const canAnswer = useCanAnswer(!!answer);
  const disabled = !canAnswer || send.status === 'sending' || send.status === 'unknown';
  // 入力欄が受け付ける長さ: 答えの値（単位つき）が契約の上限に収まる分だけ
  const maxLength = Math.max(1, ANSWER_VALUE_MAX - (isNumber ? unit.length : 0));
  const doSend = () => {
    const v = value.trim();
    if (disabled || !v || !messageId) return;
    const shown = inputAnswerValue(label, v, isNumber ? unit : undefined);
    // 黙って切らない。送らないので、前の送信の ID（保存されていないと分かった物）はそのまま持ち続ける
    if (shown.length > ANSWER_VALUE_MAX) { setSend({ status: 'failed', value: shown, reason: 'too long', id: send.status === 'failed' ? send.id : undefined }); return; }
    run(inputAnswerText(label, v, isNumber ? unit : undefined), { message_id: messageId, part, kind: 'input', value: shown, question: label }, shown);
    // 入力した値は失敗しても残す（value はそのまま）
  };
  const problem = send.status === 'failed' || send.status === 'unknown';
  return (
    <div className={CARD} data-shape="Input" data-answered={answer ? 'true' : 'false'} data-send={send.status}>
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
    </div>
  );
};

const CompareView: ComponentRenderer<CompareInput> = ({ props }) => {
  const columns = (props.columns || []).map((c) => (typeof c === 'string' ? c : ''));
  const rows = (props.rows || []).filter(Array.isArray) as string[][];
  // 表は吹き出しの幅いっぱいに使う。候補の列には読める最小幅を確保し、入り切らない時は表の中だけ横に動かす
  return (
    <div className={`${CARD} overflow-x-auto p-0`} data-shape="Compare">
      {props.caption ? <div className="px-3 pt-2.5 text-sm font-semibold">{props.caption}</div> : null}
      <table className="w-full min-w-full table-auto text-sm">
        {columns.length > 0 ? (
          <thead>
            <tr className="border-b border-border">
              {columns.map((c, i) => (
                <th key={i} className={`whitespace-nowrap px-3 py-2 text-left font-medium ${i === 0 ? 'text-muted-foreground' : 'min-w-[9rem]'}`}>{c}</th>
              ))}
            </tr>
          </thead>
        ) : null}
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="border-b border-border last:border-0">
              {(columns.length ? columns : r).map((_, ci) => {
                const text = typeof r[ci] === 'string' ? r[ci] : '';
                // 先頭列（観点）は短ければ折らない。長い観点名は普通に折り返す
                const nowrap = ci === 0 && text.length <= 12;
                return (
                  <td key={ci} className={`px-3 py-2 align-top ${ci === 0 ? 'text-muted-foreground' : 'min-w-[9rem]'} ${nowrap ? 'whitespace-nowrap' : 'break-words'}`}>
                    {text}
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
  const steps = (props.steps || []).filter((s): s is string => typeof s === 'string' && !!s.trim());
  return (
    <div className={CARD} data-shape="Steps">
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
    <div className={CARD} data-shape="Chart">
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

// --- 部品一覧（OpenUI の library） ----------------------------------------------------------

export const shapeLibrary = createLibrary({
  components: [
    defineComponent({ name: 'Compare', description: '横並びの表', props: CompareProps, component: CompareView }),
    defineComponent({ name: 'Choice', description: '選択ボタン', props: ChoiceProps, component: ChoiceView }),
    defineComponent({ name: 'Input', description: '入力欄', props: InputProps, component: InputView }),
    defineComponent({ name: 'Steps', description: '手順', props: StepsProps, component: StepsView }),
    defineComponent({ name: 'Chart', description: 'グラフ', props: ChartProps, component: ChartView }),
  ],
});

/**
 * 完成したブロックの検証: `root = 部品(引数…)` を読み、位置引数を部品定義の順に名前へ当てて
 * schema.ts の validateComplete にかける。通らなければ理由（画面は元のコードに戻す）。
 */
export function checkCompleteShape(code: string): { ok: true; name: string } | { ok: false; reason: string } {
  const call = parseShapeCall(code);
  if (!call) return { ok: false, reason: 'root = 部品(...) の形で読めない' };
  const spec = SHAPE_SPECS.find((s) => s.name === call.name);
  if (!spec) return { ok: false, reason: `知らない部品: ${call.name}` };
  const keys = Object.keys(spec.props.shape);
  if (call.args.length > keys.length) return { ok: false, reason: `${call.name}: 引数が多い` };
  const props = Object.fromEntries(call.args.map((a, i) => [keys[i], a]));
  const r = validateComplete(call.name, props);
  return r.ok ? { ok: true, name: call.name } : r;
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
