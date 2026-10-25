/**
 * ダンの返事に出す部品の定義。名前・説明・引数の型（zod）だけを持つ。
 * 2026-10-23: 表・選択ボタン・入力欄・手順・グラフの5つに、組み合わせて画面を作るための小さな部品（カード・横並び・縦並び・
 * 見出し・文・写真・数字・事実の並び・札・ボタン・区切り線）を足した。Card・Row・Column の最初の引数は中に並べる部品の一覧で、
 * 部品の中に部品を入れて組める（checkShapeProgram が1つのブロック全体を確かめる）。
 *
 * - 画面側 (components/chat/chat-shapes.tsx) はこれに描画関数を付けて OpenUI の部品一覧にする
 * - 指示文の生成 (scripts/generate-chat-shapes-prompt.mjs) はこれから部品の一覧の文を作り、
 *   app/agent/chat_shapes_prompt.md に書く（Claude の部屋でも GPT の部屋でも同じ文が入る）
 *
 * 引数は位置で渡される（OpenUI Lang）ので、必須の引数を先に、省略できるものを後ろに置く。
 *
 * 2段階の検証:
 * - 生成の途中は lang-core が JSON Schema（型と必須）だけで読む。refine は JSON Schema に
 *   出ないので、選択肢が1個しか届いていない途中でも部品は描ける（段階表示）。
 * - 閉じが届いた（完成した）部品は validateComplete で refine まで含めて検証し、
 *   通らなければその部品だけ元のコードに戻す（空の選択肢、個数、表の列数、グラフの値の数など）。
 *
 * React に依存しない（node から直接読める）。
 */
import { z } from 'zod/v4';
import {
  ANSWER_SHAPES, CONTAINER_SHAPES, PROGRAM_DEPTH_MAX, ShapeNode, parseShapeProgram, programDepth, programNodes, readLook, type Look,
} from './plain.ts';

/**
 * 選択肢の整え方: 文字か {label, color?, image?} を読み（plain.ts readLook。色と画像は検査を通った物だけ残る）、名前の
 * 前後の空白を除き、名前が空と重複の物を落とす（完成時の検証と描画で同じ物を使う）。siteHost は画像の検査へ渡す
 */
export function choiceOptions(options: readonly unknown[] | undefined | null, siteHost?: string | null): Look[] {
  const seen = new Set<string>();
  const out: Look[] = [];
  for (const o of options || []) {
    const look = readLook(o, siteHost);
    if (!look) continue;
    const t = look.label.replace(/\s+/g, ' ').trim();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push({ ...look, label: t });
  }
  return out;
}

/** 選択肢の名前だけ（押した時の答えはこの名前） */
export function normalizeOptions(options: readonly unknown[] | undefined | null): string[] {
  return choiceOptions(options).map((o) => o.label);
}

export const CHOICE_MIN = 2;
export const CHOICE_MAX = 6;

/**
 * 答え（answer_to）の長さの契約。サーバー（app/agent/chat_shapes.py の ANSWER_*_MAX）と同じ数。
 * - 完成した部品の選択肢・問い・ラベルがこれより長ければ、その部品はコードに戻す（押せる部品にしない）
 * - 入力欄はこれより長い値を受け付けない（単位を含めて）
 * - サーバーはこれより長い答えを拒否する（黙って切らない）。画面は値の全文で照合する
 */
export const ANSWER_VALUE_MAX = 200;      // 選択肢の文字・入力の値（単位つき）
export const ANSWER_QUESTION_MAX = 200;   // 問い・ラベル

/**
 * 実物（色見本・縮小画像）つきの名前。値の検査は plain.ts（safeColor・safeImageUrl）で、通らない値は捨てて名前だけを出す
 * （部品はコードに戻さない）。ここでは型だけを見る。名前は押した時の答えなので長さの契約に入る
 */
const ChoiceOption = z.union([
  z.string().max(ANSWER_VALUE_MAX),
  z.object({
    label: z.string().max(ANSWER_VALUE_MAX).describe('選択肢の名前（押すとこれが答え）'),
    color: z.string().optional().describe('色見本: #rgb・#rrggbb・rgb(r, g, b)'),
    image: z.string().optional().describe('縮小画像: /api/v1/files/… か https://'),
  }),
]);
const CompareCell = z.union([
  z.string(),
  z.object({
    label: z.string().describe('セルの文字'),
    color: z.string().optional().describe('色見本: #rgb・#rrggbb・rgb(r, g, b)'),
  }),
]);
/** 表の見出し・セルの文字（{label, color} なら label） */
export function cellLabel(c: unknown): string {
  return readLook(c)?.label ?? '';
}

export const ChoiceProps = z
  .object({
    question: z.string().max(ANSWER_QUESTION_MAX).describe('何を選ぶか（短い問い）'),
    options: z.array(ChoiceOption).describe('選択肢。2〜6個'),
  })
  .refine((v) => v.question.trim().length > 0, { message: '問いが空' })
  .refine((v) => {
    const n = normalizeOptions(v.options).length;
    return n >= CHOICE_MIN && n <= CHOICE_MAX;
  }, { message: `選択肢は空と重複を除いて${CHOICE_MIN}〜${CHOICE_MAX}個` });

export const InputProps = z
  .object({
    label: z.string().max(ANSWER_QUESTION_MAX).describe('何を入れてもらうか'),
    kind: z.enum(['number', 'text']).optional().describe('number=数値, text=短い文（既定 text）'),
    unit: z.string().max(20).optional().describe('単位（円・人・日など。数値の時だけ）'),
    placeholder: z.string().optional().describe('入力例'),
  })
  .refine((v) => v.label.trim().length > 0, { message: 'ラベルが空' });

export const CompareProps = z
  .object({
    columns: z.array(CompareCell).describe('列の見出し。先頭は比べる観点の列'),
    rows: z.array(z.array(CompareCell)).describe('行。各行は columns と同じ個数'),
    caption: z.string().optional().describe('表の題'),
  })
  // 先頭（観点の列）の見出しは空でもよい（表の左上を空けるのはよくある書き方。2026-10-17 の実モデルで Claude が書いた）
  .refine((v) => v.columns.length >= 2 && v.columns.every((c, i) => i === 0 || cellLabel(c).trim().length > 0), { message: '列は2つ以上、観点の列より後の見出しは空でない' })
  .refine((v) => v.rows.length >= 1, { message: '行が無い' })
  // 列より多いセルは隠れてしまうので受け付けない。足りないセルは空欄として描く
  .refine((v) => v.rows.every((r) => r.length >= 1 && r.length <= v.columns.length), { message: '行のセル数が列数を超えている' });

export const StepsProps = z
  .object({
    steps: z.array(z.string()).describe('手順。上から順に'),
    title: z.string().optional().describe('手順の題'),
  })
  .refine((v) => v.steps.filter((s) => s.trim()).length >= 1, { message: '手順が無い' });

export const ChartProps = z
  .object({
    kind: z.enum(['line', 'bar']).describe('line=推移, bar=比較'),
    labels: z.array(z.string()).describe('横軸の目盛り（月・項目名など）'),
    series: z
      .array(z.object({ name: z.string(), values: z.array(z.number().nullable()) }))
      .describe('系列。values は labels と同じ個数。値の無い所は null（折れ線はそこで切れ、棒は描かない）'),
    unit: z.string().optional().describe('値の単位'),
    title: z.string().optional().describe('グラフの題'),
  })
  .refine((v) => v.labels.length >= 1 && v.series.length >= 1, { message: '目盛りか系列が無い' })
  .refine((v) => v.series.every((s) => s.values.length === v.labels.length), { message: '値の数が目盛りの数と違う' })
  .refine((v) => v.series.every((s) => s.values.every((x) => x === null || Number.isFinite(x))), { message: '数値でない値がある' })
  .refine((v) => v.series.some((s) => s.values.some((x) => x !== null)), { message: '値が1つも無い' })
  .refine((v) => {
    const names = v.series.map((s) => s.name.trim());
    return names.every((n) => n.length > 0 && n !== 'label') && new Set(names).size === names.length;
  }, { message: '系列名が空・重複・label' });

// --- 組み合わせて画面を作る小さな部品 ----------------------------------------------------------------
// 子の一覧は部品（入れ子）か短い文字。lang-core は子を部品の要素として渡し、画面は useRenderNode で描く。
const Children = z.array(z.any()).describe('中に並べる部品（部品か短い文字）');
const nonEmpty = (s: string | undefined) => !!s && s.trim().length > 0;
const Tone = z.enum(['neutral', 'good', 'warn', 'bad', 'info']);

export const CardProps = z
  .object({
    children: Children,
    title: z.string().optional().describe('カードの題'),
    image: z.string().optional().describe('上に出す写真: /api/v1/files/… か https://'),
  })
  .refine((v) => v.children.length >= 1, { message: '中身が無い' });

export const RowProps = z
  .object({
    children: Children,
    align: z.enum(['start', 'center', 'between']).optional().describe('並べ方（既定 start）'),
  })
  .refine((v) => v.children.length >= 1, { message: '中身が無い' });

export const ColumnProps = z
  .object({ children: Children })
  .refine((v) => v.children.length >= 1, { message: '中身が無い' });

export const HeadingProps = z
  .object({
    text: z.string().describe('見出し'),
    sub: z.string().optional().describe('見出しの下の小さな文'),
  })
  .refine((v) => nonEmpty(v.text), { message: '見出しが空' });

export const TextProps = z
  .object({
    text: z.string().describe('短い文'),
    tone: z.enum(['normal', 'muted', 'strong', 'small']).optional().describe('文字の調子'),
  })
  .refine((v) => nonEmpty(v.text), { message: '文が空' });

export const ImageProps = z
  .object({
    src: z.string().describe('写真: /api/v1/files/… か https://'),
    alt: z.string().optional().describe('写真の説明'),
    shape: z.enum(['wide', 'square', 'tall']).optional().describe('形（既定 wide）'),
  })
  .refine((v) => nonEmpty(v.src), { message: '写真の場所が空' });

export const StatProps = z
  .object({
    label: z.string().describe('何の数字か（合計・到着など）'),
    value: z.union([z.string(), z.number()]).describe('数字・金額・時刻'),
    unit: z.string().max(20).optional().describe('単位（円・分など）'),
    note: z.string().optional().describe('数字の下の小さな補足'),
    tone: Tone.optional().describe('色の調子'),
  })
  .refine((v) => nonEmpty(v.label) && (typeof v.value === 'number' ? Number.isFinite(v.value) : nonEmpty(v.value)), { message: '名前か値が空' });

export const FactsProps = z
  .object({
    items: z.array(z.object({ label: z.string(), value: z.union([z.string(), z.number()]) })).describe('事実の並び（店・支払い・時刻など）'),
  })
  .refine((v) => v.items.length >= 1 && v.items.every((x) => nonEmpty(x.label)), { message: '項目が無い・名前が空' });

export const BadgeProps = z
  .object({
    text: z.string().max(40).describe('札の文字（短く）'),
    tone: Tone.optional().describe('色の調子'),
  })
  .refine((v) => nonEmpty(v.text), { message: '札が空' });

export const ButtonProps = z
  .object({
    label: z.string().max(60).describe('ボタンの文字'),
    url: z.string().describe('開く先: https:// かこのサイトの道（/artifacts/… など）'),
  })
  .refine((v) => nonEmpty(v.label) && nonEmpty(v.url), { message: '文字か開く先が空' });

export const DividerProps = z.object({});

// --- 矢印でつなぐ図（2026-10-25、通話の画面係と一緒に）-----------------------------------------------------------------
// 人・物・流れをアイコンの箱と矢印で描く。文字だけの表や箇条書きにしない時の部品。nodes は流れの順に並べ、edges を省けば
// 順につなぐ。tone "now" は今どこかを示す（箱が目立つ色になる）。アイコンの名前は FLOW_ICONS のどれか（PC は lucide、
// スマホは Ionicons に当てる。無い名前はアイコン無しで描き、部品はコードに戻さない）。
export const FLOW_ICONS = [
  'person', 'people', 'phone', 'pc', 'server', 'database', 'cloud', 'mail', 'chat', 'money', 'card', 'bank', 'doc', 'calendar', 'clock',
  'check', 'warning', 'lock', 'key', 'shield', 'globe', 'home', 'car', 'train', 'camera', 'mic', 'video', 'bot', 'search', 'tool', 'chart',
  'box', 'truck', 'store', 'flag', 'star', 'heart', 'question', 'gear', 'image', 'pin', 'glasses', 'ear', 'eye', 'file', 'folder', 'link', 'bolt',
] as const;
export const FLOW_NODE_MAX = 8;
const FlowNode = z.object({
  id: z.string().max(40).describe('箱の名前（edges で指す）'),
  label: z.string().max(40).describe('箱の文字（短く、8文字まで）'),
  icon: z.enum(FLOW_ICONS).optional().describe('アイコン'),
  sub: z.string().max(60).optional().describe('箱の下の小さな補足'),
  tone: z.enum(['neutral', 'now', 'good', 'warn', 'bad']).optional().describe('now=今ここ'),
});
const FlowEdge = z.object({
  from: z.string().describe('矢印の元の箱の id'),
  to: z.string().describe('矢印の先の箱の id'),
  label: z.string().max(30).optional().describe('矢印に添える短い文字'),
});
export const FlowProps = z
  .object({
    nodes: z.array(FlowNode).describe(`箱。流れの順に2〜${FLOW_NODE_MAX}個`),
    edges: z.array(FlowEdge).optional().describe('矢印。省くと箱を順につなぐ'),
    title: z.string().optional().describe('図の題'),
  })
  .refine((v) => v.nodes.length >= 2 && v.nodes.length <= FLOW_NODE_MAX, { message: `箱は2〜${FLOW_NODE_MAX}個` })
  .refine((v) => v.nodes.every((n) => nonEmpty(n.id) && nonEmpty(n.label)), { message: '箱の id か文字が空' })
  .refine((v) => new Set(v.nodes.map((n) => n.id)).size === v.nodes.length, { message: '箱の id が重複' })
  .refine((v) => (v.edges || []).every((e) => v.nodes.some((n) => n.id === e.from) && v.nodes.some((n) => n.id === e.to)), { message: '矢印が無い箱を指している' });
export type FlowInput = z.infer<typeof FlowProps>;

/** 描く矢印: 書かれた edges（省かれていれば箱を順につなぐ）。隣り合う箱の間の矢印はその場所に、それ以外は図の下に文字で */
export type FlowEdgeInput = { from: string; to: string; label?: string };
export function flowEdges(v: { nodes: { id: string }[]; edges?: FlowEdgeInput[] }) {
  const ids = v.nodes.map((n) => n.id);
  const edges: FlowEdgeInput[] = v.edges && v.edges.length ? v.edges : ids.slice(1).map((to, i) => ({ from: ids[i], to }));
  const between = new Map<number, { label?: string }>();   // i: between nodes[i] and nodes[i+1]
  const others: FlowEdgeInput[] = [];
  for (const e of edges) {
    const a = ids.indexOf(e.from), b = ids.indexOf(e.to);
    if (a >= 0 && b === a + 1 && !between.has(a)) between.set(a, { label: e.label });
    else others.push(e);
  }
  return { between, others };
}

export type ChoiceInput = z.infer<typeof ChoiceProps>;
export type InputInput = z.infer<typeof InputProps>;
export type CompareInput = z.infer<typeof CompareProps>;
export type StepsInput = z.infer<typeof StepsProps>;
export type ChartInput = z.infer<typeof ChartProps>;
export type CardInput = z.infer<typeof CardProps>;
export type RowInput = z.infer<typeof RowProps>;
export type ColumnInput = z.infer<typeof ColumnProps>;
export type HeadingInput = z.infer<typeof HeadingProps>;
export type TextInput = z.infer<typeof TextProps>;
export type ImageInput = z.infer<typeof ImageProps>;
export type StatInput = z.infer<typeof StatProps>;
export type FactsInput = z.infer<typeof FactsProps>;
export type BadgeInput = z.infer<typeof BadgeProps>;
export type ButtonInput = z.infer<typeof ButtonProps>;

/** 部品の一覧（指示文に並ぶ順）。名前は OpenUI Lang の呼び名そのもの。 */
export const SHAPE_SPECS = [
  {
    name: 'Compare',
    description: '横並びの表。候補や案を観点ごとに比べる時',
    props: CompareProps,
  },
  {
    name: 'Choice',
    description: '選択ボタン（2〜6択）。本人に1つ選んでもらう時。押すと答えが本人の発言として届く',
    props: ChoiceProps,
  },
  {
    name: 'Input',
    description: '数値か短い文を1つ入れてもらう欄。送ると答えが本人の発言として届く',
    props: InputProps,
  },
  {
    name: 'Steps',
    description: '手順の一覧。本人がこれからやる順番を示す時',
    props: StepsProps,
  },
  {
    name: 'Chart',
    description: '折れ線か棒のグラフ。推移や量の比較を見せる時',
    props: ChartProps,
  },
  { name: 'Card', description: '枠。中に部品を並べ、題と上の写真を付けられる', props: CardProps },
  { name: 'Row', description: '横並び（狭い画面では折り返す）', props: RowProps },
  { name: 'Column', description: '縦並び', props: ColumnProps },
  { name: 'Heading', description: '見出し', props: HeadingProps },
  { name: 'Text', description: '短い文', props: TextProps },
  { name: 'Image', description: '写真（この会話にある画像だけ）', props: ImageProps },
  { name: 'Stat', description: '大きく見せる数字（金額・時刻・件数）', props: StatProps },
  { name: 'Facts', description: '名前と値の並び（店・支払い・到着など）', props: FactsProps },
  { name: 'Badge', description: '小さな札（状態・種類）', props: BadgeProps },
  { name: 'Button', description: 'リンクを開くボタン', props: ButtonProps },
  { name: 'Divider', description: '区切り線', props: DividerProps },
  { name: 'Flow', description: '矢印でつなぐ図（人・物・流れ）。箱は流れの順、edges を省くと順につなぐ。tone now=今ここ', props: FlowProps },
] as const;

export const SHAPE_NAMES: readonly string[] = SHAPE_SPECS.map((s) => s.name);

/**
 * 完成した部品の検証（閉じが届いた後に1回）。通らない時は理由を返し、画面はその部品を元のコードに戻す。
 * 途中（生成中）の部品にはかけない（lang-core の段階表示を妨げない）。
 */
export function validateComplete(name: string, props: unknown): { ok: true } | { ok: false; reason: string } {
  const spec = SHAPE_SPECS.find((s) => s.name === name);
  if (!spec) return { ok: false, reason: `知らない部品: ${name}` };
  const r = spec.props.safeParse(props);
  if (r.success) return { ok: true };
  const first = r.error.issues[0];
  return { ok: false, reason: first ? `${first.path.join('.') || name}: ${first.message}` : '検証に失敗' };
}

/**
 * 1つのブロック全体（`root = …` と、名前で指す文の並び）の完成時の検証。部品ごとに位置引数を定義の順に名前へ当てて
 * validateComplete にかけるほか、組み合わせの決まりを見る:
 * - 中に部品を並べられるのは Card・Row・Column の最初の引数（子の一覧。部品か文字）だけ。ほかの所に部品は書けない
 * - 押すと答えが届く部品（Choice・Input）は1つのブロックに1つまで（答えの照合はブロックごと）
 * - 深さは PROGRAM_DEPTH_MAX まで（部品の数の上限は読み手 parseShapeProgram が見る）
 * 通らない時は理由を返し、画面はブロックを元のコードに戻す。
 */
export function checkShapeProgram(code: string): { ok: true; root: ShapeNode } | { ok: false; reason: string } {
  const root = parseShapeProgram(code);
  if (!root) return { ok: false, reason: '部品として読めない（書き方・名前・大きさ）' };
  if (programDepth(root) > PROGRAM_DEPTH_MAX) return { ok: false, reason: `入れ子が深すぎる（${PROGRAM_DEPTH_MAX}段まで）` };
  const nodes = programNodes(root);
  if (nodes.filter((n) => ANSWER_SHAPES.has(n.name)).length > 1) return { ok: false, reason: '選択ボタン・入力欄は1つのブロックに1つまで' };
  const hasNode = (v: unknown): boolean =>
    v instanceof ShapeNode || (Array.isArray(v) ? v.some(hasNode) : !!v && typeof v === 'object' && Object.values(v as Record<string, unknown>).some(hasNode));
  for (const n of nodes) {
    const spec = SHAPE_SPECS.find((s) => s.name === n.name);
    if (!spec) return { ok: false, reason: `知らない部品: ${n.name}` };
    const keys = Object.keys(spec.props.shape);
    if (n.args.length > keys.length) return { ok: false, reason: `${n.name}: 引数が多い` };
    const container = CONTAINER_SHAPES.has(n.name);
    for (let i = 0; i < n.args.length; i++) {
      const a = n.args[i];
      if (container && i === 0) {
        if (!Array.isArray(a) || !a.every((c) => c instanceof ShapeNode || typeof c === 'string')) {
          return { ok: false, reason: `${n.name}: 中身は部品か文字の一覧` };
        }
      } else if (hasNode(a)) {
        return { ok: false, reason: `${n.name}: ここに部品は書けない` };
      }
    }
    const r = validateComplete(n.name, Object.fromEntries(n.args.map((a, i) => [keys[i], a])));
    if (!r.ok) return r;
  }
  return { ok: true, root };
}
