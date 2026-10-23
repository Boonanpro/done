// スマホのアプリで、ダンの返事の中の部品（```openui-lang のブロック）を描く（2026-10-23。それまでは文章に直して出していた）。
//
// PC（frontend/src/components/chat/chat-shapes.tsx）と見た目と動きを同じにする（2026-10-23 本人「スマホとPCは差が無いように
// ちゃんと同じにしたい」）。決まりは PC と同じファイルの写しを使い、ここは描くだけ:
// - 読み手と完成時の検査: chat-shapes-plain.ts / chat-shapes-schema.ts（checkShapeProgram。欠けた部品は描かずに文章へ戻す）
// - 選択ボタン・入力欄の答えの送信の状態: chat-shapes-answer-sends.ts / chat-shapes-use-answer-send.ts（送れなかった時は
//   「送れませんでした。もう一度押してください」、分からない時は「確かめる」。送っています…で固まらない）
// - グラフの形: chat-shapes-chart-geometry.ts（折れ線と棒、負の値、欠けた値を PC と同じ計算で描く）
// 写しは frontend/scripts/sync-mobile-chat-shapes.mjs が作る。
// - 写真はダンのファイル（/api/v1/files/…）と https:// の画像だけ（PC の safeImageUrl と同じ範囲。アプリの URL 読みは
//   ブラウザと違うので、ここで同じ範囲を確かめる）。ボタンの行き先は safeLinkUrl を通った物だけ
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import Svg, { Circle, G, Line, Path, Rect, Text as SvgText } from 'react-native-svg';

import { ShapeNode, readLook, safeColor, safeLinkUrl, siteFilePath } from './chat-shapes-plain';
import { ANSWER_VALUE_MAX, SHAPE_SPECS, checkShapeProgram, choiceOptions } from './chat-shapes-schema';
import {
  choiceAnswerText, findChoiceAnswer, findInputAnswer, inputAnswerText, inputAnswerValue, type UserUtterance,
} from './chat-shapes-answers';
import type { AskSaved, SubmitAnswer } from './chat-shapes-answer-sends';
import {
  CHECK_BUTTON, CHECKING_TEXT, SEND_FAILED, SEND_UNKNOWN_AGAIN, SEND_UNKNOWN_TEXT, SEND_VERIFYING, SENDING_TEXT, START_UNSURE, TOO_LONG,
  canAnswer, useAnswerSend, type AnswerEnv, type SendState,
} from './chat-shapes-use-answer-send';
import { CHART_HEIGHT, chartGeometry } from './chat-shapes-chart-geometry';

/** 部屋の側から渡す物: 本人の発言（答えた記録）・答えを送る・送ったか聞き直す・本人・部屋・リンクを開く・写真の URL */
export type ShapeRoom = {
  utterances: UserUtterance[];
  submit: SubmitAnswer | null;
  askSaved: AskSaved | null;
  ownerId: string | null;
  roomId: string | null;
  openUrl: (url: string) => void;
  /** ダンのファイルの道（/api/v1/files/…）をアプリが読める URL に */
  siteUrl: (path: string) => string;
};
export const ShapeRoomContext = createContext<ShapeRoom>({
  utterances: [], submit: null, askSaved: null, ownerId: null, roomId: null, openUrl: () => {}, siteUrl: (p) => p,
});
/** 描いている吹き出しの返事の id（保存済みのダンの返事だけ。無ければ答えられない） */
export const ShapeMessageContext = createContext<string | null>(null);
/** このブロックの部品の鍵（partKeys） */
const PartContext = createContext<string>('');
/** 組み合わせの中か（中の部品は自分の枠を付けない） */
const InsideContext = createContext(false);

/** 1つのブロックを描けるか（PC と同じ checkShapeProgram）。描けなければ null（呼び出し側は文章に戻す） */
export function readShapeBlock(code: string): ShapeNode | null {
  const r = checkShapeProgram(code);
  return r.ok ? r.root : null;
}

/** 位置引数を部品定義の名前へ（schema.ts の zod の shape の順。PC の lang-core と同じ当て方） */
const propsOf = (n: ShapeNode): Record<string, unknown> => {
  const spec = SHAPE_SPECS.find((x) => x.name === n.name);
  const keys = spec ? Object.keys(spec.props.shape) : [];
  return Object.fromEntries(keys.map((k, i) => [k, n.args[i]]));
};

function useAnswerEnv(): AnswerEnv {
  const room = useContext(ShapeRoomContext);
  const messageId = useContext(ShapeMessageContext);
  const part = useContext(PartContext);
  return { utterances: room.utterances, submit: room.submit, askSaved: room.askSaved, ownerId: room.ownerId, roomId: room.roomId, messageId, part };
}

/** 画像の URL（PC の safeImageUrl と同じ範囲: ダンのファイルの道か、利用者名の無い https://） */
function imageUrl(src: unknown, siteUrl: (p: string) => string): string | null {
  const s = typeof src === 'string' ? src.trim() : '';
  if (!s || s.length > 2048) return null;
  if (siteFilePath(s)) return siteUrl(s);
  return /^https:\/\/[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*(?::\d{1,5})?(?:\/[^\s\\]*)?$/.test(s) ? s : null;
}

const str = (v: unknown) => (typeof v === 'string' ? v : '');
const num = (v: unknown) => (typeof v === 'number' ? v.toLocaleString('ja-JP') : str(v));

function useImageUrl(src: unknown): string | null {
  const { siteUrl } = useContext(ShapeRoomContext);
  return imageUrl(src, siteUrl);
}

function Photo({ src, ratio }: { src: unknown; ratio: number }) {
  const uri = useImageUrl(src);
  const [broken, setBroken] = useState(false);
  if (!uri || broken) return null;
  return <Image source={{ uri }} onError={() => setBroken(true)} style={[styles.photo, { aspectRatio: ratio }]} resizeMode="cover" />;
}

function Box({ children, flat, framed }: { children: ReactNode; flat?: boolean; framed?: boolean }) {
  const inside = useContext(InsideContext);
  // 組み合わせの中のカードは細い枠だけ（外のカードと区別できるように）
  if (inside && framed) return <View style={styles.inner}>{children}</View>;
  return <View style={inside || flat ? styles.flat : styles.card}>{children}</View>;
}

/** 横並びの中で幅を分け合う部品（Web の chat-shapes.tsx WIDE と同じ） */
const WIDE = new Set(['Card', 'Column', 'Compare', 'Chart', 'Steps', 'Facts']);

function Children({ items, row = false }: { items: unknown; row?: boolean }) {
  const list = Array.isArray(items) ? items : [];
  return (
    <InsideContext.Provider value={true}>
      {list.map((c, i) => (typeof c === 'string' ? <Text key={i} style={styles.text}>{c}</Text>
        : c instanceof ShapeNode ? (row && WIDE.has(c.name) ? <View key={i} style={styles.wide}><Node node={c} /></View> : <Node key={i} node={c} />)
        : null))}
    </InsideContext.Provider>
  );
}

const TONE: Record<string, string> = { good: '#1f7a4d', warn: '#9a6400', bad: '#c0442e', info: '#2a6f9e' };
const TONE_BG: Record<string, string> = { good: 'rgba(31,122,77,0.10)', warn: 'rgba(154,100,0,0.10)', bad: 'rgba(192,68,46,0.10)', info: 'rgba(42,111,158,0.10)' };

/** 送れなかった・分からない時の知らせ（PC の SendProblem と同じ文と動き） */
function SendProblem({ send, answered, recheck }: { send: SendState; answered: boolean; recheck: () => void }) {
  if (answered) return null;
  if (send.status === 'unknown' && send.verifying) {
    return <View style={styles.problemRow}><ActivityIndicator size="small" color="#6b7a72" /><Text style={styles.muted}>{SEND_VERIFYING}</Text></View>;
  }
  if (send.status === 'unknown') {
    return (
      <View style={styles.problemRow}>
        <Text style={styles.problem}>{send.again ? SEND_UNKNOWN_AGAIN : SEND_UNKNOWN_TEXT}</Text>
        <Pressable onPress={recheck} disabled={!!send.checking} style={styles.checkBtn}><Text style={styles.checkText}>{send.checking ? CHECKING_TEXT : CHECK_BUTTON}</Text></Pressable>
      </View>
    );
  }
  if (send.status === 'failed') return <Text style={styles.problem}>{send.reason === 'too long' ? TOO_LONG : SEND_FAILED}</Text>;
  return null;
}

/** 答えは保存されたが、ダンが読み始めたと確かめられなかった（PC の StartProblem と同じ） */
function StartProblem({ show, checking, recheck }: { show: boolean; checking: boolean; recheck: () => void }) {
  if (!show) return null;
  return (
    <View style={styles.problemRow}>
      <Text style={styles.problem}>{START_UNSURE}</Text>
      <Pressable onPress={recheck} disabled={checking} style={styles.checkBtn}><Text style={styles.checkText}>{checking ? CHECKING_TEXT : CHECK_BUTTON}</Text></Pressable>
    </View>
  );
}

function OptionImage({ uri }: { uri: string }) {
  const [broken, setBroken] = useState(false);
  if (broken) return null;
  return <Image source={{ uri }} onError={() => setBroken(true)} style={styles.optionImage} resizeMode="contain" />;
}

function ChoiceNode({ p }: { p: Record<string, unknown> }) {
  const env = useAnswerEnv();
  const { siteUrl } = useContext(ShapeRoomContext);
  const question = (typeof p.question === 'string' ? p.question : '').trim();
  // 名前と色は PC と同じ整え方（choiceOptions）。写真は元の値から、PC と同じ範囲だけ
  const raw = Array.isArray(p.options) ? p.options : [];
  const images = new Map<string, string>();
  for (const o of raw) {
    if (o && typeof o === 'object' && typeof (o as { label?: unknown }).label === 'string') {
      const u = imageUrl((o as { image?: unknown }).image, siteUrl);
      if (u) images.set((o as { label: string }).label.replace(/\s+/g, ' ').trim(), u);
    }
  }
  const options = choiceOptions(raw);
  const cards = options.some((o) => images.has(o.label));
  const recorded = env.messageId ? findChoiceAnswer(env.utterances, env.messageId, env.part) : null;
  const { send, answer, run, recheck, startUnsure, checking } = useAnswerSend(env, recorded);
  const can = canAnswer(env, { complete: true, live: false, streaming: false, answered: !!answer });
  const disabled = !can || send.status === 'sending' || send.status === 'unknown';
  const choose = (o: string) => {
    if (disabled || !env.messageId) return;
    run(choiceAnswerText(question, o), { message_id: env.messageId, part: env.part, kind: 'choice', value: o, question }, o);
  };
  return (
    <Box>
      <View style={styles.headRow}>
        <Text style={[styles.question, { flex: 1 }]}>{question}</Text>
        {answer ? <Text style={styles.answered}>✓ 答えました</Text> : send.status === 'sending' ? <Text style={styles.answered}>{SENDING_TEXT}</Text> : null}
      </View>
      <View style={cards ? styles.optionGrid : styles.options}>
        {options.map((o) => {
          const picked = answer === o.label;
          const sending = send.status === 'sending' && send.value === o.label;
          const failedPick = send.status === 'failed' && send.value === o.label;
          const image = images.get(o.label);
          return (
            <Pressable
              key={o.label}
              disabled={disabled}
              onPress={() => choose(o.label)}
              accessibilityState={{ selected: picked, disabled }}
              style={[cards ? styles.optionCard : styles.option, picked && styles.optionOn, !!answer && !picked && styles.optionDim, failedPick && styles.optionFailed]}
            >
              {image ? <OptionImage uri={image} /> : null}
              <View style={styles.optionLabel}>
                {sending ? <ActivityIndicator size="small" color="#245e49" /> : null}
                {o.color ? <View style={[styles.swatch, { backgroundColor: o.color }]} /> : null}
                <Text style={[styles.optionText, picked && styles.optionTextOn]}>{o.label}</Text>
              </View>
            </Pressable>
          );
        })}
      </View>
      <SendProblem send={send} answered={!!answer} recheck={recheck} />
      <StartProblem show={!!answer && startUnsure} checking={checking} recheck={recheck} />
    </Box>
  );
}

function InputNode({ p }: { p: Record<string, unknown> }) {
  const env = useAnswerEnv();
  const label = (typeof p.label === 'string' ? p.label : '').trim();
  const isNumber = p.kind === 'number';
  const unit = typeof p.unit === 'string' ? p.unit : '';
  const recorded = env.messageId ? findInputAnswer(env.utterances, env.messageId, env.part) : null;
  const { send, setTooLong, answer, run, recheck, raw, startUnsure, checking } = useAnswerSend(env, recorded);
  const [value, setValue] = useState(() => raw ?? '');
  const can = canAnswer(env, { complete: true, live: false, streaming: false, answered: !!answer });
  const disabled = !can || send.status === 'sending' || send.status === 'unknown';
  const maxLength = Math.max(1, ANSWER_VALUE_MAX - (isNumber ? unit.length : 0));
  const doSend = () => {
    const v = value.trim();
    if (disabled || !v || !env.messageId) return;
    const shown = inputAnswerValue(label, v, isNumber ? unit : undefined);
    if (shown.length > ANSWER_VALUE_MAX) { setTooLong(shown); return; }
    run(inputAnswerText(label, v, isNumber ? unit : undefined), { message_id: env.messageId, part: env.part, kind: 'input', value: shown, question: label }, shown, v);
  };
  return (
    <Box>
      <View style={styles.headRow}>
        <Text style={[styles.question, { flex: 1 }]}>{label}</Text>
        {answer ? <Text style={styles.answered}>✓ 答えました: {answer}</Text> : null}
      </View>
      {!answer ? (
        <View style={styles.inputRow}>
          <TextInput
            value={value}
            onChangeText={setValue}
            editable={!disabled}
            maxLength={maxLength}
            placeholder={typeof p.placeholder === 'string' ? p.placeholder : ''}
            keyboardType={isNumber ? 'decimal-pad' : 'default'}
            onSubmitEditing={doSend}
            style={[styles.input, disabled && styles.optionDim]}
          />
          {isNumber && unit ? <Text style={styles.unit}>{unit}</Text> : null}
          <Pressable onPress={doSend} disabled={disabled || !value.trim()} style={[styles.sendBtn, (disabled || !value.trim()) && styles.optionDim]}>
            <Text style={styles.sendText}>{send.status === 'sending' ? '送っています' : '送る'}</Text>
          </Pressable>
        </View>
      ) : null}
      <SendProblem send={send} answered={!!answer} recheck={recheck} />
      <StartProblem show={!!answer && startUnsure} checking={checking} recheck={recheck} />
    </Box>
  );
}

function CompareNode({ p }: { p: Record<string, unknown> }) {
  const cols = (Array.isArray(p.columns) ? p.columns : []).map((c) => readLook(c));
  const rows = (Array.isArray(p.rows) ? p.rows : []).filter(Array.isArray) as unknown[][];
  const cell = (c: ReturnType<typeof readLook>, head: boolean, key: string) => (
    <View key={key} style={[styles.cell, head && styles.headCell]}>
      {c?.color && safeColor(c.color) ? <View style={[styles.swatch, { backgroundColor: safeColor(c.color)! }]} /> : null}
      <Text style={[styles.cellText, head && styles.headText]}>{c?.label ?? ''}</Text>
    </View>
  );
  return (
    <Box>
      {str(p.caption) ? <Text style={styles.question}>{str(p.caption)}</Text> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={styles.table}>
          <View style={styles.tr}>{cols.map((c, i) => cell(c, true, `h${i}`))}</View>
          {rows.map((r, ri) => (
            <View key={ri} style={styles.tr}>{cols.map((_, ci) => cell(readLook(r[ci] ?? ''), false, `${ri}-${ci}`))}</View>
          ))}
        </View>
      </ScrollView>
    </Box>
  );
}

const PRIMARY = '#245e49';
const MUTED = '#6b7a72';
const toneColor = (tone: 'primary' | 'muted') => (tone === 'primary' ? PRIMARY : MUTED);

/** グラフ（PC と同じ chartGeometry の計算結果を描く。折れ線・棒・負の値・欠けた値が PC と同じ形） */
function ChartNode({ p }: { p: Record<string, unknown> }) {
  const [width, setWidth] = useState(0);
  const geo = useMemo(() => (width > 0 ? chartGeometry(p, width) : null), [width, p]);
  return (
    <Box>
      {typeof p.title === 'string' && p.title ? <Text style={styles.question}>{p.title}</Text> : null}
      <View style={{ height: CHART_HEIGHT, alignSelf: 'stretch' }} onLayout={(e) => setWidth(Math.round(e.nativeEvent.layout.width))}>
        {geo ? (
          <Svg width={geo.width} height={geo.height}>
            {geo.yTicks.map((t) => (
              <G key={t.label}>
                <Line x1={geo.plot.x} x2={geo.plot.x + geo.plot.w} y1={t.y} y2={t.y} stroke="#dbe2da" strokeDasharray={t.zero ? undefined : '3 3'} strokeWidth={t.zero ? 1.2 : 1} />
                <SvgText x={geo.plot.x - 6} y={t.y + 4} textAnchor="end" fontSize={11} fill={MUTED}>{t.label}</SvgText>
              </G>
            ))}
            {geo.xLabels.map((l, i) => (
              <SvgText key={`${l.label}-${i}`} x={l.x} y={geo.plot.y + geo.plot.h + 16} textAnchor="middle" fontSize={11} fill={MUTED}>{l.label}</SvgText>
            ))}
            {geo.series.map((s) => (geo.kind === 'bar'
              ? s.bars.map((b, i) => <Rect key={`${s.name}-${i}`} x={b.x} y={b.y} width={b.w} height={b.h} rx={3} fill={toneColor(s.style.tone)} fillOpacity={s.style.opacity} />)
              : (
                <G key={s.name}>
                  <Path d={s.path} fill="none" stroke={toneColor(s.style.tone)} strokeOpacity={s.style.opacity} strokeWidth={2} strokeDasharray={s.style.dash ?? undefined} />
                  {s.points.map((pt, i) => <Circle key={i} cx={pt.x} cy={pt.y} r={3} fill={toneColor(s.style.tone)} fillOpacity={s.style.opacity} />)}
                </G>
              )))}
          </Svg>
        ) : null}
      </View>
      {geo && geo.series.length > 1 ? (
        <View style={styles.legend}>
          {geo.series.map((s) => (
            <View key={s.name} style={styles.legendItem}>
              {geo.kind === 'bar'
                ? <View style={{ width: 12, height: 12, borderRadius: 2, backgroundColor: toneColor(s.style.tone), opacity: s.style.opacity }} />
                : <Svg width={22} height={8}><Line x1={0} y1={4} x2={22} y2={4} stroke={toneColor(s.style.tone)} strokeOpacity={s.style.opacity} strokeWidth={2} strokeDasharray={s.style.dash ?? undefined} /></Svg>}
              <Text style={styles.small}>{s.name}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </Box>
  );
}

function Node({ node }: { node: ShapeNode }) {
  const p = propsOf(node);
  const { openUrl } = useContext(ShapeRoomContext);
  switch (node.name) {
    case 'Card':
      return (
        <Box framed>
          <Photo src={p.image} ratio={16 / 9} />
          {str(p.title) ? <Text style={styles.cardTitle}>{str(p.title)}</Text> : null}
          <Children items={p.children} />
        </Box>
      );
    case 'Row': {
      const justify = p.align === 'center' ? 'center' : p.align === 'between' ? 'space-between' : 'flex-start';
      return <View style={[styles.row, { justifyContent: justify }]}><Children items={p.children} row /></View>;
    }
    case 'Column':
      return <View style={styles.column}><Children items={p.children} /></View>;
    case 'Heading':
      return (
        <View>
          <Text style={styles.heading}>{str(p.text)}</Text>
          {str(p.sub) ? <Text style={styles.sub}>{str(p.sub)}</Text> : null}
        </View>
      );
    case 'Text':
      return <Text selectable style={[styles.text, p.tone === 'muted' && styles.muted, p.tone === 'strong' && styles.strong, p.tone === 'small' && styles.small]}>{str(p.text)}</Text>;
    case 'Image':
      return <Photo src={p.src} ratio={p.shape === 'square' ? 1 : p.shape === 'tall' ? 3 / 4 : 16 / 9} />;
    case 'Stat':
      return (
        <View style={styles.stat}>
          <Text style={styles.small}>{str(p.label)}</Text>
          <Text style={[styles.statValue, !!TONE[str(p.tone)] && { color: TONE[str(p.tone)] }]}>
            {num(p.value)}{str(p.unit) ? <Text style={styles.statUnit}>{str(p.unit)}</Text> : null}
          </Text>
          {str(p.note) ? <Text style={styles.small}>{str(p.note)}</Text> : null}
        </View>
      );
    case 'Facts':
      return (
        <View style={styles.facts}>
          {(Array.isArray(p.items) ? p.items : []).map((x, i) => {
            const o = (x && typeof x === 'object' ? x : {}) as { label?: unknown; value?: unknown };
            return (
              <View key={i} style={styles.fact}>
                <Text style={styles.factLabel}>{str(o.label)}</Text>
                <Text selectable style={styles.factValue}>{num(o.value)}</Text>
              </View>
            );
          })}
        </View>
      );
    case 'Badge': {
      const t = str(p.tone);
      return (
        <View style={[styles.badge, !!TONE_BG[t] && { backgroundColor: TONE_BG[t], borderColor: 'transparent' }]}>
          <Text style={[styles.badgeText, !!TONE[t] && { color: TONE[t] }]}>{str(p.text)}</Text>
        </View>
      );
    }
    case 'Button': {
      const url = safeLinkUrl(p.url);
      return (
        <Pressable disabled={!url} onPress={() => url && openUrl(url)} style={[styles.button, !url && styles.buttonOff]}>
          <Text style={[styles.buttonText, !url && styles.buttonTextOff]}>{str(p.label)}</Text>
        </Pressable>
      );
    }
    case 'Divider':
      return <View style={styles.divider} />;
    case 'Steps': {
      const steps = (Array.isArray(p.steps) ? p.steps : []).map(str).filter((s) => s.trim());
      return (
        <Box>
          {str(p.title) ? <Text style={styles.question}>{str(p.title)}</Text> : null}
          {steps.map((s, i) => (
            <View key={i} style={styles.step}>
              <View style={styles.stepNo}><Text style={styles.stepNoText}>{i + 1}</Text></View>
              <Text selectable style={[styles.text, { flex: 1 }]}>{s}</Text>
            </View>
          ))}
        </Box>
      );
    }
    case 'Choice':
      return <ChoiceNode p={p} />;
    case 'Input':
      return <InputNode p={p} />;
    case 'Compare':
      return <CompareNode p={p} />;
    case 'Chart':
      return <ChartNode p={p} />;
    default:
      return null;
  }
}

/** 1つのブロック。part は部品の鍵（partKeys）。描けなければ null（呼び出し側が文章に戻す） */
export function ShapeBlockView({ code, part }: { code: string; part: string }) {
  const root = useMemo(() => readShapeBlock(code), [code]);
  if (!root) return null;
  return (
    <PartContext.Provider value={part}>
      <View style={styles.block}><Node node={root} /></View>
    </PartContext.Provider>
  );
}

const styles = StyleSheet.create({
  block: { marginVertical: 4, alignSelf: 'stretch' },
  card: { borderWidth: 1, borderColor: '#dbe2da', borderRadius: 12, padding: 12, gap: 8, backgroundColor: '#fbfcfa', alignSelf: 'stretch' },
  flat: { gap: 6, alignSelf: 'stretch' },
  inner: { borderWidth: 1, borderColor: '#dbe2da', borderRadius: 10, padding: 10, gap: 6, alignSelf: 'stretch', flexGrow: 1 },
  wide: { flexGrow: 1, flexBasis: 150, minWidth: 0 },
  cardTitle: { fontSize: 14, fontWeight: '700', color: '#1f2724' },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', columnGap: 16, rowGap: 8 },
  column: { gap: 8 },
  heading: { fontSize: 16, fontWeight: '700', color: '#1f2724' },
  sub: { fontSize: 13, color: '#59685f', marginTop: 1 },
  text: { fontSize: 15, lineHeight: 22, color: '#1f2724' },
  muted: { color: '#59685f', fontSize: 14 },
  strong: { fontWeight: '700' },
  small: { fontSize: 12, color: '#6b7a72' },
  photo: { width: '100%', borderRadius: 10, backgroundColor: '#eef2ee' },
  stat: { minWidth: 88 },
  statValue: { fontSize: 22, fontWeight: '700', color: '#1f2724', fontVariant: ['tabular-nums'] },
  statUnit: { fontSize: 14, fontWeight: '600' },
  facts: { gap: 4 },
  fact: { flexDirection: 'row', gap: 12 },
  factLabel: { fontSize: 14, color: '#6b7a72', minWidth: 64 },
  factValue: { fontSize: 14, color: '#1f2724', flex: 1 },
  badge: { borderWidth: 1, borderColor: '#dbe2da', backgroundColor: '#f1f4f1', borderRadius: 999, paddingHorizontal: 9, paddingVertical: 2, alignSelf: 'flex-start' },
  badgeText: { fontSize: 12, fontWeight: '600', color: '#59685f' },
  button: { backgroundColor: '#245e49', borderRadius: 10, paddingHorizontal: 14, paddingVertical: 9, alignSelf: 'flex-start' },
  buttonOff: { backgroundColor: 'transparent', borderWidth: 1, borderColor: '#dbe2da' },
  buttonText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  buttonTextOff: { color: '#6b7a72' },
  divider: { height: StyleSheet.hairlineWidth * 2, backgroundColor: '#dbe2da', alignSelf: 'stretch', marginVertical: 2 },
  question: { fontSize: 14, fontWeight: '700', color: '#1f2724' },
  options: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  option: { flexDirection: 'row', alignItems: 'center', gap: 6, borderWidth: 1, borderColor: '#b9c7bf', borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: '#fff' },
  optionOn: { backgroundColor: '#245e49', borderColor: '#245e49' },
  optionDim: { opacity: 0.55 },
  optionText: { fontSize: 14, color: '#1f2724' },
  optionTextOn: { color: '#fff', fontWeight: '600' },
  swatch: { width: 16, height: 16, borderRadius: 4, borderWidth: 1, borderColor: 'rgba(0,0,0,0.35)' },
  answered: { fontSize: 12, color: '#59685f' },
  headRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  problemRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  problem: { fontSize: 12, color: '#c0442e' },
  checkBtn: { borderWidth: 1, borderColor: '#dbe2da', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  checkText: { fontSize: 12, color: '#1f2724' },
  optionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  optionCard: { width: '47%', borderWidth: 1, borderColor: '#b9c7bf', borderRadius: 10, padding: 6, gap: 6, backgroundColor: '#fff' },
  optionImage: { width: '100%', aspectRatio: 4 / 3, borderRadius: 6, backgroundColor: '#eef2ee' },
  optionLabel: { flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 1 },
  optionFailed: { borderColor: 'rgba(192,68,46,0.6)' },
  legend: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', columnGap: 16, rowGap: 4 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  inputRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  input: { flex: 1, borderWidth: 1, borderColor: '#b9c7bf', borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8, fontSize: 15, backgroundColor: '#fff', color: '#1f2724' },
  unit: { fontSize: 14, color: '#59685f' },
  sendBtn: { backgroundColor: '#245e49', borderRadius: 10, paddingHorizontal: 14, paddingVertical: 9 },
  sendText: { color: '#fff', fontWeight: '600' },
  table: { borderWidth: 1, borderColor: 'rgba(110,120,115,0.35)', borderRadius: 8, overflow: 'hidden' },
  tr: { flexDirection: 'row' },
  cell: { width: 120, paddingHorizontal: 8, paddingVertical: 6, borderTopWidth: StyleSheet.hairlineWidth * 2, borderLeftWidth: StyleSheet.hairlineWidth * 2, borderColor: 'rgba(110,120,115,0.25)', flexDirection: 'row', alignItems: 'center', gap: 4 },
  headCell: { backgroundColor: 'rgba(36,94,73,0.08)' },
  cellText: { fontSize: 13, lineHeight: 19, color: '#1f2724', flexShrink: 1 },
  headText: { fontWeight: '700' },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  barLabel: { width: 64, fontSize: 12, color: '#59685f' },
  barLine: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  bar: { height: 10, borderRadius: 3 },
  barValue: { fontSize: 11, color: '#59685f' },
  step: { flexDirection: 'row', gap: 8, alignItems: 'flex-start' },
  stepNo: { width: 20, height: 20, borderRadius: 10, backgroundColor: 'rgba(36,94,73,0.12)', alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  stepNoText: { fontSize: 11, fontWeight: '700', color: '#245e49' },
});
