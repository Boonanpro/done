// スマホのアプリで、ダンの返事の中の部品（```openui-lang のブロック）を描く（2026-10-23。それまでは文章に直して出していた）。
//
// - 読み手は Web と同じ物の写し（chat-shapes-plain.ts の parseShapeProgram。lang-core と同じ木を読む）。部品の名前・引数の
//   順は frontend/src/lib/chat-shapes/schema.ts と同じ。描けない・読めないブロックは今までどおり文章（shapeToPlainMarkdown）に戻す
// - 選択ボタンと入力欄は、PC と同じく「<問い> → <答え>」を本人の発言として送り、どの返事のどの部品への答えか（answer_to）を
//   付ける（鍵は chat-shapes-answers.ts の partKeys。Web の answers.ts の写し）。答えたかは部屋の記録の照合情報で見る
// - 写真はダンのファイル（/api/v1/files/…）と https:// の画像だけ。ボタンの行き先は safeLinkUrl を通った物だけ
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import {
  ANSWER_SHAPES, CONTAINER_SHAPES, PROGRAM_DEPTH_MAX, ShapeNode, parseShapeProgram, programDepth, programNodes, readLook,
  safeColor, safeLinkUrl, siteFilePath,
} from './chat-shapes-plain';
import { choiceAnswerText, inputAnswerText, inputAnswerValue, type AnswerTo } from './chat-shapes-answers';

/** 部品の名前と、位置引数の名前（schema.ts の zod の shape の順と同じ） */
const ARG_NAMES: Record<string, string[]> = {
  Compare: ['columns', 'rows', 'caption'],
  Choice: ['question', 'options'],
  Input: ['label', 'kind', 'unit', 'placeholder'],
  Steps: ['steps', 'title'],
  Chart: ['kind', 'labels', 'series', 'unit', 'title'],
  Card: ['children', 'title', 'image'],
  Row: ['children', 'align'],
  Column: ['children'],
  Heading: ['text', 'sub'],
  Text: ['text', 'tone'],
  Image: ['src', 'alt', 'shape'],
  Stat: ['label', 'value', 'unit', 'note', 'tone'],
  Facts: ['items'],
  Badge: ['text', 'tone'],
  Button: ['label', 'url'],
  Divider: [],
};
const ANSWER_VALUE_MAX = 200;

/** 部屋の側から渡す物: 答えを送る・答えた記録・リンクを開く・写真の URL */
export type ShapeRoom = {
  submit: ((text: string, answerTo: AnswerTo) => void) | null;
  /** `${message_id}|${part}` → 答えの値（部屋の記録の、本人の発言の照合情報から） */
  answers: ReadonlyMap<string, string>;
  openUrl: (url: string) => void;
  /** ダンのファイルの道（/api/v1/files/…）をアプリが読める URL に */
  siteUrl: (path: string) => string;
};
export const ShapeRoomContext = createContext<ShapeRoom>({ submit: null, answers: new Map(), openUrl: () => {}, siteUrl: (p) => p });
/** 描いている吹き出しの返事の id（保存済みのダンの返事だけ。無ければ答えられない） */
export const ShapeMessageContext = createContext<string | null>(null);
/** このブロックの部品の鍵（partKeys） */
const PartContext = createContext<string>('');
/** 組み合わせの中か（中の部品は自分の枠を付けない） */
const InsideContext = createContext(false);

/**
 * 1つのブロックを描けるかの確かめ（Web の checkShapeProgram と同じ決まりを、アプリで分かる範囲で）。
 * 知らない部品・置けない所の部品・答えの部品が2つ以上・深すぎる、なら null（呼び出し側は文章に戻す）
 */
export function readShapeBlock(code: string): ShapeNode | null {
  const root = parseShapeProgram(code);
  if (!root || programDepth(root) > PROGRAM_DEPTH_MAX) return null;
  const nodes = programNodes(root);
  if (nodes.filter((n) => ANSWER_SHAPES.has(n.name)).length > 1) return null;
  const hasNode = (v: unknown): boolean =>
    v instanceof ShapeNode || (Array.isArray(v) ? v.some(hasNode) : !!v && typeof v === 'object' && Object.values(v as Record<string, unknown>).some(hasNode));
  for (const n of nodes) {
    const names = ARG_NAMES[n.name];
    if (!names || n.args.length > names.length) return null;
    for (let i = 0; i < n.args.length; i++) {
      if (CONTAINER_SHAPES.has(n.name) && i === 0) {
        const a = n.args[0];
        if (!Array.isArray(a) || a.length === 0 || !a.every((c) => c instanceof ShapeNode || typeof c === 'string')) return null;
      } else if (hasNode(n.args[i])) return null;
    }
  }
  return root;
}

const propsOf = (n: ShapeNode): Record<string, unknown> =>
  Object.fromEntries((ARG_NAMES[n.name] || []).map((k, i) => [k, n.args[i]]));
const str = (v: unknown) => (typeof v === 'string' ? v : '');
const num = (v: unknown) => (typeof v === 'number' ? v.toLocaleString('ja-JP') : str(v));

function useImageUrl(src: unknown): string | null {
  const { siteUrl } = useContext(ShapeRoomContext);
  const s = str(src).trim();
  if (!s) return null;
  if (siteFilePath(s)) return siteUrl(s);
  return /^https:\/\/[A-Za-z0-9.-]+(?::\d{1,5})?(?:\/[^\s\\]*)?$/.test(s) ? s : null;
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

function ChoiceNode({ p }: { p: Record<string, unknown> }) {
  const room = useContext(ShapeRoomContext);
  const messageId = useContext(ShapeMessageContext);
  const part = useContext(PartContext);
  const question = str(p.question).trim();
  const seen = new Set<string>();
  const options = (Array.isArray(p.options) ? p.options : [])
    .map((o) => readLook(o))
    .filter((o): o is NonNullable<typeof o> => !!o && !!o.label.trim() && !seen.has(o.label.trim()) && !!seen.add(o.label.trim()))
    .map((o) => ({ ...o, label: o.label.replace(/\s+/g, ' ').trim(), color: safeColor(o.color) }));
  const answered = messageId ? room.answers.get(`${messageId}|${part}`) ?? null : null;
  const [sent, setSent] = useState<string | null>(null);
  const picked = answered ?? sent;
  const canAnswer = !!room.submit && !!messageId && !picked;
  return (
    <Box>
      {question ? <Text style={styles.question}>{question}</Text> : null}
      <View style={styles.options}>
        {options.map((o) => {
          const on = picked === o.label;
          return (
            <Pressable
              key={o.label}
              disabled={!canAnswer || o.label.length > ANSWER_VALUE_MAX}
              onPress={() => {
                if (!room.submit || !messageId) return;
                setSent(o.label);
                room.submit(choiceAnswerText(question, o.label), { message_id: messageId, part, kind: 'choice', value: o.label, question });
              }}
              style={({ pressed }) => [styles.option, on && styles.optionOn, (pressed || (!!picked && !on)) && styles.optionDim]}
            >
              {o.color ? <View style={[styles.swatch, { backgroundColor: o.color }]} /> : null}
              <Text style={[styles.optionText, on && styles.optionTextOn]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
      {picked ? <Text style={styles.answered}>✓ {answered ? '答えました' : '送っています…'}</Text> : null}
    </Box>
  );
}

function InputNode({ p }: { p: Record<string, unknown> }) {
  const room = useContext(ShapeRoomContext);
  const messageId = useContext(ShapeMessageContext);
  const part = useContext(PartContext);
  const label = str(p.label).trim();
  const unit = str(p.unit);
  const [value, setValue] = useState('');
  const answered = messageId ? room.answers.get(`${messageId}|${part}`) ?? null : null;
  const [sent, setSent] = useState<string | null>(null);
  const done = answered ?? sent;
  const send = () => {
    const v = value.trim();
    if (!v || !room.submit || !messageId) return;
    const val = inputAnswerValue(label, v, unit);
    if (val.length > ANSWER_VALUE_MAX) return;
    setSent(val);
    room.submit(inputAnswerText(label, v, unit), { message_id: messageId, part, kind: 'input', value: val, question: label });
  };
  return (
    <Box>
      {label ? <Text style={styles.question}>{label}</Text> : null}
      {done ? (
        <Text style={styles.answered}>✓ {done}{answered ? '' : '（送っています…）'}</Text>
      ) : (
        <View style={styles.inputRow}>
          <TextInput
            value={value}
            onChangeText={setValue}
            editable={!!room.submit && !!messageId}
            placeholder={str(p.placeholder)}
            keyboardType={p.kind === 'number' ? 'numeric' : 'default'}
            onSubmitEditing={send}
            style={styles.input}
          />
          {unit ? <Text style={styles.unit}>{unit}</Text> : null}
          <Pressable onPress={send} disabled={!value.trim() || !room.submit || !messageId} style={styles.sendBtn}>
            <Text style={styles.sendText}>送る</Text>
          </Pressable>
        </View>
      )}
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
    <Box flat>
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

function ChartNode({ p }: { p: Record<string, unknown> }) {
  const labels = (Array.isArray(p.labels) ? p.labels : []).map(str);
  const series = (Array.isArray(p.series) ? p.series : []).filter((s): s is { name?: unknown; values?: unknown } => !!s && typeof s === 'object');
  const unit = str(p.unit);
  const all = series.flatMap((s) => (Array.isArray(s.values) ? s.values.filter((v): v is number => typeof v === 'number') : []));
  const max = Math.max(1, ...all.map(Math.abs));
  const colors = ['#245e49', '#7fb39b', '#c08a3e', '#5a7fb0'];
  return (
    <Box>
      {str(p.title) ? <Text style={styles.question}>{str(p.title)}</Text> : null}
      {labels.map((l, i) => (
        <View key={i} style={styles.barRow}>
          <Text style={styles.barLabel} numberOfLines={1}>{l}</Text>
          <View style={{ flex: 1, gap: 2 }}>
            {series.map((s, si) => {
              const v = Array.isArray(s.values) ? s.values[i] : undefined;
              if (typeof v !== 'number') return null;
              return (
                <View key={si} style={styles.barLine}>
                  <View style={[styles.bar, { width: `${Math.max(2, (Math.abs(v) / max) * 100)}%`, backgroundColor: colors[si % colors.length] }]} />
                  <Text style={styles.barValue}>{v.toLocaleString('ja-JP')}{unit}</Text>
                </View>
              );
            })}
          </View>
        </View>
      ))}
      {series.length > 1 ? <Text style={styles.small}>{series.map((s, si) => `${['■', '■', '■', '■'][si % 4]} ${str(s.name)}`).join('　')}</Text> : null}
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
