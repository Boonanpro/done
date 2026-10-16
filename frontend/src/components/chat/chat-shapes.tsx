'use client';

/**
 * ダンの返事の中の「部品」（OpenUI Lang の ```openui-lang ブロック）を描く。
 *
 * - 部品の定義（名前・引数）は lib/chat-shapes/schema.ts。ここでは見た目（React）を付けて
 *   OpenUI の部品一覧（library）にする。
 * - 描くのは @openuidev/react-lang の Renderer。生成の途中（閉じ ``` が無い）でも
 *   届いた分から描き（isStreaming）、その間は押せない。
 * - 選択ボタンと入力欄の答えは、確認カードと同じ経路で「本人の発言」として部屋に送る
 *   （ShapeAnswerProvider の submit = project-chat-panel の answerInRoom）。
 *   答えた状態は部屋の記録（その部品より後の本人の発言）から判定するので、再読み込みしても残る。
 * - 描画で例外が起きても、その部品だけを元のコードブロック（文章）に戻し、画面全体は落とさない。
 */
import {
  Component, createContext, memo, useCallback, useContext, useMemo, useState, type ReactNode,
} from 'react';
import {
  Renderer, createLibrary, defineComponent, useIsStreaming, type ComponentRenderer, type ParseResult,
} from '@openuidev/react-lang';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Check, Send } from 'lucide-react';

import {
  ChartProps, ChoiceProps, CompareProps, InputProps, StepsProps,
  type ChartInput, type ChoiceInput, type CompareInput, type InputInput, type StepsInput,
} from '@/lib/chat-shapes/schema';
import {
  choiceAnswerText, findChoiceAnswer, findInputAnswer, inputAnswerText, type UserUtterance,
} from '@/lib/chat-shapes/answers';

// --- 答えの経路（部屋の本人の発言と、発言を送る関数） -------------------------------------

type ShapeAnswerContextValue = {
  /** 部屋にある本人の発言（新しい順でも古い順でもよい）。答えた状態の判定に使う */
  utterances: UserUtterance[];
  /** 本人の発言として部屋へ送る（確認カードと同じ経路）。無ければ答えられない（閲覧だけ） */
  submit: ((text: string) => void) | null;
};

const ShapeAnswerContext = createContext<ShapeAnswerContextValue>({ utterances: [], submit: null });

type UtteranceSource = { sender_type: string; content: string | null; created_at: string };

export function ShapeAnswerProvider({
  messages, submit, children,
}: { messages: UtteranceSource[]; submit: ((text: string) => void) | null; children: ReactNode }) {
  const utterances = useMemo<UserUtterance[]>(
    () => messages
      .filter((m) => m.sender_type === 'human' && (m.content || '').trim())
      .map((m) => ({ text: m.content || '', at: Date.parse(m.created_at) || 0 })),
    [messages],
  );
  const value = useMemo(() => ({ utterances, submit }), [utterances, submit]);
  return <ShapeAnswerContext.Provider value={value}>{children}</ShapeAnswerContext.Provider>;
}

/** 1つの部品ブロックの素性: いつの返事か（これより後の発言だけが答え）、生成の途中か */
const ShapeMetaContext = createContext<{ askedAt: number; live: boolean }>({ askedAt: 0, live: false });

// --- 共通の見た目 --------------------------------------------------------------------------

const CARD = 'my-2 w-full max-w-[560px] rounded-xl border border-border bg-card p-3 shadow-sm';
const CHOICE_BTN = 'rounded-lg border px-3 py-1.5 text-left text-sm transition-colors disabled:cursor-default';

function Answered({ text }: { text: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <Check className="h-3.5 w-3.5" />{text}
    </span>
  );
}

// --- 部品 ---------------------------------------------------------------------------------

const ChoiceView: ComponentRenderer<ChoiceInput> = ({ props }) => {
  const question = props.question || '';
  const options = (props.options || []).filter((o): o is string => typeof o === 'string' && !!o.trim());
  const streaming = useIsStreaming();
  const { utterances, submit } = useContext(ShapeAnswerContext);
  const { askedAt, live } = useContext(ShapeMetaContext);
  const [picked, setPicked] = useState<string | null>(null);
  const recorded = findChoiceAnswer(utterances, question, options, askedAt);
  const answer = recorded ?? picked;
  const disabled = streaming || live || !!answer || !submit;
  const choose = (o: string) => {
    if (disabled) return;
    setPicked(o);
    submit?.(choiceAnswerText(question, o));
  };
  return (
    <div className={CARD} data-shape="Choice" data-answered={answer ? 'true' : 'false'}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-semibold leading-snug">{question}</div>
        {answer ? <Answered text="答えました" /> : null}
      </div>
      <div className="mt-2 flex flex-col gap-1.5">
        {options.map((o) => (
          <button
            key={o} type="button" disabled={disabled} onClick={() => choose(o)}
            aria-pressed={answer === o}
            className={`${CHOICE_BTN} ${answer === o ? 'border-primary bg-primary/10 font-medium' : answer ? 'border-border opacity-50' : 'border-border hover:bg-muted'}`}
          >
            {o}
          </button>
        ))}
        {options.length === 0 ? <div className="h-8 animate-pulse rounded-lg bg-muted/40" /> : null}
      </div>
    </div>
  );
};

const InputView: ComponentRenderer<InputInput> = ({ props }) => {
  const label = props.label || '';
  const isNumber = props.kind === 'number';
  const unit = props.unit || '';
  const streaming = useIsStreaming();
  const { utterances, submit } = useContext(ShapeAnswerContext);
  const { askedAt, live } = useContext(ShapeMetaContext);
  const [value, setValue] = useState('');
  const [sent, setSent] = useState<string | null>(null);
  const recorded = findInputAnswer(utterances, label, askedAt);
  const answer = recorded ?? sent;
  const disabled = streaming || live || !!answer || !submit;
  const send = () => {
    const v = value.trim();
    if (disabled || !v) return;
    const text = inputAnswerText(label, v, isNumber ? unit : undefined);
    setSent(text.slice(text.indexOf(' → ') + 3));
    submit?.(text);
  };
  return (
    <div className={CARD} data-shape="Input" data-answered={answer ? 'true' : 'false'}>
      <div className="flex items-start justify-between gap-2">
        <label className="text-sm font-semibold leading-snug">{label}</label>
        {answer ? <Answered text={`答えました: ${answer}`} /> : null}
      </div>
      {!answer ? (
        <form
          className="mt-2 flex items-center gap-2"
          onSubmit={(e) => { e.preventDefault(); send(); }}
        >
          <input
            type={isNumber ? 'number' : 'text'}
            inputMode={isNumber ? 'decimal' : 'text'}
            step={isNumber ? 'any' : undefined}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={disabled}
            placeholder={props.placeholder || ''}
            className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-sm outline-none focus-visible:border-ring disabled:opacity-60"
          />
          {isNumber && unit ? <span className="shrink-0 text-sm text-muted-foreground">{unit}</span> : null}
          <button
            type="submit" disabled={disabled || !value.trim()}
            className="inline-flex h-9 shrink-0 items-center gap-1 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Send className="h-3.5 w-3.5" />送る
          </button>
        </form>
      ) : null}
    </div>
  );
};

const CompareView: ComponentRenderer<CompareInput> = ({ props }) => {
  const columns = (props.columns || []).map((c) => (typeof c === 'string' ? c : ''));
  const rows = (props.rows || []).filter(Array.isArray) as string[][];
  return (
    <div className={`${CARD} overflow-x-auto p-0`} data-shape="Compare">
      {props.caption ? <div className="px-3 pt-2.5 text-sm font-semibold">{props.caption}</div> : null}
      <table className="w-full text-sm">
        {columns.length > 0 ? (
          <thead>
            <tr className="border-b border-border">
              {columns.map((c, i) => (
                <th key={i} className={`px-3 py-2 text-left font-medium ${i === 0 ? 'text-muted-foreground' : ''}`}>{c}</th>
              ))}
            </tr>
          </thead>
        ) : null}
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="border-b border-border last:border-0">
              {(columns.length ? columns : r).map((_, ci) => (
                <td key={ci} className={`px-3 py-2 align-top ${ci === 0 ? 'whitespace-nowrap text-muted-foreground' : ''}`}>
                  {typeof r[ci] === 'string' ? r[ci] : ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const StepsView: ComponentRenderer<StepsInput> = ({ props }) => {
  const steps = (props.steps || []).filter((s): s is string => typeof s === 'string');
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

// 単色のテーマ（白のアクセント）に合わせ、系列は同じ色の濃さと線種で分ける
const SERIES_STYLE = [
  { color: 'var(--primary)', opacity: 1, dash: undefined },
  { color: 'var(--primary)', opacity: 0.55, dash: '6 3' },
  { color: 'var(--primary)', opacity: 0.3, dash: '2 3' },
  { color: 'var(--muted-foreground)', opacity: 0.8, dash: '4 2' },
];

const ChartView: ComponentRenderer<ChartInput> = ({ props }) => {
  const labels = (props.labels || []).map((l) => (typeof l === 'string' ? l : String(l ?? '')));
  const series = (props.series || []).filter((s) => s && typeof s === 'object' && Array.isArray(s.values));
  const unit = props.unit || '';
  const data = useMemo(
    () => labels.map((label, i) => {
      const row: Record<string, string | number> = { label };
      series.forEach((s, si) => {
        const v = s.values[i];
        row[s.name || `系列${si + 1}`] = typeof v === 'number' && Number.isFinite(v) ? v : 0;
      });
      return row;
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(labels), JSON.stringify(series)],
  );
  const fmt = (v: unknown) => `${typeof v === 'number' ? v.toLocaleString('ja-JP') : String(v ?? '')}${unit}`;
  const names = series.map((s, si) => s.name || `系列${si + 1}`);
  const common = {
    data,
    margin: { top: 8, right: 12, left: 0, bottom: 0 },
  };
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
            {props.kind === 'line' ? (
              <LineChart {...common}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" tick={axisStyle} axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={72} tickFormatter={(v) => fmt(v)} />
                <Tooltip {...tooltipStyle} formatter={(v) => fmt(v)} />
                {names.length > 1 ? <Legend wrapperStyle={{ fontSize: 12 }} /> : null}
                {names.map((n, i) => {
                  const st = SERIES_STYLE[i % SERIES_STYLE.length];
                  return (
                    <Line key={n} type="monotone" dataKey={n} stroke={st.color} strokeOpacity={st.opacity}
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
                {names.length > 1 ? <Legend wrapperStyle={{ fontSize: 12 }} /> : null}
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

// --- 1ブロックの描画（例外はその部品だけ文章に戻す） --------------------------------------------

class ShapeErrorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.warn('[chat-shapes] render failed; showing the block as text', error); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export const ShapeBlock = memo(function ShapeBlock({
  code, complete, askedAt, renderFallback,
}: {
  /** ```openui-lang ブロックの中身（途中まででもよい） */
  code: string;
  /** 閉じ ``` まで届いたか。false の間は生成中として扱い、押せない */
  complete: boolean;
  /** この返事の時刻（ms）。これより後の本人の発言だけを答えと見なす */
  askedAt: number;
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
  const meta = useMemo(() => ({ askedAt, live: !complete }), [askedAt, complete]);
  const parsed = parse && parse.forCode === trimmed ? parse : null;
  if (complete && (!trimmed || (parsed && !parsed.root))) {
    // 中身が無い／部品として読めない（知らない部品名、必須の引数が無い）: 文章として出す
    return <>{renderFallback(code)}</>;
  }
  return (
    <ShapeErrorBoundary fallback={renderFallback(code)}>
      <ShapeMetaContext.Provider value={meta}>
        <div className="not-prose" data-shape-block={complete ? 'complete' : 'streaming'}>
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
