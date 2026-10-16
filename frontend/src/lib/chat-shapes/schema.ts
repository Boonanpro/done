/**
 * ダンの返事に出す部品（5つ）の定義。名前・説明・引数の型（zod）だけを持つ。
 *
 * - 画面側 (components/chat/chat-shapes.tsx) はこれに描画関数を付けて OpenUI の部品一覧にする
 * - 指示文の生成 (scripts/generate-chat-shapes-prompt.mjs) はこれから部品の一覧の文を作り、
 *   app/agent/chat_shapes_prompt.md に書く（Claude の部屋でも GPT の部屋でも同じ文が入る）
 *
 * 引数は位置で渡される（OpenUI Lang）ので、必須の引数を先に、省略できるものを後ろに置く。
 * React に依存しない（node から直接読める）。
 */
import { z } from 'zod/v4';

export const ChoiceProps = z.object({
  question: z.string().describe('何を選ぶか（短い問い）'),
  options: z.array(z.string()).describe('選択肢。2〜6個'),
});

export const InputProps = z.object({
  label: z.string().describe('何を入れてもらうか'),
  kind: z.enum(['number', 'text']).optional().describe('number=数値, text=短い文（既定 text）'),
  unit: z.string().optional().describe('単位（円・人・日など。数値の時だけ）'),
  placeholder: z.string().optional().describe('入力例'),
});

export const CompareProps = z.object({
  columns: z.array(z.string()).describe('列の見出し。先頭は比べる観点の列'),
  rows: z.array(z.array(z.string())).describe('行。各行は columns と同じ個数の文字列'),
  caption: z.string().optional().describe('表の題'),
});

export const StepsProps = z.object({
  steps: z.array(z.string()).describe('手順。上から順に'),
  title: z.string().optional().describe('手順の題'),
});

export const ChartProps = z.object({
  kind: z.enum(['line', 'bar']).describe('line=推移, bar=比較'),
  labels: z.array(z.string()).describe('横軸の目盛り（月・項目名など）'),
  series: z
    .array(z.object({ name: z.string(), values: z.array(z.number()) }))
    .describe('系列。values は labels と同じ個数'),
  unit: z.string().optional().describe('値の単位'),
  title: z.string().optional().describe('グラフの題'),
});

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
