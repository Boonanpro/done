'use client';

import { useEffect, useState } from 'react';
import { promptRequest } from '@/lib/prompts-api';

export type Change = { id: number; node: string; phase: string; text: string; at: string };
type Decision = { words: string; route: string; preliminary?: boolean; look: boolean | null; reason: string; criterion: string; ms: number | null; model: string };
export type Turn = { turn: number; words: string; decisions: Decision[] };
type Development = { changes: Change[]; session: string };
const empty: Development = { changes: [], session: '' };

export function useDevelopmentBoard(enabled: boolean) {
  const [board, setBoard] = useState(empty);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState('');
  const [routingError, setRoutingError] = useState('');
  useEffect(() => {
    if (!enabled) return;
    let active = true, timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        if (!document.hidden) {
          const data = await promptRequest<Development>('/development');
          if (active) {
            setBoard(previous => previous.session === data.session && previous.changes[0]?.id === data.changes[0]?.id ? previous : data);
            setError('');
          }
        }
      } catch { if (active) setError('構成図の変更履歴を取得できませんでした。'); }
      finally { if (active) timer = setTimeout(refresh, 2500); }
    }
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [enabled]);
  useEffect(() => {
    if (!enabled || !board.session) return;
    setTurns([]); setRoutingError('');
    let active = true, timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        if (!document.hidden) {
          const data = await promptRequest<{ turns: Turn[] }>('/live/backend/routing?session_id=' + encodeURIComponent(board.session), undefined, '/api/v1/voicelog');
          if (active) {
            setTurns(previous => JSON.stringify(previous) === JSON.stringify(data.turns) ? previous : data.turns);
            setRoutingError('');
          }
        }
      } catch { if (active) setRoutingError('通話の判断を取得できませんでした。'); }
      finally { if (active) timer = setTimeout(refresh, 650); }
    }
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [enabled, board.session]);
  return { ...board, turns, error: error || (board.session ? routingError : '') };
}

type Comparison = { baseline: Turn | null; setBaseline: (turn: Turn | null) => void };

export function TurnDecision({ turns, live, baseline, setBaseline }: { turns: Turn[]; live: boolean } & Comparison) {
  const [selected, setSelected] = useState<number | null>(null);
  const turn = turns.find(t => t.turn === selected) || turns[0];
  if (!turn) return <p>発言を待っています。</p>;

  return <div className="space-y-1.5">
    <label className="flex items-center gap-2 text-xs">{live ? '通話中' : '直前の通話'}
      <select className="min-w-0 flex-1 rounded border bg-white px-1 py-1" aria-label="確認する発言" value={selected ?? ''} onChange={e => setSelected(e.target.value === '' ? null : Number(e.target.value))}>
        <option value="">最新の発言</option>{turns.map(t => <option key={t.turn} value={t.turn}>{t.words.slice(0, 32)}</option>)}
      </select>
    </label>
    {baseline && <div className="rounded border bg-stone-50 p-2">
      <div className="flex justify-between"><strong>比較に残した判断</strong>
        <button type="button" className="underline" onClick={() => setBaseline(null)}>比較を閉じる</button></div>
      <DecisionText turn={baseline} />
    </div>}
    {baseline && <strong>選んでいる発言</strong>}
    <DecisionText turn={turn} />
    {turn.decisions.length > 0 && <button type="button" className="text-teal-800 underline" onClick={() => setBaseline(turn)}>この判断を比較に残す</button>}
  </div>;
}

function DecisionText({turn}: {turn: Turn}) {
  const decision = [...turn.decisions].reverse().find(d => !d.preliminary) || turn.decisions.at(-1);
  const time = (value: number) => Number((value / 1000).toFixed(3)) + '秒';
  return <div className="space-y-1">
    <blockquote className="border-l-2 border-teal-500 pl-2 text-sm">{turn.words}</blockquote>
    {decision ? <>
      <p className="font-semibold">{decision.preliminary ? '先読みの候補' : '行き先'}　{decision.route || '判断なし'}</p>
      <p>画面　{decision.look === null ? '判断なし' : decision.look ? '見る' : '見ない'}</p>
      <p>{decision.reason}</p>
      {decision.criterion && <p className="text-stone-600">選んだ基準　{decision.criterion}</p>}
      {decision.ms != null && <p>{decision.model} · 判断にかかった時間　{time(decision.ms)}</p>}
      {decision.words !== turn.words.trim() && <p>判断に使った言葉　{decision.words}</p>}
      {turn.decisions.length > 1 && <details><summary className="cursor-pointer">この発言での判断の経過</summary>
        <ol className="space-y-1 pt-1">{turn.decisions.filter(d => d !== decision).map((d,i) => <li key={i}>「{d.words}」 {d.preliminary ? '先読み' : '振り分け'} · {d.route || '判断なし'} · {d.ms == null ? '時間の記録なし' : time(d.ms)}</li>)}</ol>
      </details>}
    </> : <p className="text-stone-600">この発言の振り分けはまだ記録されていません。</p>}
  </div>;
}

export function ChangeList({ changes }: { changes: Change[] }) {
  if (!changes.length) return null;
  return <ol className="space-y-2 border-l-2 border-indigo-200 pl-3">
    {changes.map(change => <li key={change.id}>
      <div className="flex items-baseline gap-2 text-xs text-stone-600"><strong>{change.phase}</strong>
        <time>{new Date(change.at).toLocaleString('ja-JP', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</time></div>
      <p className="whitespace-pre-wrap break-words">{change.text}</p>
    </li>)}
  </ol>;
}
