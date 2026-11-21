'use client';

// 台本を聞く画面のコメントと提案の札（2026-11-19）。コメントは Google ドキュメントのコメントそのもの
// （app/services/script_listen.py の comments）。ここで書くと、ドキュメントで書いた時と同じくダンが返事と直しをする。
import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronUp, Loader2, MessageSquare, RotateCcw, X } from 'lucide-react';

import type { Seg, Suggestion, Thread } from '@/lib/script-listen-api';
import { cn } from '@/lib/utils';

import { JobLog, Mark, latestLine, useDanLive } from './listen-dan';

export function SegText({ segs, onSuggestion }: { segs: Seg[]; onSuggestion?: (id: string) => void }) {
  return (
    <>
      {segs.map((s, k) => {
        const sid = s.ins || s.del;
        return (
          <span
            key={k}
            onClick={sid && onSuggestion ? e => { e.stopPropagation(); onSuggestion(sid); } : undefined}
            className={cn(
              s.b && 'font-bold',
              s.blue && 'text-sky-700/80',
              s.ins && 'cursor-pointer bg-emerald-50 text-emerald-800 underline decoration-emerald-500 decoration-2 underline-offset-2',
              s.del && 'cursor-pointer text-red-700/70 line-through decoration-red-500',
            )}
          >
            {s.t}
          </span>
        );
      })}
    </>
  );
}

function when(at?: string) {
  if (!at) return '';
  const d = new Date(at);
  const now = new Date();
  const hm = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
  return d.toDateString() === now.toDateString() ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}

const WHO: Record<string, string> = { owner: 'みきさん', dan: 'ダン' };
const WHO_LOOK: Record<string, { dot: string; bubble: string; name: string; initial?: string }> = {
  owner: { dot: 'bg-violet-600', bubble: 'border-violet-500 bg-violet-50', name: 'text-violet-800', initial: 'み' },
  dan: { dot: 'bg-sky-600', bubble: 'border-sky-500 bg-sky-50', name: 'text-sky-800', initial: 'ダ' },
  other: { dot: 'bg-stone-500', bubble: 'border-stone-400 bg-stone-50', name: 'text-stone-700' },
};

function ReplyBox({ onSend, placeholder, autoFocus }: { onSend: (text: string) => Promise<void>; placeholder: string; autoFocus?: boolean }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLTextAreaElement | null>(null);
  // Focus after the card has been moved beside its words; a plain autoFocus scrolled the page to the top (11/19).
  useEffect(() => {
    if (!autoFocus) return;
    const t = window.setTimeout(() => box.current?.focus({ preventScroll: true }), 60);
    return () => window.clearTimeout(t);
  }, [autoFocus]);
  const send = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try { await onSend(text.trim()); setText(''); } finally { setBusy(false); }
  };
  return (
    <div className="mt-2">
      <textarea
        ref={box}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); }
        }}
        rows={Math.min(6, Math.max(2, Math.ceil(text.length / 22)))}
        placeholder={placeholder}
        className="w-full resize-none rounded-md border border-stone-300 bg-white px-2 py-1.5 text-[14px] leading-relaxed outline-none focus:border-amber-500"
      />
      <div className="mt-1 flex justify-end">
        <button
          type="button"
          disabled={!text.trim() || busy}
          onClick={() => void send()}
          className="flex items-center gap-1 rounded-md bg-amber-600 px-3 py-1.5 text-[13px] font-semibold text-white disabled:opacity-40"
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}送る
        </button>
      </div>
    </div>
  );
}

export function ThreadCard({
  thread, active, onFocus, onReply, onSettle, canWrite,
}: {
  thread: Thread;
  active?: boolean;
  onFocus?: () => void;
  onReply: (text: string) => Promise<void>;
  onSettle: (reopen: boolean) => Promise<void>;
  canWrite: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const settle = async (reopen: boolean) => {
    setBusy(true);
    try { await onSettle(reopen); } finally { setBusy(false); }
  };
  return (
    <div
      onClick={onFocus}
      className={cn(
        'rounded-lg border bg-white p-2.5 text-[13px] shadow-sm transition-shadow',
        active ? 'border-amber-400 shadow-md' : 'border-stone-200',
        thread.resolved && 'opacity-70',
      )}
    >
      {thread.quote && (
        <div className="mb-1.5 line-clamp-2 border-l-2 border-yellow-400 pl-2 text-[12px] text-stone-500">{thread.quote}</div>
      )}
      <Messages thread={thread} />
      {canWrite && active && !thread.resolved && (
        <div onClick={e => e.stopPropagation()}>
          <ReplyBox placeholder="返事を書く" onSend={onReply} />
        </div>
      )}
      <div className="mt-1.5 flex justify-end gap-1" onClick={e => e.stopPropagation()}>
        <button
          type="button"
          disabled={busy}
          onClick={() => void settle(thread.resolved)}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-stone-600 hover:bg-stone-100 disabled:opacity-40"
        >
          {thread.resolved ? <><RotateCcw className="h-3.5 w-3.5" />開き直す</> : <><Check className="h-3.5 w-3.5" />解決</>}
        </button>
      </div>
    </div>
  );
}

/** The messages of one thread and whether Dan is on it (a comment card, or a suggestion's card). */
function Messages({ thread }: { thread: Thread }) {
  const live = useDanLive();
  const job = thread.working === 'needs_room' ? null : live.jobFor(thread.id);
  const open = !!job && live.expanded === job.id;
  return (
    <>
      <div className="space-y-2">
        {thread.messages.map(m => {
          // Who wrote it must be clear at a glance (11/21 本人): a coloured initial and a tinted bubble per writer —
          // みきさん violet (their suggestions are violet), ダン sky (Dan's work line is sky), anyone else grey.
          const look = WHO_LOOK[m.who] || WHO_LOOK.other;
          const name = WHO[m.who] || m.name || '他の人';
          return (
            <div key={m.id} data-who={m.who} className="flex items-start gap-1.5">
              <span className={cn('mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white', look.dot)}>
                {look.initial || name.slice(0, 1)}
              </span>
              <div className={cn('min-w-0 flex-1 rounded-md border-l-[3px] px-2 py-1', look.bubble)}>
                <div className="flex items-baseline gap-1.5 text-[11px]">
                  <span className={cn('font-bold', look.name)}>{name}</span>
                  <span className="text-stone-500">{when(m.at)}</span>
                </div>
                {m.action
                  ? <div className="text-[12px] text-stone-500">{m.action === 'resolve' ? '解決にしました' : '開き直しました'}</div>
                  : <div className="whitespace-pre-wrap break-words leading-relaxed text-stone-800">{(m.text || '').replace(/^ダン[：:]\s*/, '')}</div>}
              </div>
            </div>
          );
        })}
      </div>
      {job && (
        // The newest line of Dan's work on it; pressing it opens the whole log here in the card (11/20).
        <div onClick={e => e.stopPropagation()}>
          <button
            type="button"
            data-testid="card-dan-line"
            onClick={() => live.toggle(job.id)}
            className="mt-2 flex w-full items-start gap-1.5 rounded-md bg-sky-50 px-1.5 py-1 text-left text-[12px] text-sky-900 hover:bg-sky-100"
          >
            <Mark j={job} className="mt-[1px]" />
            <span className="min-w-0 flex-1 break-words"><b className="mr-1 font-semibold">ダン</b>{latestLine(job)}</span>
            {open ? <ChevronUp className="mt-[1px] h-3.5 w-3.5 shrink-0 text-sky-700" /> : <ChevronDown className="mt-[1px] h-3.5 w-3.5 shrink-0 text-sky-700" />}
          </button>
          {open && <JobLog j={job} />}
        </div>
      )}
      {!job && thread.working && thread.working !== 'needs_room' && (
        <div className="mt-2 flex items-start gap-1.5 rounded-md bg-sky-50 px-1.5 py-1 text-[12px] text-sky-900">
          <Loader2 className="mt-[1px] h-3.5 w-3.5 shrink-0 animate-spin text-sky-600" />
          <span className="min-w-0 flex-1 break-words"><b className="mr-1 font-semibold">ダン</b>対応しています</span>
        </div>
      )}
      {thread.working === 'needs_room' && (
        <div className="mt-2 text-[12px] text-amber-800">ダンが、どの部屋の台本かを聞いています。返事に部屋の名前を書いてください。</div>
      )}
    </>
  );
}

/** A suggestion (Dan's or someone's change in suggestion mode) with 承認 / 却下, and the owner's talk about it: what is
 * written here goes to Dan as a comment on that suggestion, in one thread that keeps going when Dan puts in a new
 * suggestion for it (11/20 本人「提案に対して『それおかしいから、もう少しこういう風に直して』と言いたい」). */
export function SuggestionCard({
  s, active, onFocus, onDecide, threads = [], canComment = false, onComment, earlier = false,
}: {
  s: Suggestion; active?: boolean; onFocus?: () => void; onDecide: (accept: boolean) => Promise<void>;
  threads?: Thread[]; canComment?: boolean; onComment?: (text: string) => Promise<void>;
  /** The talk began on an earlier suggestion at this place (Dan replaced it with this one). */
  earlier?: boolean;
}) {
  const [busy, setBusy] = useState<'' | 'yes' | 'no'>('');
  const [writing, setWriting] = useState(false);
  const go = async (accept: boolean) => {
    setBusy(accept ? 'yes' : 'no');
    try { await onDecide(accept); } finally { setBusy(''); }
  };
  const kind = s.ins && s.del ? '置き換え' : s.ins ? '足す' : '消す';
  // Dan's suggestion the owner wrote over: his colour, with the owner's letters in theirs (11/21 本人「全部が紫になる…おかしい」).
  const fromDan = !!s.from_dan;
  const own = !fromDan && (s.by === 'owner' || s.by === 'client');   // kept by the screen (the owner's, or the other side's from their copy)
  const touched = fromDan && /o/.test((s.ins_who || '') + (s.del_who || ''));
  const byWho = (text: string, who: string | undefined, dan: string, mine: string) => {
    if (!fromDan || !who) return text;
    const parts: { t: string; o: boolean }[] = [];
    for (let k = 0; k < text.length; k++) {
      const o = who[k] === 'o';
      if (parts.length && parts[parts.length - 1].o === o) parts[parts.length - 1].t += text[k];
      else parts.push({ t: text[k], o });
    }
    return parts.map((p, k) => <span key={k} className={p.o ? mine : dan}>{p.t}</span>);
  };
  const talking = threads.length > 0;
  const showBox = canComment && !!onComment && (writing || (active && talking));
  return (
    <div
      onClick={onFocus}
      className={cn('rounded-lg border bg-white p-2.5 text-[13px] shadow-sm',
        active ? (own ? 'border-violet-400 shadow-md' : 'border-emerald-400 shadow-md') : 'border-stone-200')}
    >
      <div className={cn('mb-1 text-[11px] font-semibold', own ? 'text-violet-800' : 'text-emerald-800')}>{s.by === 'client' ? '相手の直し' : own ? 'みきさんの提案' : touched ? 'ダンの提案・みきさんが直した' : '提案'}（{kind}）</div>
      {s.del && <div className={cn('line-clamp-3 line-through', own ? 'text-violet-700/80 decoration-violet-500' : 'text-red-700/80 decoration-red-500')}>{fromDan ? byWho(s.del, s.del_who, '', 'text-violet-700/80 decoration-violet-500') : s.del.trim()}</div>}
      {s.ins && <div className={cn('mt-0.5 line-clamp-4', own ? 'text-violet-800' : 'text-emerald-800')}>{fromDan ? byWho(s.ins, s.ins_who, '', 'text-violet-800') : s.ins.trim()}</div>}
      {talking && (
        <div className="mt-2 space-y-2 border-t border-stone-100 pt-2">
          {earlier && <div className="text-[11px] text-stone-400">前の提案からの続き</div>}
          {threads.map(t => <Messages key={t.id} thread={t} />)}
        </div>
      )}
      {showBox && (
        <div onClick={e => e.stopPropagation()}>
          <ReplyBox autoFocus={writing} placeholder="この提案へのコメント（例：ここは言い切らずに、もう少し柔らかく）"
            onSend={async text => { await onComment!(text); setWriting(false); }} />
        </div>
      )}
      <div className="mt-2 flex items-center justify-end gap-1.5" onClick={e => e.stopPropagation()}>
        {canComment && onComment && !showBox && (
          <button
            type="button"
            onClick={() => { setWriting(true); onFocus?.(); }}
            className="mr-auto flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-stone-600 hover:bg-stone-100"
          >
            <MessageSquare className="h-3.5 w-3.5" />{talking ? '返事を書く' : 'コメント'}
          </button>
        )}
        <button
          type="button"
          disabled={!!busy}
          onClick={() => void go(false)}
          className="flex items-center gap-1 rounded-md border border-stone-300 px-2.5 py-1 text-[12px] text-stone-700 disabled:opacity-40"
        >
          {busy === 'no' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}却下
        </button>
        <button
          type="button"
          disabled={!!busy}
          onClick={() => void go(true)}
          className="flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-[12px] font-semibold text-white disabled:opacity-40"
        >
          {busy === 'yes' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}承認
        </button>
      </div>
    </div>
  );
}

export function Composer({ quote, onSend, onCancel }: { quote: string; onSend: (text: string) => Promise<void>; onCancel: () => void }) {
  return (
    <div className="rounded-lg border border-amber-400 bg-white p-2.5 text-[13px] shadow-md">
      <div className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-amber-800"><MessageSquare className="h-3.5 w-3.5" />コメント</div>
      {quote && <div className="line-clamp-2 border-l-2 border-yellow-400 pl-2 text-[12px] text-stone-500">{quote}</div>}
      <ReplyBox autoFocus placeholder="ダンへの質問や直してほしいこと" onSend={onSend} />
      <div className="-mt-7 flex">
        <button type="button" onClick={onCancel} className="rounded-md px-2 py-1 text-[12px] text-stone-500 hover:bg-stone-100">やめる</button>
      </div>
    </div>
  );
}
