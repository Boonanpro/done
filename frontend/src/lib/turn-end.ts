/**
 * ダンのターンが答えで終わった。答えと同じ知らせ（新着の線の message の turn_end）で届き、画面は答えを出すのと
 * 同時に作業中の表示を止める（2026-10-14: 答えの後に「考え中」「実行中」が1〜4秒残っていた）。
 *
 * その後に、終わる前に出した問い合わせの答えが遅れて届いても、もう点け直さない:
 * - 終わった実行記録（run）が「実行中」と返ってきたら「完了」と読む
 * - 部屋の「作業中」が、終わる前に始まった送信のものなら「作業中ではない」と読む（時刻はどちらもサーバーの時計）
 */
import { create } from 'zustand';

export type TurnEnd = { run_id?: string | null; at?: number };

const endedRuns = new Set<string>();
const endedAt = new Map<string, number>();   // room -> サーバーの時計で、ターンが答えで終わった時刻（秒）

export function noteTurnEnd(roomId: string, end: TurnEnd): void {
  if (end.run_id) endedRuns.add(end.run_id);
  if (typeof end.at === 'number') endedAt.set(roomId, Math.max(end.at, endedAt.get(roomId) ?? 0));
}

/** current-run の答えに: 答えで終わった実行記録はもう実行中ではない。 */
export function settleRun<T extends { id?: string; state?: string } | null | undefined>(run: T): T {
  return run && run.state === 'running' && run.id && endedRuns.has(run.id) ? ({ ...run, state: 'completed' } as T) : run;
}

/** /active の答えに: その「作業中」が、答えで終わったターンの送信のものなら作業中ではない。 */
export function settleActive<T extends { active?: boolean; session_id?: string; started_at?: number | null }>(status: T): T {
  const ended = status?.session_id ? endedAt.get(status.session_id) : undefined;
  if (!status?.active || ended === undefined || typeof status.started_at !== 'number') return status;
  return status.started_at <= ended ? ({ ...status, active: false, started_at: null } as T) : status;
}

/** 部屋ごとに、ターンが答えで終わった回数。入力欄はこれが変わったら手元の「作業中」を外す。 */
export const useTurnEndStore = create<{ ends: Record<string, number>; end: (roomId: string) => void }>((set) => ({
  ends: {},
  end: (roomId) => set((s) => ({ ends: { ...s.ends, [roomId]: (s.ends[roomId] ?? 0) + 1 } })),
}));
