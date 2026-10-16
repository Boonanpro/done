/**
 * 部品（選択ボタン・入力欄）の答えを「本人の発言」にする時の文面と、
 * 部屋の記録からその答えを探し直す（再読み込みしても答えた状態が分かる）ための関数。
 *
 * 答えは確認カードと同じく本人のチャット発言として部屋に送る。文面は
 *   「<問い> → <答え>」
 * で固定し、画面はその部品より後の本人の発言にこの文面があれば「答えた」と判定する。
 * 別の保存先を持たず、部屋の記録だけを見る（画面は推測せず記録を映す）。
 *
 * 依存なし（node:test から直接読み込んで試験する）。
 */

export const ANSWER_ARROW = ' → ';

export type UserUtterance = { text: string; at: number };

function norm(s: string): string {
  return (s || '').replace(/\s+/g, ' ').trim();
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

/**
 * その部品（AI の発言時刻 askedAt 以降）に対する選択の答えを本人の発言から探す。
 * 見つかれば選んだ選択肢、無ければ null。
 */
export function findChoiceAnswer(
  utterances: UserUtterance[],
  question: string,
  options: string[],
  askedAt: number,
): string | null {
  const candidates = new Map(options.map((o) => [choiceAnswerText(question, o), o] as const));
  for (const u of utterances) {
    if (u.at < askedAt) continue;
    const hit = candidates.get(norm(u.text));
    if (hit !== undefined) return hit;
  }
  return null;
}

/** 入力欄の答え（「<label> → 」で始まる本人の発言）を探す。見つかれば値の部分。 */
export function findInputAnswer(
  utterances: UserUtterance[],
  label: string,
  askedAt: number,
): string | null {
  const prefix = `${norm(label)}${ANSWER_ARROW}`;
  for (const u of utterances) {
    if (u.at < askedAt) continue;
    const t = norm(u.text);
    if (t.startsWith(prefix) && t.length > prefix.length) return t.slice(prefix.length);
  }
  return null;
}
