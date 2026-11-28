'use client';

// 部品 MapPlan の描き方: ダン自身の直す所を、指示文の地図の箱に番号で結んで見せる（2026-11-27 本人「何をどう変えてその結果
// どうなる見込みかを、左にある指示文のマップと紐づけて直感的に」）。
// - 上: 直す箱を、指示文の地図の左から右（流れの順）に地図と同じ絵で並べ、紫の番号を付ける。地図をそのまま縮めると
//   チャットの幅では箱も字も小さすぎて読めなかった（試しで確かめた）ので、箱だけを流れの順に並べる。
// - 下: 直す所ごとのカード（番号・箱の絵と名前・何を直すか／今／直した後／見込み）。押すと指示文の地図のその箱が開く
//   （lib/map-focus.ts。同じ画面・開発室の枠の中・どちらも無ければ新しいタブ）。
// - 出た時に番号を指示文の大きな地図にも出す（announcePlan。最後に出た案が残る）。
// 箱の位置は本人が並べ替えた物（/api/v1/prompts/board-layout）を読めればそれ、読めなければ architecture.ts の既定。
import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, MapPin } from 'lucide-react';

import { BOARD_NODES, BOX_H, NODE_ALIAS, type ArchNode } from '@/components/prompts/architecture';
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

/** 直す箱を、指示文の地図の左から右（流れの順）に、地図と同じ絵で並べる。番号は下のカードと同じ */
function BoxStrip({ marks, layout, onPick }: { marks: Map<string, number[]>; layout: Record<string, Box>; onPick: (id: string, n?: number) => void }) {
  const boxOf = (n: ArchNode): Box => layout[n.id] || { x: n.x, y: n.y, w: n.w, h: n.height ?? BOX_H };
  const targets = BOARD_NODES.filter((n) => marks.has(n.id))
    .sort((a, b) => { const A = boxOf(a), B = boxOf(b); return A.x - B.x || A.y - B.y; });
  if (!targets.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-2 rounded-lg border border-border bg-[#faf8f4] p-2" aria-label="指示文の地図で直す所（左から流れの順）" data-map-plan-strip>
      {targets.map((n, i) => (
        <div key={n.id} className="flex items-center gap-1">
          {i ? <ArrowRight className="h-4 w-4 shrink-0 text-stone-400" /> : null}
          <button type="button" onClick={() => onPick(n.id, marks.get(n.id)?.[0])} title="指示文の地図でこの箱を開く"
            className="relative flex w-[84px] flex-col items-center gap-0.5 rounded-lg border-2 border-violet-500 bg-white px-1 pb-1 pt-2 hover:bg-violet-50">
            <span className="absolute -left-2 -top-2 flex gap-0.5">
              {marks.get(n.id)!.map((k) => <span key={k} className="flex h-5 min-w-5 items-center justify-center rounded-full bg-violet-600 px-1 text-[11px] font-extrabold text-white">{k}</span>)}
            </span>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={icon(n)} alt="" className="h-12 w-full object-contain" />
            <span className="line-clamp-2 text-center text-[11px] font-bold leading-tight text-stone-900">{n.name}</span>
          </button>
        </div>
      ))}
    </div>
  );
}

/** 指示文を書き換える案の、今の文と直した後の文（実物の言葉）。指示文の画面の箱の中身でも同じ物を出す */
export function TextChange({ quote, rewrite, light }: { quote?: string | null; rewrite?: string | null; light?: boolean }) {
  return (
    <span className="flex flex-col gap-1 text-[13px] leading-relaxed" data-map-plan-text>
      <span className={light ? 'text-[11px] font-bold text-stone-500' : 'text-[11px] font-bold text-muted-foreground'}>指示文の言葉</span>
      {quote ? <span className="rounded-md border border-rose-400/40 bg-rose-500/5 px-2 py-1"><b className="mr-1 text-[11px] text-rose-600">今の文</b><span className="whitespace-pre-wrap">「{quote}」</span></span> : null}
      {rewrite ? <span className="rounded-md border border-emerald-500/40 bg-emerald-500/5 px-2 py-1"><b className="mr-1 text-[11px] text-emerald-600">{quote ? 'こう書き換える' : '足す文'}</b><span className="whitespace-pre-wrap">「{rewrite}」</span></span>
        : quote ? <span className="text-[12px] text-rose-600">この文を消す</span> : null}
    </span>
  );
}

export function MapPlanView({ plan, box }: { plan: MapPlanInput; box: string }) {
  // 前に出した案の古い箱（裏方の4つ）は、まとめた「ダンの本体」に付ける
  const changes = useMemo(() => (plan.changes || []).map((c) => (c?.node && NODE_ALIAS[c.node] ? { ...c, node: NODE_ALIAS[c.node] } : c)), [plan.changes]);
  const [layout, setLayout] = useState<Record<string, Box>>({});
  useEffect(() => { let live = true; void boardLayout().then((l) => { if (live) setLayout(l); }); return () => { live = false; }; }, []);
  const marks = useMemo(() => {
    const m = new Map<string, number[]>();
    changes.forEach((c, i) => { if (c?.node && BY_ID.has(c.node)) m.set(c.node, [...(m.get(c.node) || []), i + 1]); });
    return m;
  }, [changes]);
  const key = changes.map((c) => `${c?.node}:${c?.title}:${c?.prompt || ''}`).join('|');
  useEffect(() => {
    if (!key) return;
    announcePlan(changes.flatMap((c, i) => (c?.node ? [{
      node: c.node, n: i + 1, title: c.title || '', now: c.now || undefined, after: c.after || undefined,
      effect: c.effect || undefined, prompt: c.prompt || undefined, quote: c.quote || undefined, rewrite: c.rewrite || undefined,
    }] : [])));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return (
    <div className={`${box} flex flex-col gap-2`} data-shape="MapPlan">
      {plan.title ? <div className="text-[15px] font-bold leading-snug">{plan.title}</div> : null}
      <BoxStrip marks={marks} layout={layout} onPick={focusMapBox} />
      <ol className="m-0 flex list-none flex-col gap-2 p-0">
        {changes.map((c, i) => {
          const n = c?.node ? BY_ID.get(c.node) : undefined;
          return (
            <li key={i}>
              <button type="button" onClick={() => c?.node && focusMapBox(c.node, i + 1)} data-map-plan-change={c?.node}
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
                  {c?.quote || c?.rewrite ? <TextChange quote={c.quote} rewrite={c.rewrite} /> : null}
                  {c?.effect ? <span className="text-[13px] font-semibold text-violet-500">→ {c.effect}</span> : null}
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
