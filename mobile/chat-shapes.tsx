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
import { createContext, useCallback, useContext, useMemo, useState, type ComponentProps, type ReactNode } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import Svg, { Circle, G, Line, Path, Rect, Text as SvgText } from 'react-native-svg';

import { ShapeNode, readLook, safeColor, safeLinkUrl, siteFilePath } from './chat-shapes-plain';
import { ANSWER_VALUE_MAX, POINT_TITLE, SHAPE_SPECS, checkShapeProgram, choiceOptions, flowEdges, timeSeconds } from './chat-shapes-schema';
import { mapView, pinLabels } from './chat-shapes-map-geometry';
import { Ionicons } from '@expo/vector-icons';
import {
  choiceAnswerText, findChoiceAnswer, findInputAnswer, findLastPoint, inputAnswerText, inputAnswerValue, pointText, type UserUtterance,
} from './chat-shapes-answers';
import type { AskSaved, SubmitAnswer } from './chat-shapes-answer-sends';
import {
  CHECK_BUTTON, CHECKING_TEXT, SEND_FAILED, SEND_UNKNOWN_AGAIN, SEND_UNKNOWN_TEXT, SEND_VERIFYING, SENDING_TEXT, START_UNSURE, TOO_LONG,
  canAnswer, newSendId, useAnswerSend, type AnswerEnv, type SendState,
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
const WIDE = new Set(['Card', 'Column', 'Compare', 'Chart', 'Steps', 'Facts', 'Flow', 'Map', 'Item', 'Quote', 'Sources', 'Frames', 'BeforeAfter']);

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

/** 矢印でつなぐ図（PC の FlowView と同じ並べ方。アイコンは Ionicons に当てる） */
const FLOW_ICON: Record<string, ComponentProps<typeof Ionicons>['name']> = {
  person: 'person-outline', people: 'people-outline', phone: 'phone-portrait-outline', pc: 'desktop-outline', server: 'server-outline',
  database: 'server-outline', cloud: 'cloud-outline', mail: 'mail-outline', chat: 'chatbubble-outline', money: 'cash-outline', card: 'card-outline',
  bank: 'business-outline', doc: 'document-text-outline', calendar: 'calendar-outline', clock: 'time-outline', check: 'checkmark-circle-outline',
  warning: 'warning-outline', lock: 'lock-closed-outline', key: 'key-outline', shield: 'shield-outline', globe: 'globe-outline', home: 'home-outline',
  car: 'car-outline', train: 'train-outline', camera: 'camera-outline', mic: 'mic-outline', video: 'videocam-outline', bot: 'hardware-chip-outline',
  search: 'search-outline', tool: 'build-outline', chart: 'bar-chart-outline', box: 'cube-outline', truck: 'bus-outline', store: 'storefront-outline',
  flag: 'flag-outline', star: 'star-outline', heart: 'heart-outline', question: 'help-circle-outline', gear: 'settings-outline', image: 'image-outline',
  pin: 'location-outline', glasses: 'glasses-outline', ear: 'ear-outline', eye: 'eye-outline', file: 'document-outline', folder: 'folder-outline',
  link: 'link-outline', bolt: 'flash-outline',
};
const FLOW_TONE_BORDER: Record<string, string> = { now: '#2a6f9e', good: TONE.good, warn: TONE.warn, bad: TONE.bad };
function FlowNodeView({ p }: { p: Record<string, unknown> }) {
  const nodes = (Array.isArray(p.nodes) ? p.nodes : []) as { id: string; label: string; icon?: string; sub?: string; tone?: string }[];
  const edges = Array.isArray(p.edges) ? (p.edges as { from: string; to: string; label?: string }[]) : undefined;
  const { between, others } = flowEdges({ nodes, edges });
  const nameOf = (id: string) => nodes.find((n) => n.id === id)?.label || id;
  return (
    <Box>
      {str(p.title) ? <Text style={styles.question}>{str(p.title)}</Text> : null}
      <View style={styles.flow}>
        {nodes.map((n, i) => {
          const icon = n.icon ? FLOW_ICON[n.icon] : undefined;
          const edge = between.get(i);
          const now = n.tone === 'now';
          const border = FLOW_TONE_BORDER[str(n.tone)];
          return (
            <View key={`${n.id}-${i}`} style={styles.flowItem}>
              <View style={[styles.flowNode, !!border && { borderColor: border, borderWidth: now ? 2 : 1 }, now && styles.flowNow, !!TONE_BG[str(n.tone)] && { backgroundColor: TONE_BG[str(n.tone)] }]}>
                {icon ? <Ionicons name={icon} size={20} color={now ? '#2a6f9e' : '#5c6660'} /> : null}
                <Text style={styles.flowLabel}>{n.label}</Text>
                {n.sub ? <Text style={styles.flowSub}>{n.sub}</Text> : null}
              </View>
              {i < nodes.length - 1 ? (
                <View style={styles.flowArrow}>
                  {edge?.label ? <Text style={styles.flowEdgeLabel} numberOfLines={1}>{edge.label}</Text> : null}
                  {edge ? <Ionicons name="arrow-forward" size={18} color="#8a938d" /> : <View style={{ height: 18 }} />}
                </View>
              ) : null}
            </View>
          );
        })}
      </View>
      {others.length ? <Text style={styles.small}>{others.map((e) => `${nameOf(e.from)} → ${nameOf(e.to)}${e.label ? `（${e.label}）` : ''}`).join('　')}</Text> : null}
    </Box>
  );
}


// --- 本物の中身を見せる部品（2026-11-12。PC の chat-shapes.tsx と同じ形・同じ届き方）--------------------------
const NAVY = '#1f4e79';
const MARK_BG = 'rgba(255, 200, 0, 0.45)';

/** 押せる物（ピン・札・コマ）: 押すと本人の発言「<題> → <押した物>」として部屋へ（answer_to.kind 'point'。何度でも押せる） */
function usePoint(title: string) {
  const env = useAnswerEnv();
  const [mine, setMine] = useState<{ value: string; status: 'sending' | 'sent' | 'failed' } | null>(null);
  const recorded = env.messageId ? findLastPoint(env.utterances, env.messageId, env.part) : null;
  const can = !!env.submit && !!env.messageId && !!env.ownerId && !!env.roomId;
  const press = useCallback(async (value: string) => {
    if (!env.submit || !env.messageId) return;
    setMine({ value, status: 'sending' });
    try {
      await env.submit(pointText(title, value), { message_id: env.messageId, part: env.part, kind: 'point', value: value.slice(0, ANSWER_VALUE_MAX), question: title.slice(0, 200) }, newSendId());
      setMine({ value, status: 'sent' });
    } catch { setMine({ value, status: 'failed' }); }
  }, [env.submit, env.messageId, env.part, title]);
  const selected = mine?.value ?? recorded;
  const note = mine?.status === 'failed' ? '伝えられませんでした。もう一度押してください'
    : mine?.status === 'sending' ? '伝えています…' : selected ? `ダンに伝えました: ${selected}` : null;
  return { selected, note, failed: mine?.status === 'failed', press: can ? (v: string) => { void press(v); } : null };
}

function PointNote({ note, failed }: { note: string | null; failed: boolean }) {
  return note ? <Text style={failed ? styles.problem : styles.small}>{note}</Text> : null;
}

function hostOf(url: string | null): string {
  const m = url ? url.match(/^https?:\/\/([^/?#]+)/i) : null;
  return m ? m[1].replace(/^www\./, '') : '';
}

function SourceLine({ url, label }: { url: unknown; label: string }) {
  const { openUrl } = useContext(ShapeRoomContext);
  const safe = safeLinkUrl(url);
  return (
    <Pressable disabled={!safe} onPress={() => safe && openUrl(safe)} style={styles.sourceLine}>
      <Ionicons name="link-outline" size={14} color="#6b7a72" />
      {hostOf(safe) ? <Text style={styles.sourceHost}>{hostOf(safe)}</Text> : null}
      <Text numberOfLines={1} style={[styles.small, { flexShrink: 1 }]}>{label}</Text>
    </Pressable>
  );
}

function Marked({ text, marks }: { text: string; marks: unknown }) {
  const words = (Array.isArray(marks) ? marks : []).map(str).map((m) => m.trim()).filter((m) => m && text.includes(m));
  const out: ReactNode[] = [];
  let rest = text, k = 0;
  for (;;) {
    let best = -1, word = '';
    for (const w of words) { const i = rest.indexOf(w); if (i >= 0 && (best < 0 || i < best)) { best = i; word = w; } }
    if (best < 0) break;
    out.push(rest.slice(0, best), <Text key={k++} style={{ backgroundColor: MARK_BG }}>{word}</Text>);
    rest = rest.slice(best + word.length); words.splice(words.indexOf(word), 1);
  }
  out.push(rest);
  return <Text selectable style={styles.quoteText}>{out}</Text>;
}

/** 地図: PC と同じ計算（chat-shapes-map-geometry）でタイルを並べ、ピンを立てる。指でずらす代わりに ＋ − で寄る・引く */
function MapNode({ p }: { p: Record<string, unknown> }) {
  const places = (Array.isArray(p.places) ? p.places : []).filter((x): x is { label: string; lat: number; lng: number; sub?: string } =>
    !!x && typeof x === 'object' && typeof (x as { lat?: unknown }).lat === 'number' && typeof (x as { lng?: unknown }).lng === 'number');
  const h = p.here && typeof p.here === 'object' ? p.here as { lat?: unknown; lng?: unknown; label?: unknown } : null;
  const here = h && typeof h.lat === 'number' && typeof h.lng === 'number' ? { lat: h.lat, lng: h.lng } : null;
  const title = str(p.title).trim() || POINT_TITLE.Map;
  const point = usePoint(title);
  const [width, setWidth] = useState(0);
  const [zoomDelta, setZoomDelta] = useState(0);
  const height = Math.round(Math.min(320, Math.max(220, width * 0.72)));
  const view = width > 0 && places.length ? mapView(places, here, width, height, zoomDelta) : null;
  const labels = pinLabels(places.length);
  // 札の置き場所は PC と同じ決め方: 右、重なるなら左、それも重なるなら番号だけ（＋−のボタンにも重ねない）
  const placement = useMemo(() => {
    if (!view) return [];
    type B = { l: number; t: number; r: number; b: number };
    const taken: B[] = [{ l: width - 46, t: 0, r: width, b: 80 }];
    const hits = (a: B) => a.l < 2 || a.r > width - 2 || taken.some((q) => a.l < q.r && a.r > q.l && a.t < q.b && a.b > q.t);
    return places.map((pl, i) => {
      const at = view.points[i];
      const w = Math.min(170, 38 + [...pl.label].length * 14);
      const right = { l: at.left - 11, t: at.top - 14, r: at.left - 11 + w, b: at.top + 14 };
      const left = { l: at.left + 11 - w, t: at.top - 14, r: at.left + 11, b: at.top + 14 };
      const small = { l: at.left - 11, t: at.top - 14, r: at.left + 11, b: at.top + 14 };
      const pick = labels && !hits(right) ? { flip: false, label: true, box: right }
        : labels && !hits(left) ? { flip: true, label: true, box: left } : { flip: false, label: false, box: small };
      taken.push(pick.box);
      return pick;
    });
  }, [view, places, labels, width]);
  return (
    <Box>
      {str(p.title) ? <Text style={styles.question}>{str(p.title)}</Text> : null}
      <View onLayout={(e) => setWidth(Math.round(e.nativeEvent.layout.width))} style={[styles.map, { height }]}>
        {view ? view.tiles.map((t) => <Image key={t.key} source={{ uri: t.url }} style={{ position: 'absolute', left: t.left, top: t.top, width: 256, height: 256, opacity: 0.85 }} />) : null}
        {view?.here ? <View style={[styles.here, { left: view.here.left - 8, top: view.here.top - 8 }]} /> : null}
        {view ? places.map((pl, i) => {
          const at = view.points[i];
          const sel = point.selected === pl.label;
          const flip = !!placement[i]?.flip;
          const named = !!placement[i]?.label;
          return (
            <Pressable key={i} disabled={!point.press} onPress={() => point.press?.(pl.label)}
              style={[styles.pin, sel && styles.pinOn, flip ? { right: width - at.left - 11, flexDirection: 'row-reverse' } : { left: at.left - 11 }, { top: at.top - 13 }]}>
              <View style={styles.pinNo}><Text style={styles.pinNoText}>{i + 1}</Text></View>
              {named ? <Text numberOfLines={1} style={styles.pinText}>{pl.label}</Text> : null}
            </Pressable>
          );
        }) : null}
        <View style={styles.zoom}>
          <Pressable onPress={() => setZoomDelta((z) => z + 1)} style={styles.zoomBtn}><Ionicons name="add" size={18} color="#333" /></Pressable>
          <Pressable onPress={() => setZoomDelta((z) => z - 1)} style={[styles.zoomBtn, { borderTopWidth: 1, borderColor: '#dbe2da' }]}><Ionicons name="remove" size={18} color="#333" /></Pressable>
        </View>
        {view ? <Text style={styles.credit}>{view.credit}</Text> : null}
      </View>
      {places.map((pl, i) => (
        <Pressable key={i} disabled={!point.press} onPress={() => point.press?.(pl.label)} style={[styles.placeRow, point.selected === pl.label && { backgroundColor: MARK_BG }]}>
          <View style={styles.pinNo}><Text style={styles.pinNoText}>{i + 1}</Text></View>
          <Text style={[styles.text, { flexShrink: 1 }]}>{pl.label}{str(pl.sub) ? <Text style={styles.small}>{'　' + str(pl.sub)}</Text> : null}</Text>
        </Pressable>
      ))}
      <PointNote note={point.note} failed={point.failed} />
    </Box>
  );
}

function ItemNode({ p }: { p: Record<string, unknown> }) {
  const point = usePoint(POINT_TITLE.Item);
  const uri = useImageUrl(p.image);
  const [broken, setBroken] = useState(false);
  const title = str(p.title);
  const lines = (Array.isArray(p.lines) ? p.lines : []).map(str).filter((l) => l.trim());
  return (
    <View style={{ gap: 4, alignSelf: 'stretch' }}>
      <Pressable disabled={!point.press} onPress={() => point.press?.(title)} style={[styles.item, point.selected === title && styles.itemOn]}>
        {uri && !broken ? <Image source={{ uri }} onError={() => setBroken(true)} style={styles.itemPhoto} resizeMode="cover" /> : null}
        <View style={styles.itemBody}>
          <View style={{ flexDirection: 'row', gap: 6, alignItems: 'center' }}>
            {str(p.num) ? <View style={styles.pinNo}><Text style={styles.pinNoText}>{str(p.num)}</Text></View> : null}
            <Text style={[styles.cardTitle, { fontSize: 15, flexShrink: 1 }]}>{title}</Text>
          </View>
          {str(p.sub) ? <Text style={styles.small}>{str(p.sub)}</Text> : null}
          {lines.map((l, i) => <Text key={i} style={[styles.text, { fontSize: 13, lineHeight: 19 }]}>{l}</Text>)}
        </View>
      </Pressable>
      {safeLinkUrl(p.url) ? <SourceLine url={p.url} label="ページを開く" /> : null}
      <PointNote note={point.note} failed={point.failed} />
    </View>
  );
}

function QuoteNode({ p }: { p: Record<string, unknown> }) {
  const uri = useImageUrl(p.image);
  const [broken, setBroken] = useState(false);
  const [ratio, setRatio] = useState(3);
  return (
    <Box>
      {uri && !broken ? (
        <View style={styles.quoteImageBox}>
          <Image source={{ uri }} onError={() => setBroken(true)} onLoad={(e) => { const s = e.nativeEvent.source; if (s?.width && s?.height) setRatio(s.width / s.height); }}
            style={{ width: '100%', aspectRatio: ratio }} resizeMode="contain" />
        </View>
      ) : <View style={styles.quoteBar}><Marked text={str(p.text)} marks={p.mark} /></View>}
      <SourceLine url={p.url} label={str(p.source)} />
    </Box>
  );
}

function SourcesNode({ p }: { p: Record<string, unknown> }) {
  const { openUrl } = useContext(ShapeRoomContext);
  const items = (Array.isArray(p.items) ? p.items : []).filter((x): x is Record<string, unknown> => !!x && typeof x === 'object');
  return (
    <Box>
      <Text style={styles.small}>出どころ</Text>
      {items.map((x, i) => {
        const url = safeLinkUrl(x.url);
        return (
          <Pressable key={i} disabled={!url} onPress={() => url && openUrl(url)} style={styles.sourceRow}>
            <Text style={styles.sourceNo}>{i + 1}</Text>
            <View style={{ flex: 1 }}>
              <Text numberOfLines={1} style={[styles.text, { fontSize: 14, fontWeight: '600' }]}>{str(x.title)}</Text>
              <Text numberOfLines={1} style={styles.small}>{hostOf(url)}{str(x.note) ? `・${str(x.note)}` : ''}</Text>
            </View>
          </Pressable>
        );
      })}
    </Box>
  );
}

function FramesNode({ p }: { p: Record<string, unknown> }) {
  const title = str(p.title).trim() || POINT_TITLE.Frames;
  const point = usePoint(title);
  const { siteUrl } = useContext(ShapeRoomContext);
  const frames = (Array.isArray(p.frames) ? p.frames : []).filter((f): f is Record<string, unknown> => !!f && typeof f === 'object');
  const total = timeSeconds(p.length);
  const value = (f: Record<string, unknown>) => (str(f.label) ? `${str(f.time)}（${str(f.label)}）` : str(f.time));
  return (
    <Box>
      {str(p.title) ? <Text style={styles.question}>{str(p.title)}</Text> : null}
      <View style={styles.frameGrid}>
        {frames.map((f, i) => {
          const uri = imageUrl(f.src, siteUrl);
          const sel = point.selected === value(f);
          return (
            <Pressable key={i} disabled={!point.press} onPress={() => point.press?.(value(f))} style={[styles.frame, sel && styles.itemOn]}>
              {uri ? <Image source={{ uri }} style={{ width: '100%', aspectRatio: 16 / 9, backgroundColor: '#eef2ee' }} resizeMode="cover" /> : <View style={{ width: '100%', aspectRatio: 16 / 9, backgroundColor: '#eef2ee' }} />}
              <Text style={styles.frameTime}>{str(f.time)}</Text>
              {str(f.label) ? <Text numberOfLines={2} style={[styles.small, { padding: 6 }]}>{str(f.label)}</Text> : null}
            </Pressable>
          );
        })}
      </View>
      {total ? (
        <View style={styles.frameBar}>
          {frames.map((f, i) => { const t = timeSeconds(f.time); return t === null ? null : <View key={i} style={[styles.frameTick, { left: `${Math.min(100, (t / total) * 100)}%` }, point.selected === value(f) && { backgroundColor: '#e0a800', width: 4 }]} />; })}
        </View>
      ) : null}
      <PointNote note={point.note} failed={point.failed} />
    </Box>
  );
}

function BeforeAfterNode({ p }: { p: Record<string, unknown> }) {
  const labels = Array.isArray(p.labels) && p.labels.length === 2 ? p.labels.map(str) : ['前', '後'];
  return (
    <Box>
      <View style={{ flexDirection: 'row', gap: 8 }}>
        {[p.before, p.after].map((src, i) => (
          <View key={i} style={{ flex: 1, gap: 4 }}>
            <Text style={[styles.small, i ? { color: '#fff', backgroundColor: NAVY, alignSelf: 'flex-start', paddingHorizontal: 6, borderRadius: 4 } : null]}>{labels[i]}</Text>
            <Photo src={src} ratio={4 / 3} />
          </View>
        ))}
      </View>
      {str(p.caption) ? <Text style={styles.text}>{str(p.caption)}</Text> : null}
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
    case 'Flow':
      return <FlowNodeView p={p} />;
    case 'Map':
      return <MapNode p={p} />;
    case 'Item':
      return <ItemNode p={p} />;
    case 'Quote':
      return <QuoteNode p={p} />;
    case 'Sources':
      return <SourcesNode p={p} />;
    case 'Frames':
      return <FramesNode p={p} />;
    case 'BeforeAfter':
      return <BeforeAfterNode p={p} />;
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
  flow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'center', rowGap: 10 },
  flowItem: { flexDirection: 'row', alignItems: 'center' },
  flowNode: { minWidth: 84, maxWidth: 140, alignItems: 'center', gap: 3, borderWidth: 1, borderColor: '#dbe2da', backgroundColor: '#f6f8f5', borderRadius: 12, paddingHorizontal: 10, paddingVertical: 8 },
  flowNow: { backgroundColor: 'rgba(42,111,158,0.12)' },
  flowLabel: { fontSize: 13, fontWeight: '600', color: '#1f2724', textAlign: 'center' },
  flowSub: { fontSize: 10, color: '#6b746e', textAlign: 'center' },
  flowArrow: { width: 48, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 2 },
  flowEdgeLabel: { fontSize: 9, color: '#6b746e', maxWidth: 46 },
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
  map: { alignSelf: 'stretch', overflow: 'hidden', borderRadius: 10, borderWidth: 1, borderColor: '#dbe2da', backgroundColor: '#f4f3ef' },
  here: { position: 'absolute', width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: '#fff', backgroundColor: '#1f7a4d' },
  pin: { position: 'absolute', flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: '#fff', borderWidth: 1, borderColor: 'rgba(0,0,0,0.2)', borderRadius: 999, paddingVertical: 2, paddingHorizontal: 3, maxWidth: 170 },
  pinOn: { borderColor: '#e0a800', borderWidth: 3 },
  pinNo: { width: 20, height: 20, borderRadius: 10, backgroundColor: NAVY, alignItems: 'center', justifyContent: 'center' },
  pinNoText: { color: '#fff', fontSize: 11, fontWeight: '700' },
  pinText: { fontSize: 13, fontWeight: '600', color: '#1a1a1a', paddingRight: 5, flexShrink: 1 },
  zoom: { position: 'absolute', right: 8, top: 8, backgroundColor: 'rgba(255,255,255,0.95)', borderRadius: 6, borderWidth: 1, borderColor: '#dbe2da', overflow: 'hidden' },
  zoomBtn: { width: 34, height: 34, alignItems: 'center', justifyContent: 'center' },
  credit: { position: 'absolute', right: 6, bottom: 3, fontSize: 9, color: '#6b746e', backgroundColor: 'rgba(255,255,255,0.75)', paddingHorizontal: 3 },
  placeRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 2, borderRadius: 6 },
  item: { flexDirection: 'row', borderWidth: 1, borderColor: '#dbe2da', borderRadius: 12, overflow: 'hidden', backgroundColor: '#fbfcfa', alignSelf: 'stretch' },
  itemOn: { borderColor: '#e0a800', borderWidth: 3 },
  itemPhoto: { width: 96, minHeight: 96, backgroundColor: '#eef2ee' },
  itemBody: { flex: 1, paddingHorizontal: 12, paddingVertical: 10, gap: 3 },
  sourceLine: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  sourceHost: { fontSize: 12, fontWeight: '600', color: '#3d4a43' },
  quoteBar: { borderLeftWidth: 3, borderLeftColor: 'rgba(0,0,0,0.18)', paddingLeft: 10 },
  quoteText: { fontSize: 15, lineHeight: 24, color: '#1f2724' },
  quoteImageBox: { borderWidth: 1, borderColor: '#dbe2da', borderRadius: 8, overflow: 'hidden', backgroundColor: '#fff' },
  sourceRow: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', paddingVertical: 4 },
  sourceNo: { width: 20, height: 20, borderRadius: 4, backgroundColor: '#eef2ee', textAlign: 'center', fontSize: 11, lineHeight: 20, color: '#6b7a72' },
  frameGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  frame: { width: '48%', borderWidth: 1, borderColor: '#dbe2da', borderRadius: 8, overflow: 'hidden', backgroundColor: '#fff' },
  frameTime: { position: 'absolute', left: 6, top: 6, backgroundColor: 'rgba(0,0,0,0.65)', color: '#fff', fontSize: 12, paddingHorizontal: 5, borderRadius: 4, overflow: 'hidden' },
  frameBar: { height: 22, borderRadius: 4, backgroundColor: '#eef2ee', marginTop: 4 },
  frameTick: { position: 'absolute', top: 4, bottom: 4, width: 3, borderRadius: 2, backgroundColor: NAVY },
});
