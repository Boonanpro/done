'use client';

// 台本を聞く画面で、ダンが今どこを直していて何をしているかを見せる部品（2026-11-20 本人「動画制作エディターみたいに
// ダンがどこを編集してるか可視化」「ダンが対応していますだけじゃなくてプロセスモニター。同時に出るのは1つずつ、
// クリックしたら他も見れる。このチャットと同じ感じ」）。作業の記録は app/services/script_listen.py の activity。
// 本人の画面は動かさない（勝手にスクロールしない・本文の中身を変えない）。印は本文の外か data-dan の印だけ。
import { createContext, useContext, useMemo, useState } from 'react';
import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, CircleAlert, Loader2, Wrench } from 'lucide-react';

import type { DanJob, Thread, WorkEvent } from '@/lib/script-listen-api';
import { cn } from '@/lib/utils';

export const LIVE = new Set<DanJob['status']>(['pending', 'running', 'needs_room']);
export const isLive = (j: DanJob) => LIVE.has(j.status);

const plain = (s: string) => s.replace(/\*\*/g, '').replace(/^#+\s*/gm, '').trim();

/** The one line the chat would show now: the newest work line (its first sentence's line), or how it ended. */
export function latestLine(j: DanJob): string {
  if (j.status === 'pending') return '取りかかる順番を待っています';
  if (j.status === 'needs_room') return 'どの部屋の台本かを聞いています';
  const last = [...j.events].reverse().find(e => e.kind === 'progress' || e.kind === 'result' || e.kind === 'error');
  if (!isLive(j)) {
    if (j.status === 'failed') return '途中で止まりました';
    if (j.status === 'attention') return '終わりましたが、返事がドキュメントに入ったか確かめられていません';
    const r = [...j.events].reverse().find(e => e.kind === 'result');
    return r ? `終わりました：${firstLine(r.text)}` : '終わりました';
  }
  return last ? firstLine(last.text) : '作業を始めています';
}

function firstLine(text: string) {
  const t = plain(text).split('\n').map(s => s.trim()).find(Boolean) || '';
  return t.length > 140 ? t.slice(0, 139) + '…' : t;
}

function hm(at?: string | null) {
  if (!at) return '';
  const d = new Date(at);
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** What the comment cards read: the line of the job on a thread, and a way to open that job in the monitor. */
export const DanLiveContext = createContext<{ lineFor: (threadId: string) => string | null; open: (threadId: string) => void }>({
  lineFor: () => null, open: () => {},
});
export const useDanLive = () => useContext(DanLiveContext);

/** The status mark of a job: spinning while it works, a check when it ended well. */
function Mark({ j, className }: { j: DanJob; className?: string }) {
  if (isLive(j)) return <Loader2 className={cn('h-3.5 w-3.5 shrink-0 animate-spin text-sky-600', className)} />;
  if (j.status === 'completed') return <Check className={cn('h-3.5 w-3.5 shrink-0 text-emerald-600', className)} />;
  return <CircleAlert className={cn('h-3.5 w-3.5 shrink-0 text-amber-600', className)} />;
}

type Row = { kind: 'line'; e: WorkEvent } | { kind: 'tools'; list: WorkEvent[]; key: string };

/** The log as the chat shows it: the work lines, with the tool steps between two lines folded into one row. */
function rows(events: WorkEvent[]): Row[] {
  const out: Row[] = [];
  for (const e of events) {
    if (e.kind === 'tool') {
      const last = out[out.length - 1];
      if (last?.kind === 'tools') last.list.push(e);
      else out.push({ kind: 'tools', list: [e], key: `t${e.seq}` });
    } else if (e.kind !== 'input') out.push({ kind: 'line', e });
  }
  return out;
}

function ToolRow({ list }: { list: WorkEvent[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="pl-5">
      <button type="button" onClick={() => setOpen(v => !v)} className="flex items-center gap-1 text-[11px] text-stone-400 hover:text-stone-600">
        <Wrench className="h-3 w-3" />道具を{list.length}回使いました{open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {open && (
        <div className="mt-1 space-y-0.5 border-l border-stone-200 pl-2">
          {list.map(e => <div key={e.seq} className="truncate font-mono text-[10.5px] text-stone-400" title={e.text}>{hm(e.at)} {e.text}</div>)}
        </div>
      )}
    </div>
  );
}

/**
 * The work monitor above the player: one job's newest line; press it to see its whole log and the other jobs.
 */
export function DanMonitor({
  jobs, threads, selected, onSelect, open, onOpen, onGoText,
}: {
  jobs: DanJob[]; threads: Thread[]; selected: string | null; onSelect: (id: string) => void;
  open: boolean; onOpen: (open: boolean) => void; onGoText: (job: DanJob) => void;
}) {
  const at = Math.max(0, jobs.findIndex(j => j.id === selected));
  const j = jobs[at];
  const quoteOf = useMemo(() => new Map(threads.map(t => [t.id, t.quote || (t.messages[0]?.text || '')])), [threads]);
  if (!j) return null;
  const about = (job: DanJob) => {
    const q = job.comment_ids.map(id => quoteOf.get(id)).find(Boolean) || '';
    return q.length > 24 ? q.slice(0, 23) + '…' : q;
  };
  const step = (d: number) => onSelect(jobs[(at + d + jobs.length) % jobs.length].id);
  return (
    <div data-testid="dan-monitor" className="mb-1.5 overflow-hidden rounded-lg border border-sky-200 bg-sky-50/80 text-[12.5px]">
      <div className="flex items-center gap-1">
        <button
          type="button"
          data-testid="dan-monitor-line"
          onClick={() => onOpen(!open)}
          className="flex min-w-0 flex-1 items-center gap-1.5 px-2.5 py-1.5 text-left"
        >
          <Mark j={j} />
          <span className="shrink-0 font-semibold text-sky-800">ダン</span>
          <span className="min-w-0 flex-1 truncate text-stone-700">{latestLine(j)}</span>
          {open ? <ChevronDown className="h-4 w-4 shrink-0 text-stone-500" /> : <ChevronUp className="h-4 w-4 shrink-0 text-stone-500" />}
        </button>
        {jobs.length > 1 && (
          <div className="flex shrink-0 items-center pr-1 text-[11px] tabular-nums text-stone-500">
            <button type="button" aria-label="前の作業" onClick={() => step(-1)} className="rounded p-1 hover:bg-sky-100"><ChevronLeft className="h-3.5 w-3.5" /></button>
            {at + 1}/{jobs.length}
            <button type="button" aria-label="次の作業" onClick={() => step(1)} className="rounded p-1 hover:bg-sky-100"><ChevronRight className="h-3.5 w-3.5" /></button>
          </div>
        )}
      </div>
      {open && (
        <div className="border-t border-sky-200 bg-white/70">
          {jobs.length > 1 && (
            <div className="flex gap-1 overflow-x-auto px-2 pt-2">
              {jobs.map(x => (
                <button
                  key={x.id}
                  type="button"
                  onClick={() => onSelect(x.id)}
                  className={cn('flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11.5px]', x.id === j.id
                    ? 'border-sky-600 bg-sky-600 text-white' : 'border-stone-300 bg-white text-stone-700')}
                >
                  <Mark j={x} className={x.id === j.id ? 'text-white' : undefined} />{about(x) || 'コメント'}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between gap-2 px-2.5 pt-2 text-[11.5px] text-stone-500">
            <span className="truncate">「{about(j) || 'コメント'}」への対応 {hm(j.started)}〜</span>
            <button type="button" onClick={() => onGoText(j)} className="shrink-0 rounded-md border border-stone-300 bg-white px-2 py-0.5 text-[11.5px] text-stone-700 hover:bg-stone-50">文へ</button>
          </div>
          <div data-testid="dan-monitor-log" className="max-h-[38dvh] space-y-1.5 overflow-y-auto px-2.5 py-2">
            {rows(j.events).map(r => r.kind === 'tools'
              ? <ToolRow key={r.key} list={r.list} />
              : (
                <div key={r.e.seq} className="flex gap-1.5">
                  <span className="mt-[3px] shrink-0">
                    {r.e.kind === 'result' ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : r.e.kind === 'error'
                      ? <CircleAlert className="h-3.5 w-3.5 text-amber-600" /> : <span className="block h-1.5 w-1.5 translate-x-1 translate-y-1 rounded-full bg-sky-500" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className={cn('whitespace-pre-wrap break-words leading-relaxed text-stone-800', r.e.kind === 'result' && 'text-[12px]')}>{plain(r.e.text)}</div>
                    <div className="text-[10.5px] text-stone-400">{hm(r.e.at)}</div>
                  </div>
                </div>
              ))}
            {isLive(j) && (
              <div className="flex items-center gap-1.5 pl-0.5 text-[11.5px] text-sky-700"><Loader2 className="h-3 w-3 animate-spin" />作業中</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
