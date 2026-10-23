// スマホのアプリ用: 部品（選択ボタン・入力欄）の答えの文面と部品の鍵。
// frontend/src/lib/chat-shapes/answers.ts と同じ中身（アプリは別のパッケージなので取り込めない。両方を同じに保つ。
// tests/chat_shapes_program.test.mjs が同じ中身であることを見る）。
/**
 * 部品（選択ボタン・入力欄）の答えを「本人の発言」にする時の文面と、
 * 部屋の記録からその答えを探し直す（再読み込みしても答えた状態が分かる）ための関数。
 *
 * 答えは確認カードと同じく本人のチャット発言として部屋に送る。文面は
 *   「<問い> → <答え>」
 * で固定（ダンはこれを読む）。それに加えて、どの返事のどの部品への答えかを
 *   ai_context.answer_to = { message_id, part, kind, value }
 * として同じ発言に保存する（app/api/chat_routes.py の _answer_to_context）。
 * 画面はこの照合情報だけで「答えた」と判定する。文面が同じでも照合情報の無い発言
 * （本人が手で打った物、別の返事への答え）は答えと数えない。
 *
 * part は部品の中身（コード）から作る短い鍵。同じ返事に同じコードの部品が2つあれば
 * 2つ目に -1 が付く（ordinal）。返事の描き方（通常／作業つき）が違っても同じ鍵になる。
 *
 * 依存なし（node:test から直接読み込んで試験する）。
 */

export const ANSWER_ARROW = ' → ';

export type AnswerKind = 'choice' | 'input';

export type AnswerTo = {
  message_id: string;
  part: string;
  kind: AnswerKind;
  value: string;
  question?: string;
};

/** 部屋にある本人の発言。id は保存された行の id（送った答えが記録に現れたかを見る） */
export type UserUtterance = { id?: string; text: string; at: number; answerTo?: AnswerTo | null };

// 文面と部品の鍵で空白とみなす文字（JavaScript の \s と同じ一覧を明示。サーバー chat_shapes.py KEY_SPACE_CHARS と同じ）。
// Markdown の構文の空白（半角スペースとタブだけ。plain.ts）とは別の物
const KEY_SPACE_RUN = /[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+/g;
const KEY_SPACE_EDGE = /^[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+|[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+$/g;

function norm(s: string): string {
  return (s || '').replace(KEY_SPACE_RUN, ' ').replace(KEY_SPACE_EDGE, '');
}

/** 選択ボタンを押した時に部屋へ送る文面。 */
export function choiceAnswerText(question: string, option: string): string {
  return `${norm(question)}${ANSWER_ARROW}${norm(option)}`;
}

/** 入力欄を送った時に部屋へ送る文面。unit は値の後ろに付ける（例: 30 → 30万円）。 */
export function inputAnswerText(label: string, value: string, unit?: string): string {
  const v = norm(value);
  const u = norm(unit || '');
  return `${norm(label)}${ANSWER_ARROW}${v}${u && !v.endsWith(u) ? u : ''}`;
}

/** 入力欄の答えの値（単位つき）: 文面の矢印より後ろ。 */
export function inputAnswerValue(label: string, value: string, unit?: string): string {
  const t = inputAnswerText(label, value, unit);
  return t.slice(t.indexOf(ANSWER_ARROW) + ANSWER_ARROW.length);
}

/** 部品の鍵: コードの FNV-1a（32bit）の16進 + 同じコードの何個目か。 */
export function partKey(code: string, ordinal = 0): string {
  const s = norm(code);
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `p${h.toString(16).padStart(8, '0')}${ordinal ? `-${ordinal}` : ''}`;
}

/** 返事の中の部品のコード列から、各部品の鍵を順に作る（同じコードは ordinal で区別）。 */
export function partKeys(codes: readonly string[]): string[] {
  const seen = new Map<string, number>();
  return codes.map((c) => {
    const base = partKey(c);
    const n = seen.get(base) || 0;
    seen.set(base, n + 1);
    return n ? `${base}-${n}` : base;
  });
}

/** 本人の発言が「その返事のその部品」への答えなら照合情報、違えば null。 */
export function answerFor(u: UserUtterance, messageId: string, part: string, kind: AnswerKind): AnswerTo | null {
  const a = u.answerTo;
  if (!a || a.kind !== kind) return null;
  if (a.message_id !== messageId || a.part !== part) return null;
  return a;
}

/**
 * その部品（返事 messageId の部品 part）に対する選択の答えを本人の発言から探す。
 * 見つかれば選んだ選択肢、無ければ null。選択肢に無い値（古い版の部品への答えなど）も
 * 値として返すので、画面は「選択肢と一致した時だけ強調」する。
 */
export function findChoiceAnswer(
  utterances: readonly UserUtterance[],
  messageId: string,
  part: string,
): string | null {
  for (const u of utterances) {
    const a = answerFor(u, messageId, part, 'choice');
    if (a && a.value) return a.value;
  }
  return null;
}

/** 入力欄の答え（単位つきの値）を探す。見つかれば値、無ければ null。 */
export function findInputAnswer(
  utterances: readonly UserUtterance[],
  messageId: string,
  part: string,
): string | null {
  for (const u of utterances) {
    const a = answerFor(u, messageId, part, 'input');
    if (a && a.value) return a.value;
  }
  return null;
}

/** 部屋の記録（MessageResponse 相当）から照合情報を読む。無ければ null。 */
export function readAnswerTo(aiContext: unknown): AnswerTo | null {
  if (!aiContext || typeof aiContext !== 'object') return null;
  const a = (aiContext as { answer_to?: unknown }).answer_to;
  if (!a || typeof a !== 'object') return null;
  const o = a as Record<string, unknown>;
  if (typeof o.message_id !== 'string' || typeof o.part !== 'string') return null;
  if (o.kind !== 'choice' && o.kind !== 'input') return null;
  return {
    message_id: o.message_id,
    part: o.part,
    kind: o.kind,
    value: typeof o.value === 'string' ? o.value : '',
    ...(typeof o.question === 'string' ? { question: o.question } : {}),
  };
}
