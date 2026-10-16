/**
 * ダンの返事に出す部品（5つ）の定義。名前・説明・引数の型（zod）だけを持つ。
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

/** 選択肢の整え方: 前後の空白を除き、空と重複を落とす（完成時の検証と描画で同じ物を使う） */
export function normalizeOptions(options: readonly unknown[] | undefined | null): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const o of options || []) {
    if (typeof o !== 'string') continue;
    const t = o.replace(/\s+/g, ' ').trim();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

export const CHOICE_MIN = 2;
export const CHOICE_MAX = 6;

export const ChoiceProps = z
  .object({
    question: z.string().describe('何を選ぶか（短い問い）'),
    options: z.array(z.string()).describe('選択肢。2〜6個'),
  })
  .refine((v) => v.question.trim().length > 0, { message: '問いが空' })
  .refine((v) => {
    const n = normalizeOptions(v.options).length;
    return n >= CHOICE_MIN && n <= CHOICE_MAX;
  }, { message: `選択肢は空と重複を除いて${CHOICE_MIN}〜${CHOICE_MAX}個` });

export const InputProps = z
  .object({
    label: z.string().describe('何を入れてもらうか'),
    kind: z.enum(['number', 'text']).optional().describe('number=数値, text=短い文（既定 text）'),
    unit: z.string().optional().describe('単位（円・人・日など。数値の時だけ）'),
    placeholder: z.string().optional().describe('入力例'),
  })
  .refine((v) => v.label.trim().length > 0, { message: 'ラベルが空' });

export const CompareProps = z
  .object({
    columns: z.array(z.string()).describe('列の見出し。先頭は比べる観点の列'),
    rows: z.array(z.array(z.string())).describe('行。各行は columns と同じ個数の文字列'),
    caption: z.string().optional().describe('表の題'),
  })
  .refine((v) => v.columns.length >= 2 && v.columns.every((c) => c.trim().length > 0), { message: '列は2つ以上、見出しは空でない' })
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
      .array(z.object({ name: z.string(), values: z.array(z.number()) }))
      .describe('系列。values は labels と同じ個数'),
    unit: z.string().optional().describe('値の単位'),
    title: z.string().optional().describe('グラフの題'),
  })
  .refine((v) => v.labels.length >= 1 && v.series.length >= 1, { message: '目盛りか系列が無い' })
  .refine((v) => v.series.every((s) => s.values.length === v.labels.length), { message: '値の数が目盛りの数と違う' })
  .refine((v) => v.series.every((s) => s.values.every((x) => Number.isFinite(x))), { message: '数値でない値がある' })
  .refine((v) => {
    const names = v.series.map((s) => s.name.trim());
    return names.every((n) => n.length > 0 && n !== 'label') && new Set(names).size === names.length;
  }, { message: '系列名が空・重複・label' });

export type ChoiceInput = z.infer<typeof ChoiceProps>;
export type InputInput = z.infer<typeof InputProps>;
export type CompareInput = z.infer<typeof CompareProps>;
export type StepsInput = z.infer<typeof StepsProps>;
export type ChartInput = z.infer<typeof ChartProps>;

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
