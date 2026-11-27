'use client';

// 部品 MapPlan の描き方: ダン自身の直す所を、指示文の地図の箱に番号で結んで見せる（2026-11-27 本人「何をどう変えてその結果
// どうなる見込みかを、左にある指示文のマップと紐づけて直感的に」）。
// - 上: 指示文の地図のうち直す箱とその隣だけを切り出した小さな地図。直す箱は本物の絵＋紫の番号、ほかは薄く。
// - 下: 直す所ごとのカード（番号・箱の絵と名前・何を直すか／今／直した後／見込み）。押すと指示文の地図のその箱が開く
//   （lib/map-focus.ts。同じ画面・開発室の枠の中・どちらも無ければ新しいタブ）。
// - 出た時に番号を指示文の大きな地図にも出す（announcePlan。最後に出た案が残る）。
// 箱の位置は本人が並べ替えた物（/api/v1/prompts/board-layout）を読めればそれ、読めなければ architecture.ts の既定。
import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, MapPin } from 'lucide-react';

import { BOARD_EDGES, BOARD_NODES, BOX_H, type ArchNode } from '@/components/prompts/architecture';
import { announcePlan, focusMapBox } from '@/lib/map-focus';
import { promptRequest } from '@/lib/prompts-api';
import type { MapPlanInput } from '@/lib/chat-shapes/schema';

type Box = { x: number; y: number; w: number; h: number };
const BY_ID = new Map<string, ArchNode>(BOARD_NODES.map((n) => [n.id, n]));
const icon = (n: ArchNode) => `/prompts/arch/${n.icon}.webp`;

let layoutOnce: Promise<Record<string, Box>> | null = null;
function boardLayout(): Promise<Record<string, Box>> {
  layoutOnce ??= promptRequest<{ nodes?: Record<string, Box> }>('/board-layout').then((r) => r?.nodes || {}).catch(() => ({}));
  return layoutOnce;
}

function MiniMap({ marks, layout, onPick }: { marks: Map<string, number[]>; layout: Record<string, Box>; onPick: (id: string) => void }) {
  const boxOf = (n: ArchNode): Box => layout[n.id] || { x: n.x, y: n.y, w: n.w, h: n.height ?? BOX_H };
  const view = useMemo(() => {
    const targets = BOARD_NODES.filter((n) => marks.has(n.id));
    if (!targets.length) return null;
    // 直す箱と、線でつながった隣の箱まで入れて、その周りを切り出す
    const near = new Set(targets.map((n) => n.id));
    for (const e of BOARD_EDGES) {
      if (marks.has(e.from)) near.add(e.to);
      if (marks.has(e.to)) near.add(e.from);
    }
    const tb = targets.map(boxOf);
    let x0 = Math.min(...tb.map((b) => b.x)), y0 = Math.min(...tb.map((b) => b.y));
    let x1 = Math.max(...tb.map((b) => b.x + b.w)), y1 = Math.max(...tb.map((b) => b.y + b.h));
    // 隣は、切り出しが大きくなりすぎない範囲だけ足す
    for (const id of near) {
      const n = BY_ID.get(id); if (!n) continue;
      const b = boxOf(n);
      const nx0 = Math.min(x0, b.x), ny0 = Math.min(y0, b.y), nx1 = Math.max(x1, b.x + b.w), ny1 = Math.max(y1, b.y + b.h);
      if ((nx1 - nx0) <= Math.max(900, (x1 - x0) * 1.6) && (ny1 - ny0) <= Math.max(700, (y1 - y0) * 1.6)) { x0 = nx0; y0 = ny0; x1 = nx1; y1 = ny1; }
    }
    const pad = 36;
    x0 -= pad; y0 -= pad + 20; x1 += pad; y1 += pad;
    // 横長すぎ・縦長すぎにしない（チャットの幅で読める形）
    const w = x1 - x0, h = y1 - y0;
    if (h < w * 0.42) { const add = (w * 0.42 - h) / 2; y0 -= add; y1 += add; }
    if (h > w * 0.9) { const add = (h / 0.9 - w) / 2; x0 -= add; x1 += add; }
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marks, layout]);
  if (!view) return null;
  const inView = (b: Box) => b.x + b.w > view.x && b.x < view.x + view.w && b.y + b.h > view.y && b.y < view.y + view.h;
  const font = Math.max(15, view.w / 30);
  const r = Math.max(15, view.w / 40);
  const center = (b: Box): [number, number] => [b.x + b.w / 2, b.y + b.h / 2];
  return (
    <svg viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} className="block w-full rounded-lg border border-border bg-[#faf8f4]" role="img" aria-label="指示文の地図で直す所" data-map-plan-mini>
      {BOARD_EDGES.map((e, i) => {
        const a = BY_ID.get(e.from), b = BY_ID.get(e.to);
        if (!a || !b) return null;
        const ba = boxOf(a), bb = boxOf(b);
        if (!inView(ba) && !inView(bb)) return null;
        const hot = marks.has(e.from) || marks.has(e.to);
        const [ax, ay] = center(ba), [bx, by] = center(bb);
        return <line key={i} x1={ax} y1={ay} x2={bx} y2={by} stroke={hot ? '#8b5cf6' : '#d6d3d1'} strokeWidth={hot ? font / 6 : font / 9} strokeDasharray={e.dashed ? `${font / 2} ${font / 3}` : undefined} />;
      })}
      {BOARD_NODES.map((n) => {
        const b = boxOf(n);
        if (!inView(b)) return null;
        const nums = marks.get(n.id);
        const on = !!nums;
        const imgH = b.h - font * 1.5;
        return (
          <g key={n.id} opacity={on ? 1 : 0.42} style={{ cursor: on ? 'pointer' : undefined }} onClick={on ? () => onPick(n.id) : undefined}>
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={12} fill={on ? '#f5f3ff' : '#ffffff'} stroke={on ? '#7c3aed' : '#d6d3d1'} strokeWidth={on ? font / 4 : 2} />
            {imgH > 10 ? <image href={icon(n)} x={b.x + 4} y={b.y + 4} width={b.w - 8} height={imgH - 4} preserveAspectRatio="xMidYMid meet" /> : null}
            <text x={b.x + b.w / 2} y={b.y + b.h - font * 0.35} textAnchor="middle" fontSize={on ? font : font * 0.8} fontWeight={on ? 700 : 500} fill={on ? '#3b0764' : '#57534e'}
              stroke="#ffffff" strokeWidth={font / 5} paintOrder="stroke">{n.name}</text>
            {nums ? nums.map((k, i) => (
              <g key={k}>
                <circle cx={b.x + i * r * 2.1} cy={b.y} r={r} fill="#7c3aed" stroke="#ffffff" strokeWidth={r / 5} />
                <text x={b.x + i * r * 2.1} y={b.y + r * 0.36} textAnchor="middle" fontSize={r * 1.05} fontWeight={800} fill="#ffffff">{k}</text>
              </g>
            )) : null}
          </g>
        );
      })}
    </svg>
  );
}

export function MapPlanView({ plan, box }: { plan: MapPlanInput; box: string }) {
  const changes = plan.changes || [];
  const [layout, setLayout] = useState<Record<string, Box>>({});
  useEffect(() => { let live = true; void boardLayout().then((l) => { if (live) setLayout(l); }); return () => { live = false; }; }, []);
  const marks = useMemo(() => {
    const m = new Map<string, number[]>();
    changes.forEach((c, i) => { if (c?.node && BY_ID.has(c.node)) m.set(c.node, [...(m.get(c.node) || []), i + 1]); });
    return m;
  }, [changes]);
  const key = changes.map((c) => `${c?.node}:${c?.title}`).join('|');
  useEffect(() => {
    if (!key) return;
    announcePlan(changes.flatMap((c, i) => (c?.node ? [{ node: c.node, n: i + 1, title: c.title || '' }] : [])));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return (
    <div className={`${box} flex flex-col gap-2`} data-shape="MapPlan">
      {plan.title ? <div className="text-[15px] font-bold leading-snug">{plan.title}</div> : null}
      <MiniMap marks={marks} layout={layout} onPick={focusMapBox} />
      <ol className="m-0 flex list-none flex-col gap-2 p-0">
        {changes.map((c, i) => {
          const n = c?.node ? BY_ID.get(c.node) : undefined;
          return (
            <li key={i}>
              <button type="button" onClick={() => c?.node && focusMapBox(c.node)} data-map-plan-change={c?.node}
                className="group flex w-full gap-2.5 rounded-lg border border-border bg-background/40 p-2 text-left transition-colors hover:border-violet-500/70 hover:bg-violet-500/5">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-violet-600 text-sm font-extrabold text-white">{i + 1}</span>
                <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <span className="flex items-center gap-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    {n ? <img src={icon(n)} alt="" className="h-9 w-9 shrink-0 rounded-md border border-border bg-white object-contain" /> : null}
                    <span className="min-w-0">
                      <span className="block text-[15px] font-bold leading-tight">{c?.title}</span>
                      <span className="flex items-center gap-1 text-[11px] text-muted-foreground"><MapPin className="h-3 w-3" />{n?.name || c?.node}<span className="opacity-0 transition-opacity group-hover:opacity-100">・地図で見る ›</span></span>
                    </span>
                  </span>
                  <span className="grid grid-cols-1 items-stretch gap-1.5 sm:grid-cols-[1fr_auto_1fr]">
                    <span className="rounded-md bg-rose-500/10 px-2 py-1.5 text-[13px] leading-snug"><b className="mr-1 text-[11px] text-rose-600">今</b>{c?.now}</span>
                    <ArrowRight className="hidden h-4 w-4 self-center text-muted-foreground sm:block" />
                    <span className="rounded-md bg-emerald-500/10 px-2 py-1.5 text-[13px] leading-snug"><b className="mr-1 text-[11px] text-emerald-600">直した後</b>{c?.after}</span>
                  </span>
                  {c?.effect ? <span className="text-[13px] font-semibold text-violet-600 dark:text-violet-300">→ {c.effect}</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {plan.goal ? <div className="rounded-md bg-violet-500/10 px-2.5 py-1.5 text-sm font-semibold">{plan.goal}</div> : null}
    </div>
  );
}
