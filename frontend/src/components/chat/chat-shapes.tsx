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
 *   （ShapeAnswerProvider の submit = project-chat-panel の answerInRoom）。文面「<問い> → <答え>」に
 *   加えて、どの返事のどの部品への答えか（answer_to: message_id + part）を同じ発言に保存する。
 * - 「答えました」は、その照合情報つきの発言がサーバーに保存されてから出す。送信中は送信中、
 *   失敗したら失敗と出して選び直せる（楽観表示を保存の根拠にしない）。
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
  ChartProps, ChoiceProps, CompareProps, InputProps, SHAPE_SPECS, StepsProps, normalizeOptions, validateComplete,
  type ChartInput, type ChoiceInput, type CompareInput, type InputInput, type StepsInput,
} from '@/lib/chat-shapes/schema';
import {
  choiceAnswerText, findChoiceAnswer, findInputAnswer, inputAnswerText, inputAnswerValue, readAnswerTo,
  type AnswerTo, type UserUtterance,
} from '@/lib/chat-shapes/answers';
import { parseShapeCall } from '@/lib/chat-shapes/plain';

// --- 答えの経路（部屋の本人の発言と、発言を送る関数） -------------------------------------

/** 本人の発言として部屋へ送る。サーバーに保存されたら resolve、保存されなかったら reject。 */
export type ShapeSubmit = (text: string, answerTo: AnswerTo) => Promise<void>;

type ShapeAnswerContextValue = {
  /** 部屋にある本人の発言（照合情報つき）。答えた状態の判定に使う */
  utterances: UserUtterance[];
  /** 無ければ答えられない（閲覧だけ） */
  submit: ShapeSubmit | null;
};

const ShapeAnswerContext = createContext<ShapeAnswerContextValue>({ utterances: [], submit: null });

type UtteranceSource = { sender_type: string; content: string | null; created_at: string; ai_context?: unknown; pending?: boolean };

export function ShapeAnswerProvider({
  messages, submit, children,
}: { messages: UtteranceSource[]; submit: ShapeSubmit | null; children: ReactNode }) {
  const utterances = useMemo<UserUtterance[]>(
    () => messages
      // 保存前（pending）の発言は数えない: 「答えました」はサーバーに残ってから
      .filter((m) => m.sender_type === 'human' && !m.pending && (m.content || '').trim())
      .map((m) => ({ text: m.content || '', at: Date.parse(m.created_at) || 0, answerTo: readAnswerTo(m.ai_context) })),
    [messages],
  );
  const value = useMemo(() => ({ utterances, submit }), [utterances, submit]);
  return <ShapeAnswerContext.Provider value={value}>{children}</ShapeAnswerContext.Provider>;
}

/** 1つの部品ブロックの素性: どの返事（id）のどの部品（part）か、閉じまで届いたか、ライブ枠（保存前）か */
type ShapeMeta = { messageId: string | null; part: string; complete: boolean; live: boolean };
const ShapeMetaContext = createContext<ShapeMeta>({ messageId: null, part: '', complete: false, live: false });

// --- 共通の見た目 --------------------------------------------------------------------------

const CARD = 'my-2 w-full max-w-full rounded-xl border border-border bg-card p-3 shadow-sm';
const CHOICE_BTN = 'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-sm transition-colors disabled:cursor-default';
const SEND_FAILED = '送れませんでした。もう一度押してください';

function Answered({ text }: { text: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <Check className="h-3.5 w-3.5" />{text}
    </span>
  );
}

function Failed({ text }: { text: string }) {
  return (
    <div className="mt-2 flex items-center gap-1 text-xs text-red-600" role="alert">
      <AlertCircle className="h-3.5 w-3.5 shrink-0" />{text}
    </div>
  );
}

/** 送信の状態: 押していない / 送信中 / 保存された（照合情報の発言がまだ画面に無い間の保険） / 失敗 */
type SendState =
  | { status: 'idle' }
  | { status: 'sending'; value: string }
  | { status: 'saved'; value: string }
  | { status: 'failed'; value: string };

/** 答えられる条件: 送る先がある・保存された返事・閉じまで届いた・ライブ枠でない・まだ答えていない */
function useCanAnswer(answered: boolean) {
  const { submit } = useContext(ShapeAnswerContext);
  const { messageId, complete, live } = useContext(ShapeMetaContext);
  const streaming = useIsStreaming();
  return !!submit && !!messageId && complete && !live && !streaming && !answered;
}

// --- 部品 ---------------------------------------------------------------------------------

const ChoiceView: ComponentRenderer<ChoiceInput> = ({ props }) => {
  const question = (props.question || '').trim();
  const options = normalizeOptions(props.options);
  const { utterances, submit } = useContext(ShapeAnswerContext);
  const { messageId, part } = useContext(ShapeMetaContext);
  const [send, setSend] = useState<SendState>({ status: 'idle' });
  // 答えた状態の根拠は部屋の記録（照合情報つきの保存済み発言）だけ。saved は記録が画面に届くまでの保険
  const recorded = messageId ? findChoiceAnswer(utterances, messageId, part) : null;
  const answer = recorded ?? (send.status === 'saved' ? send.value : null);
  const canAnswer = useCanAnswer(!!answer);
  const disabled = !canAnswer || send.status === 'sending';
  const choose = (o: string) => {
    if (disabled || !submit || !messageId) return;
    setSend({ status: 'sending', value: o });
    submit(choiceAnswerText(question, o), { message_id: messageId, part, kind: 'choice', value: o, question })
      .then(() => setSend({ status: 'saved', value: o }))
      .catch(() => setSend({ status: 'failed', value: o }));
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
      {send.status === 'failed' ? <Failed text={SEND_FAILED} /> : null}
    </div>
  );
};

const InputView: ComponentRenderer<InputInput> = ({ props }) => {
  const label = (props.label || '').trim();
  const isNumber = props.kind === 'number';
  const unit = props.unit || '';
  const { utterances, submit } = useContext(ShapeAnswerContext);
  const { messageId, part } = useContext(ShapeMetaContext);
  const inputId = useId();
  const [value, setValue] = useState('');
  const [send, setSend] = useState<SendState>({ status: 'idle' });
  const recorded = messageId ? findInputAnswer(utterances, messageId, part) : null;
  const answer = recorded ?? (send.status === 'saved' ? send.value : null);
  const canAnswer = useCanAnswer(!!answer);
  const disabled = !canAnswer || send.status === 'sending';
  const doSend = () => {
    const v = value.trim();
    if (disabled || !v || !submit || !messageId) return;
    const shown = inputAnswerValue(label, v, isNumber ? unit : undefined);
    setSend({ status: 'sending', value: shown });
    submit(inputAnswerText(label, v, isNumber ? unit : undefined), { message_id: messageId, part, kind: 'input', value: shown, question: label })
      .then(() => setSend({ status: 'saved', value: shown }))
      .catch(() => setSend({ status: 'failed', value: shown }));   // 入力した値はそのまま残す
  };
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
            onChange={(e) => setValue(e.target.value)}
            disabled={disabled}
            placeholder={props.placeholder || ''}
            aria-invalid={send.status === 'failed' ? true : undefined}
            aria-describedby={send.status === 'failed' ? `${inputId}-error` : undefined}
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
      {send.status === 'failed' ? <div id={`${inputId}-error`}><Failed text={SEND_FAILED} /></div> : null}
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
