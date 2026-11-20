'use client';

// 台本を聞く画面で、ダンが今どこを直していて何をしているかを見せる部品（2026-11-20 本人「動画制作エディターみたいに
// ダンがどこを編集してるか可視化」「ダンが対応していますだけじゃなくてプロセスモニター。同時に出るのは1つずつ、
// クリックしたら他も見れる。このチャットと同じ感じ」）。作業の記録は app/services/script_listen.py の activity。
// 本人の画面は動かさない（勝手にスクロールしない・本文の中身を変えない）。印は本文の外か data-dan の印だけ。
import { createContext, useContext, useState } from 'react';
import { Check, ChevronDown, ChevronUp, CircleAlert, Loader2, Wrench } from 'lucide-react';

import type { DanJob, WorkEvent } from '@/lib/script-listen-api';
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
  // Dan writes a line now and then; between them, the step he is on in plain words.
  const tool = [...j.events].reverse().find(e => e.kind === 'tool');
  const stale = !last || last.text === '作業を始めています'
    || (!!tool && tool.seq > last.seq && Date.parse(tool.at) - Date.parse(last.at) > 25000);
  if (tool?.say && stale) return tool.say;
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

/** What the comment cards read: the job on a thread (working, or ended a little while ago), and whether its log is open. */
export const DanLiveContext = createContext<{
  jobFor: (threadId: string) => DanJob | null; expanded: string | null; toggle: (jobId: string) => void;
}>({ jobFor: () => null, expanded: null, toggle: () => {} });
export const useDanLive = () => useContext(DanLiveContext);

/** The status mark of a job: spinning while it works, a check when it ended well. */
export function Mark({ j, className }: { j: DanJob; className?: string }) {
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

/** Tool steps in plain words, the same words in a row folded into one (the commands themselves on hover). */
function steps(list: WorkEvent[]) {
  const out: { first: WorkEvent; labels: string[] }[] = [];
  for (const e of list) {
    const last = out[out.length - 1];
    if (last && (last.first.say || last.first.text) === (e.say || e.text)) last.labels.push(e.text);
    else out.push({ first: e, labels: [e.text] });
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
          {steps(list).map(g => (
            <div key={g.first.seq} className="truncate text-[11px] text-stone-500" title={g.labels.join('\n')}>
              {hm(g.first.at)} {g.first.say || g.first.text}{g.labels.length > 1 && <span className="text-stone-400"> ×{g.labels.length}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * One job's whole log, inside the comment card it is about (11/20 本人「プロセスモニターは画面下の固定部分には出す必要
 * 無い。あくまでそのコメントのところだけに出して」). The card's line opens and closes it.
 */
export function JobLog({ j }: { j: DanJob }) {
  return (
    <div data-testid="dan-job-log" className="mt-1 max-h-[38dvh] space-y-1.5 overflow-y-auto rounded-md border border-sky-100 bg-white px-2 py-1.5 text-[12px]">
      <div className="text-[11px] text-stone-400">{hm(j.started)}〜</div>
      {rows(j.events).map(r => r.kind === 'tools'
        ? <ToolRow key={r.key} list={r.list} />
        : (
          <div key={r.e.seq} className="flex gap-1.5">
            <span className="mt-[3px] shrink-0">
              {r.e.kind === 'result' ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : r.e.kind === 'error'
                ? <CircleAlert className="h-3.5 w-3.5 text-amber-600" /> : <span className="block h-1.5 w-1.5 translate-x-1 translate-y-1 rounded-full bg-sky-500" />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="whitespace-pre-wrap break-words leading-relaxed text-stone-800">{plain(r.e.text)}</div>
              <div className="text-[10.5px] text-stone-400">{hm(r.e.at)}</div>
            </div>
          </div>
        ))}
      {isLive(j) && (
        <div className="flex items-center gap-1.5 pl-0.5 text-[11.5px] text-sky-700"><Loader2 className="h-3 w-3 animate-spin" />作業中</div>
      )}
    </div>
  );
}
