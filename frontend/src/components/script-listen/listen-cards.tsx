'use client';

// 台本を聞く画面のコメントと提案の札（2026-11-19）。コメントは Google ドキュメントのコメントそのもの
// （app/services/script_listen.py の comments）。ここで書くと、ドキュメントで書いた時と同じくダンが返事と直しをする。
import { useState } from 'react';
import { Check, Loader2, MessageSquare, RotateCcw, X } from 'lucide-react';

import type { Seg, Suggestion, Thread } from '@/lib/script-listen-api';
import { cn } from '@/lib/utils';

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

function ReplyBox({ onSend, placeholder, autoFocus }: { onSend: (text: string) => Promise<void>; placeholder: string; autoFocus?: boolean }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try { await onSend(text.trim()); setText(''); } finally { setBusy(false); }
  };
  return (
    <div className="mt-2">
      <textarea
        autoFocus={autoFocus}
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
      <div className="space-y-2">
        {thread.messages.map(m => (
          <div key={m.id}>
            <div className="flex items-baseline gap-1.5 text-[11px] text-stone-500">
              <span className={cn('font-semibold', m.who === 'dan' ? 'text-amber-800' : 'text-stone-700')}>{WHO[m.who] || m.name || '他の人'}</span>
              <span>{when(m.at)}</span>
            </div>
            {m.action
              ? <div className="text-[12px] text-stone-500">{m.action === 'resolve' ? '解決にしました' : '開き直しました'}</div>
              : <div className="whitespace-pre-wrap break-words leading-relaxed text-stone-800">{(m.text || '').replace(/^ダン[：:]\s*/, '')}</div>}
          </div>
        ))}
      </div>
      {thread.working && thread.working !== 'needs_room' && (
        <div className="mt-2 flex items-center gap-1.5 text-[12px] text-amber-800"><Loader2 className="h-3.5 w-3.5 animate-spin" />ダンが対応しています</div>
      )}
      {thread.working === 'needs_room' && (
        <div className="mt-2 text-[12px] text-amber-800">ダンが、どの部屋の台本かを聞いています。返事に部屋の名前を書いてください。</div>
      )}
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

export function SuggestionCard({
  s, active, onFocus, onDecide,
}: { s: Suggestion; active?: boolean; onFocus?: () => void; onDecide: (accept: boolean) => Promise<void> }) {
  const [busy, setBusy] = useState<'' | 'yes' | 'no'>('');
  const go = async (accept: boolean) => {
    setBusy(accept ? 'yes' : 'no');
    try { await onDecide(accept); } finally { setBusy(''); }
  };
  const kind = s.ins && s.del ? '置き換え' : s.ins ? '足す' : '消す';
  return (
    <div
      onClick={onFocus}
      className={cn('rounded-lg border bg-white p-2.5 text-[13px] shadow-sm', active ? 'border-emerald-400 shadow-md' : 'border-stone-200')}
    >
      <div className="mb-1 text-[11px] font-semibold text-emerald-800">提案（{kind}）</div>
      {s.del && <div className="line-clamp-3 text-red-700/80 line-through decoration-red-500">{s.del.trim()}</div>}
      {s.ins && <div className="mt-0.5 line-clamp-4 text-emerald-800">{s.ins.trim()}</div>}
      <div className="mt-2 flex justify-end gap-1.5" onClick={e => e.stopPropagation()}>
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
