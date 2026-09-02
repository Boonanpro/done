'use client';

/**
 * 部屋ボード — 部屋の「今」をポストイット＋因果矢印で示すフリーボード。
 *
 * - 付箋の色＝手番（黄=あなた / 青=ダン / 灰=待ち）、色あせ＝停滞
 * - 矢印＝因果・依存（これが決まる/終わると、これが動く）
 * - 完了・中止した付箋は貼られない（消化が削除する）
 * - 付箋はドラッグで並べ替え可。配置はサーバーに保存され、ダンは動かさない
 *
 * データはバックエンドのポーラーが会話を消化して更新する。ここは5秒ポーリング。
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, RefreshCw } from 'lucide-react';
import {
  api,
  RoomBoardArrow,
  RoomBoardNote,
} from '@/lib/api-client';

const NOTE_W = 264;
const CANVAS_W = 980;
const GRID_X = [30, 330, 630];
const GRID_ROW_H = 185;
const EST_H = 160; // 衝突判定用の付箋想定高さ

type XY = { x: number; y: number };

const noteColors: Record<RoomBoardNote['owner'], { bg: string; edge: string }> = {
  you: { bg: '#fde047', edge: '#eab308' },
  dan: { bg: '#7dd3fc', edge: '#0ea5e9' },
  wait: { bg: '#d6d3d1', edge: '#a8a29e' },
};

function overlaps(a: XY, b: XY): boolean {
  return Math.abs(a.x - b.x) < NOTE_W + 20 && Math.abs(a.y - b.y) < EST_H + 20;
}

/** 保存済み配置が無い付箋の自動配置。矢印の親の近くへ、無ければ空きグリッドへ。 */
function autoLayout(
  notes: RoomBoardNote[],
  arrows: RoomBoardArrow[],
  fixed: Record<string, XY>
): Record<string, XY> {
  const placed: Record<string, XY> = { ...fixed };
  const result: Record<string, XY> = {};

  const slots: XY[] = [];
  for (let row = 0; row < 24; row++) {
    for (const x of GRID_X) slots.push({ x, y: 30 + row * GRID_ROW_H });
  }
  const isFree = (p: XY) => Object.values(placed).every((q) => !overlaps(p, q));
  const nearestFree = (desired: XY): XY => {
    let best: XY | null = null;
    let bestD = Infinity;
    for (const s of slots) {
      if (!isFree(s)) continue;
      const d = (s.x - desired.x) ** 2 + (s.y - desired.y) ** 2;
      if (d < bestD) {
        bestD = d;
        best = s;
      }
    }
    return best ?? desired;
  };

  let cursor = 0;
  for (const n of notes) {
    if (placed[n.id]) continue;
    const parent = arrows.find((a) => a.to === n.id && placed[a.from]);
    const child = arrows.find((a) => a.from === n.id && placed[a.to]);
    let desired: XY | null = null;
    if (parent) desired = { x: placed[parent.from].x + 40, y: placed[parent.from].y + GRID_ROW_H };
    else if (child) desired = { x: placed[child.to].x - 40, y: placed[child.to].y - GRID_ROW_H };
    if (!desired) {
      while (cursor < slots.length && !isFree(slots[cursor])) cursor++;
      desired = slots[Math.min(cursor, slots.length - 1)];
    }
    const p = nearestFree(desired);
    placed[n.id] = p;
    result[n.id] = p;
  }
  return result;
}

/** 矩形境界上のアンカー: 中心同士を結ぶ直線と矩形の交点（簡易） */
function anchor(from: { cx: number; cy: number; w: number; h: number }, to: { cx: number; cy: number }): XY {
  const dx = to.cx - from.cx;
  const dy = to.cy - from.cy;
  const hw = from.w / 2 + 6;
  const hh = from.h / 2 + 6;
  const scale = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh, 1e-6);
  return { x: from.cx + dx * Math.min(scale, 1) * 0.999, y: from.cy + dy * Math.min(scale, 1) * 0.999 };
}

function PostItNote({
  note,
  pos,
  isNew,
  delay,
  onDragEnd,
  onMeasure,
  onDrag,
}: {
  note: RoomBoardNote;
  pos: XY;
  isNew: boolean;
  delay: number;
  onDragEnd: (id: string, p: XY) => void;
  onDrag: (id: string, p: XY) => void;
  onMeasure: (id: string, el: HTMLDivElement | null) => void;
}) {
  const c = noteColors[note.owner] ?? noteColors.wait;
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number; moved: boolean } | null>(null);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
      dragRef.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y, moved: false };
    },
    [pos.x, pos.y]
  );
  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = e.clientX - d.startX;
      const dy = e.clientY - d.startY;
      if (!d.moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      d.moved = true;
      onDrag(note.id, {
        x: Math.max(0, Math.min(CANVAS_W - NOTE_W, d.origX + dx)),
        y: Math.max(0, d.origY + dy),
      });
    },
    [note.id, onDrag]
  );
  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const d = dragRef.current;
      dragRef.current = null;
      if (d?.moved) {
        const dx = e.clientX - d.startX;
        const dy = e.clientY - d.startY;
        onDragEnd(note.id, {
          x: Math.max(0, Math.min(CANVAS_W - NOTE_W, d.origX + dx)),
          y: Math.max(0, d.origY + dy),
        });
      }
    },
    [note.id, onDragEnd]
  );

  const isDecision = note.kind === 'decision';
  return (
    <div
      ref={(el) => onMeasure(note.id, el)}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      className={`absolute cursor-grab touch-none select-none rounded-sm shadow-[4px_6px_14px_rgba(0,0,0,0.45)] active:cursor-grabbing ${
        note.stale ? 'opacity-45' : ''
      } ${isNew ? 'board-note-stick' : ''}`}
      style={{
        left: pos.x,
        top: pos.y,
        width: isDecision ? NOTE_W - 30 : NOTE_W,
        background: c.bg,
        borderTop: `6px solid ${c.edge}`,
        color: '#1c1917',
        animationDelay: isNew ? `${delay}s` : undefined,
        padding: isDecision ? '10px 12px 10px' : '14px 14px 12px',
      }}
    >
      <div className={`font-bold leading-snug ${isDecision ? 'text-[14px]' : 'text-[16.5px]'}`}>
        {isDecision ? <span className="mr-1">📌</span> : null}
        {note.title}
      </div>
      {note.body ? (
        <div className="mt-1.5 text-[13px] leading-snug text-[#44403c]">{note.body}</div>
      ) : null}
      {note.live ? (
        <div className="mt-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-[#075985]">
          <span className="board-live-dot h-2 w-2 shrink-0 rounded-full bg-[#0284c7]" />
          {note.live}
        </div>
      ) : null}
      {note.due ? (
        <div className="mt-2 inline-block rounded-full bg-black/10 px-2.5 py-0.5 text-[11.5px] font-semibold text-[#44403c]">
          {note.due}
        </div>
      ) : null}
    </div>
  );
}

export function RoomBoard({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['room-board', projectId],
    queryFn: () => api.projects.getBoard(projectId),
    enabled: !!projectId,
    refetchInterval: 5000,
  });

  const refreshMutation = useMutation({
    mutationFn: () => api.projects.refreshBoard(projectId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['room-board', projectId] }),
  });
  const positionsMutation = useMutation({
    mutationFn: (positions: Record<string, XY>) =>
      api.projects.updateBoardPositions(projectId, positions),
  });

  const board = data?.board ?? null;
  const notes = useMemo(() => board?.notes ?? [], [board?.notes]);
  const arrows = useMemo(() => board?.arrows ?? [], [board?.arrows]);
  const serverPos = useMemo(() => board?.positions ?? {}, [board?.positions]);

  // ドラッグ中/直後のローカル配置（サーバー確定まで優先）
  const [dragPos, setDragPos] = useState<Record<string, XY>>({});
  // 「貼られる」アニメーションは、開いている間に本当に増えた付箋だけ。
  // 初回表示・部屋切替・再マウントでは動かさない（毎回流れるとうるさい）。
  const seenIdsRef = useRef<Set<string> | null>(null);
  const [newIds, setNewIds] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!board) return;
    const ids = notes.map((n) => n.id);
    if (seenIdsRef.current === null) {
      seenIdsRef.current = new Set(ids);
      return;
    }
    const seen = seenIdsRef.current;
    const fresh = ids.filter((id) => !seen.has(id));
    if (fresh.length) {
      ids.forEach((id) => seen.add(id));
      setNewIds((prev) => ({
        ...prev,
        ...Object.fromEntries(fresh.map((id, i) => [id, i * 0.12])),
      }));
    }
  }, [board, notes]);

  const autoPos = useMemo(
    () => autoLayout(notes, arrows, { ...serverPos, ...dragPos }),
    [notes, arrows, serverPos, dragPos]
  );
  const posOf = useCallback(
    (id: string): XY => dragPos[id] ?? serverPos[id] ?? autoPos[id] ?? { x: 30, y: 30 },
    [dragPos, serverPos, autoPos]
  );

  // 実測サイズ（矢印のアンカー計算用）
  const [sizes, setSizes] = useState<Record<string, { w: number; h: number }>>({});
  const elsRef = useRef<Record<string, HTMLDivElement | null>>({});
  const onMeasure = useCallback((id: string, el: HTMLDivElement | null) => {
    elsRef.current[id] = el;
  }, []);
  useLayoutEffect(() => {
    const next: Record<string, { w: number; h: number }> = {};
    let changed = false;
    for (const n of notes) {
      const el = elsRef.current[n.id];
      if (!el) continue;
      next[n.id] = { w: el.offsetWidth, h: el.offsetHeight };
      const prev = sizes[n.id];
      if (!prev || prev.w !== next[n.id].w || prev.h !== next[n.id].h) changed = true;
    }
    if (changed || Object.keys(next).length !== Object.keys(sizes).length) setSizes(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes, dragPos, serverPos]);

  const onDrag = useCallback((id: string, p: XY) => {
    setDragPos((prev) => ({ ...prev, [id]: p }));
  }, []);
  const onDragEnd = useCallback(
    (id: string, p: XY) => {
      setDragPos((prev) => ({ ...prev, [id]: p }));
      positionsMutation.mutate({ [id]: p });
    },
    [positionsMutation]
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const canvasH = Math.max(
    420,
    ...notes.map((n) => posOf(n.id).y + (sizes[n.id]?.h ?? EST_H) + 60)
  );

  return (
    <div className="mx-4 mt-4">
      <style>{`
        .board-live-dot { animation: board-blink 1.2s ease-in-out infinite; }
        @keyframes board-blink { 0%,100% { opacity: 1 } 50% { opacity: 0.25 } }
        .board-note-stick { animation: board-stick 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) both; }
        @keyframes board-stick {
          from { opacity: 0; transform: scale(1.25); }
          to { opacity: 1; transform: scale(1); }
        }
        .board-arrow { animation: board-fadein 0.5s ease both; }
        @keyframes board-fadein { from { opacity: 0 } to { opacity: 1 } }
      `}</style>

      {/* 凡例 + 更新 */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: noteColors.you.bg }} />
            あなた
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: noteColors.dan.bg }} />
            ダン
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: noteColors.wait.bg }} />
            待ち
          </span>
          <span className="text-muted-foreground/60">矢印＝これが動くとこれが動く</span>
        </div>
        <div className="flex items-center gap-1.5">
          {board?.updated_at ? (
            <span className="text-[10px] text-muted-foreground/70">
              {new Date(board.updated_at).toLocaleString('ja-JP', {
                month: 'numeric',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}{' '}
              更新
            </span>
          ) : null}
          <button
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
            title="今すぐ更新"
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            {refreshMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* ボード面 */}
      {!board || !notes.length ? (
        <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          まだ付箋がありません。会話するとダンがここに現在地を貼っていきます。
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl">
          <div
            className="relative"
            style={{
              width: CANVAS_W,
              height: canvasH,
              background:
                'radial-gradient(circle, rgba(127,127,127,0.18) 1px, transparent 1px) 0 0 / 26px 26px, hsl(var(--muted) / 0.3)',
            }}
          >
            {/* 矢印レイヤー */}
            <svg className="pointer-events-none absolute inset-0 h-full w-full">
              <defs>
                <marker id="board-arrowhead" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                  <path d="M 0 0 L 8 4 L 0 8 Z" fill="rgba(127,127,127,0.75)" />
                </marker>
              </defs>
              {arrows.map((a) => {
                const fp = posOf(a.from);
                const tp = posOf(a.to);
                const fs = sizes[a.from] ?? { w: NOTE_W, h: EST_H };
                const ts = sizes[a.to] ?? { w: NOTE_W, h: EST_H };
                const fc = { cx: fp.x + fs.w / 2, cy: fp.y + fs.h / 2, w: fs.w, h: fs.h };
                const tc = { cx: tp.x + ts.w / 2, cy: tp.y + ts.h / 2, w: ts.w, h: ts.h };
                const p1 = anchor(fc, tc);
                const p2 = anchor(tc, fc);
                const mx = (p1.x + p2.x) / 2;
                const my = (p1.y + p2.y) / 2;
                // 軽くカーブさせる（法線方向に膨らみ）
                const nx = -(p2.y - p1.y) * 0.15;
                const ny = (p2.x - p1.x) * 0.15;
                return (
                  <g key={`${a.from}-${a.to}`} className="board-arrow">
                    <path
                      d={`M ${p1.x} ${p1.y} Q ${mx + nx} ${my + ny} ${p2.x} ${p2.y}`}
                      fill="none"
                      stroke="rgba(127,127,127,0.75)"
                      strokeWidth={1.8}
                      markerEnd="url(#board-arrowhead)"
                    />
                    {a.label ? (
                      <text
                        x={mx + nx}
                        y={my + ny - 6}
                        textAnchor="middle"
                        fill="rgba(127,127,127,0.95)"
                        fontSize={12.5}
                      >
                        {a.label}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </svg>

            {/* 付箋レイヤー */}
            {notes.map((n) => (
              <PostItNote
                key={n.id}
                note={n}
                pos={posOf(n.id)}
                isNew={n.id in newIds}
                delay={newIds[n.id] ?? 0}
                onDrag={onDrag}
                onDragEnd={onDragEnd}
                onMeasure={onMeasure}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
