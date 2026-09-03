'use client';

/**
 * 部屋ボード v3 — インスタ的「1目標=1画面」カルーセル。
 *
 * カードは4段だけ:
 *   ① 目標（なぜ＋何を）
 *   ② アバター（表情＝誰待ち。you/dan/external の3表情）
 *   ③ 今、誰の何待ちか
 *   ④ それが来たら何ができるか
 * 経緯・やったこと・履歴は表面に出さない（気になればチャットで聞く）。
 *
 * 左右ボタン／スワイプ／スクロールで他の目標へ（scroll-snap）。
 * 更新はSSE購読で完全リアルタイム。更新された画面は一瞬光る。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowDown,
  ChevronLeft,
  ChevronRight,
  Flag,
  Hourglass,
  Loader2,
  RefreshCw,
  Unlock,
} from 'lucide-react';
import { api, RoomBoardGoal, RoomBoardResponse } from '@/lib/api-client';

const ball = {
  you: {
    avatar: '/board-avatar/you.png',
    chip: 'bg-amber-400/20 text-amber-700 dark:text-amber-300',
    ring: '#f59e0b',
    waitLabel: (g: RoomBoardGoal) => `${g.ball_label || 'あなた'}の番`,
  },
  dan: {
    avatar: '/board-avatar/dan.png',
    chip: 'bg-sky-400/20 text-sky-700 dark:text-sky-300',
    ring: '#0ea5e9',
    waitLabel: () => 'ダンが進行中',
  },
  external: {
    avatar: '/board-avatar/external.png',
    chip: 'bg-zinc-400/20 text-zinc-700 dark:text-zinc-300',
    ring: '#71717a',
    waitLabel: (g: RoomBoardGoal) => `${g.ball_label || '外部'}待ち`,
  },
} as const;

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function GoalPanel({ goal, flash }: { goal: RoomBoardGoal; flash: boolean }) {
  const b = ball[goal.ball] ?? ball.dan;
  return (
    <div
      className={`flex h-full w-full shrink-0 snap-center flex-col justify-center overflow-y-auto rounded-2xl border border-border bg-card p-5 md:p-7 ${
        goal.stale ? 'opacity-70' : ''
      } ${flash ? 'board-flash' : ''}`}
      style={{ scrollSnapStop: 'always' }}
    >
      {/* ① 目的（ゴールフラッグ＝目指す場所。PCは左上寄せ） */}
      <div className="mx-auto flex w-fit max-w-2xl shrink-0 items-center gap-2.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 md:mx-0 md:self-start">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-500/90">
          <Flag className="h-[18px] w-[18px] text-white" />
        </span>
        <span className="text-[16px] font-bold leading-snug text-emerald-800 dark:text-emerald-200 md:text-[18px]">
          {goal.title}
        </span>
      </div>

      {/* 本体: PC=横並び / モバイル=縦積み */}
      <div className="mt-4 flex shrink-0 flex-col md:mt-5 md:flex-row md:items-center md:gap-7">
        {/* ② アバター＋誰待ち */}
        <div className="flex shrink-0 flex-col items-center justify-center md:w-[36%] md:max-w-[300px]">
          <img src={b.avatar} alt="" className="h-36 w-auto object-contain md:h-64 lg:h-72" />
          <span className={`mt-2.5 rounded-full px-4 py-1.5 text-[15px] font-bold ${b.chip}`}>
            {b.waitLabel(goal)}
          </span>
        </div>

        {/* ③ 主役: いま何待ち（砂時計＋手番色の太枠で強調） ＋ ④ これが来たら */}
        <div className="mt-4 flex min-w-0 flex-1 flex-col justify-center md:mt-0">
          <div
            className="rounded-2xl border-l-[5px] p-4 md:p-5"
            style={{ borderColor: b.ring, background: `${b.ring}14` }}
          >
            <div className="flex items-center gap-1.5 text-[15px] font-bold tracking-wide md:text-[17px]" style={{ color: b.ring }}>
              <Hourglass className="h-[18px] w-[18px]" />
              今は…
            </div>
            {/* ◯◯待ち を大きく */}
            <div className="mt-1.5 text-[25px] font-bold leading-tight md:text-[34px]">
              {goal.waiting_on || '—'}
            </div>
            {/* 補足は小さく */}
            {goal.waiting_note ? (
              <div className="mt-1.5 text-[13px] leading-snug text-muted-foreground">
                {goal.waiting_note}
              </div>
            ) : null}
          </div>

          {/* 流れの矢印 */}
          <div className="my-1.5 flex justify-center">
            <ArrowDown className="h-4 w-4 text-muted-foreground/50" />
          </div>

          {/* ④ Next→（解錠＝次に進める） */}
          <div className="flex items-start gap-2.5 rounded-xl border border-border bg-muted/30 px-4 py-3">
            <Unlock className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
            <div className="min-w-0">
              <div className="text-[11px] font-bold tracking-wide text-emerald-600 dark:text-emerald-400">Next →</div>
              <div className="mt-0.5 text-[15px] leading-snug text-foreground/85 md:text-[16px]">
                {goal.then || '—'}
              </div>
            </div>
          </div>

          <div className="mt-3 text-[11px] text-muted-foreground/60">
            {formatTime(goal.updated_at)} 更新{goal.stale ? '・しばらく動きなし' : ''}
          </div>
        </div>
      </div>
    </div>
  );
}

export function RoomBoard({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [flashIds, setFlashIds] = useState<Set<string>>(new Set());
  const [current, setCurrent] = useState(0);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const prevUpdatedRef = useRef<Record<string, string>>({});

  const { data, isLoading } = useQuery({
    queryKey: ['room-board', projectId],
    queryFn: () => api.projects.getBoard(projectId),
    enabled: !!projectId,
    refetchInterval: 30000,
  });

  // SSE購読 = 本線
  useEffect(() => {
    if (!projectId) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/v1/projects/${projectId}/board/stream`);
      es.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data) as RoomBoardResponse;
          queryClient.setQueryData(['room-board', projectId], payload);
        } catch {
          /* 不正フレームは無視 */
        }
      };
    } catch {
      /* 非対応環境はポーリングのみ */
    }
    return () => es?.close();
  }, [projectId, queryClient]);

  const board = data?.board ?? null;
  const goals = board?.goals ?? [];

  useEffect(() => {
    const prev = prevUpdatedRef.current;
    const changed: string[] = [];
    for (const g of goals) {
      if (g.updated_at && prev[g.id] && prev[g.id] !== g.updated_at) changed.push(g.id);
    }
    prevUpdatedRef.current = Object.fromEntries(goals.map((g) => [g.id, g.updated_at ?? '']));
    if (changed.length) {
      setFlashIds(new Set(changed));
      const timer = setTimeout(() => setFlashIds(new Set()), 2000);
      return () => clearTimeout(timer);
    }
  }, [goals]);

  const go = useCallback((idx: number) => {
    const el = scrollerRef.current;
    if (!el) return;
    const clamped = Math.max(0, Math.min(idx, el.children.length - 1));
    (el.children[clamped] as HTMLElement)?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }, []);

  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setCurrent(Math.round(el.scrollLeft / el.clientWidth));
  }, []);

  const refreshMutation = useMutation({
    mutationFn: () => api.projects.refreshBoard(projectId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['room-board', projectId] }),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!board || !goals.length) {
    return (
      <div className="mx-4 mt-4 rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        まだ目標がありません。会話するとダンがこの部屋の目標と現在地をここに整理していきます。
      </div>
    );
  }

  return (
    <div className="mx-3 mt-3 flex h-[62vh] min-h-[460px] flex-col">
      <style>{`
        .board-flash { animation: board-flash-anim 1.6s ease; }
        @keyframes board-flash-anim {
          0% { box-shadow: 0 0 0 2px rgba(16,185,129,0.7), 0 0 24px rgba(16,185,129,0.35); }
          100% { box-shadow: 0 0 0 0 rgba(16,185,129,0); }
        }
        .board-scroller::-webkit-scrollbar { display: none; }
        .board-scroller { scrollbar-width: none; }
      `}</style>

      <div className="mb-2 flex items-center justify-between px-1">
        <span className="text-[13px] font-semibold text-muted-foreground">
          目標 {goals.length} 件{' '}
          <span className="text-muted-foreground/60">（{current + 1}/{goals.length}）</span>
        </span>
        <div className="flex items-center gap-1.5">
          {board.updated_at ? (
            <span className="text-[11px] text-muted-foreground/70">{formatTime(board.updated_at)} 更新</span>
          ) : null}
          <button
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
            title="今すぐ更新"
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            {refreshMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollerRef}
          onScroll={onScroll}
          className="board-scroller flex h-full snap-x snap-mandatory gap-3 overflow-x-auto overflow-y-hidden scroll-smooth"
        >
          {goals.map((g) => (
            <GoalPanel key={g.id} goal={g} flash={flashIds.has(g.id)} />
          ))}
        </div>

        {current > 0 && (
          <button
            onClick={() => go(current - 1)}
            className="absolute left-1 top-1/2 hidden -translate-y-1/2 rounded-full border border-border bg-background/80 p-2 shadow backdrop-blur hover:bg-background md:block"
            aria-label="前の目標"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
        )}
        {current < goals.length - 1 && (
          <button
            onClick={() => go(current + 1)}
            className="absolute right-1 top-1/2 hidden -translate-y-1/2 rounded-full border border-border bg-background/80 p-2 shadow backdrop-blur hover:bg-background md:block"
            aria-label="次の目標"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        )}
      </div>

      <div className="mt-2.5 flex items-center justify-center gap-1.5">
        {goals.map((g, i) => (
          <button
            key={g.id}
            onClick={() => go(i)}
            className={`h-1.5 rounded-full transition-all ${
              i === current ? 'w-5 bg-foreground/70' : 'w-1.5 bg-foreground/25'
            }`}
            aria-label={`目標 ${i + 1}`}
          />
        ))}
      </div>
    </div>
  );
}
