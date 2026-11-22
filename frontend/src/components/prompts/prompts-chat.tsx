'use client';

// 指示文の画面で、ダンと話しながら一緒に指示文を見直す会話（2026-11-21 本人「指示文の見直しはお前が単体でやるより俺と一緒に
// やった方が良い気がするけど、指示文を見直すページにチャットが無いからやりにくい」）。
// - 部屋は1つ（「ダン開発室: 指示文の見直し」。一覧に出さない。app/api/prompts_screen.py の /prompts/chat）。/prompts と
//   開発室の「指示文」が同じ部屋で話す。
// - 発言ごとに、今開いている指示文と選んでいる行・文、保存していない書きかけを <dan-context> で添える（画面には出さない。
//   本人の吹き出しには「どの文の何行目について」だけを小さく出す）。「ここ」「この行」で通じるように。
// - ダンが文を保存したら、全文の欄が新しい版になり、変わった所と「元に戻す」が出る（prompts-screen.tsx の Editor）。
//   ここからは、ダンが動いている間とダンの返事が来た時に onPulse で知らせるだけ。
// - 新着は、ダン本体の画面と同じ新着の線（/chat/feed）で受ける。作業中の1行は lib/chat-shapes/live-line.ts と同じ決まり。
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowUp, Loader2, MessageCircle, Square, X } from 'lucide-react';

import { ShapeBlock } from '@/components/chat/chat-shapes';
import { parseMediaContent } from '@/lib/chat-media';
import { splitShapeSegments } from '@/lib/chat-shapes/split';
import { partKeys } from '@/lib/chat-shapes/answers';
import { elapsedText, liveLineText, liveStartedAt, liveStepsFromEvents, sentSinceReply } from '@/lib/chat-shapes/live-line';
import { oneLine } from '@/lib/one-line';
import { promptsChat, type ChatMessage, type ChatStep } from '@/lib/prompts-api';
import { cn } from '@/lib/utils';

/** 会話に添える「今見ている所」。画面（prompts-screen.tsx）が作る */
export type PromptChatContext = {
  place?: { id: string; name: string } | null;
  prompt?: { id: string; title: string; reader?: string; when?: string; readonly?: boolean; source?: string; chars?: number } | null;
  /** 選んでいる所（行は1から）。選んでいなければ無し */
  selection?: { from: number; to: number; text: string } | null;
  /** カーソルのある行（選んでいない時の手がかり） */
  cursor?: number | null;
  /** 保存していない書きかけの違い（- 消した行 / + 足した行） */
  draftDiff?: string | null;
};

const SNIP = 1200;
const clip = (s: string, n = SNIP) => (s.length > n ? `${s.slice(0, n)}…（以下${s.length - n}字略）` : s);
const indent = (s: string) => s.split('\n').map(l => `  ${l}`).join('\n');
const linesText = (sel: { from: number; to: number }) => (sel.from === sel.to ? `${sel.from}行目` : `${sel.from}〜${sel.to}行目`);

/** ダンへ渡す前置き。本人には見えない（chat-media.ts・chat_service.py が外す） */
export function contextBlock(ctx: PromptChatContext): string {
  const out = ['<dan-context>', 'kind: prompts-screen', 'note: みきさんは指示文の画面を見ながら話している。「ここ」「この行」「これ」は下の選んでいる所（無ければ開いている文）を指す。'];
  if (ctx.place) out.push(`place: ${ctx.place.name}（図の箱 ${ctx.place.id}）`);
  if (ctx.prompt) {
    const p = ctx.prompt;
    out.push(`prompt-id: ${p.id}`, `prompt-title: ${p.title}`);
    if (p.reader) out.push(`reader: ${p.reader}`);
    if (p.when) out.push(`when: ${p.when}`);
    if (p.source) out.push(`source: ${p.source}`);
    out.push(`readonly: ${p.readonly ? 'true（プログラムの中の文。この部屋では書き換えない）' : 'false'}`);
    if (!p.readonly && !p.id.startsWith('skill/')) out.push(`read: python /Users/mikihonda/done/scripts/prompts.py show ${p.id}`, `save: python /Users/mikihonda/done/scripts/prompts.py save ${p.id} --note "<なぜ>" < 新しい全文`);
  } else {
    out.push('prompt: （文はまだ開いていない。図か一覧を見ている）');
  }
  if (ctx.selection?.text.trim()) out.push(`selected-lines: ${linesText(ctx.selection)}`, 'selected-text: |', indent(clip(ctx.selection.text)));
  else if (ctx.cursor) out.push(`cursor-line: ${ctx.cursor}（参考。選んではいない）`);
  if (ctx.draftDiff) out.push('unsaved-draft: |（みきさんが書きかけで、まだ保存していない違い。直す時は消さない）', indent(clip(ctx.draftDiff, 3000)));
  out.push('</dan-context>');
  return out.join('\n');
}

/** 本人の吹き出しの上に出す「どの文の何行目について」（送った時の前置きから読む） */
function aboutOf(content: string): { title?: string; lines?: string; text?: string } | null {
  const m = content.match(/<dan-context>([\s\S]*?)<\/dan-context>/);
  if (!m) return null;
  const body = m[1];
  const title = body.match(/^prompt-title: (.+)$/m)?.[1];
  const lines = body.match(/^selected-lines: (.+)$/m)?.[1];
  const text = body.match(/^selected-text: \|\n((?: {2}.*\n?)+)/m)?.[1]?.split('\n').map(l => l.replace(/^ {2}/, '')).join(' ').trim();
  if (!title && !lines) return null;
  return { title, lines, text };
}

const MD_PLUGINS = [remarkGfm];
const MD = 'text-[14px] leading-relaxed text-stone-900 [&_a]:text-amber-800 [&_a]:underline [&_code]:rounded [&_code]:bg-stone-100 [&_code]:px-1 [&_code]:text-[12.5px] [&_h1]:mt-2 [&_h1]:text-base [&_h1]:font-bold [&_h2]:mt-2 [&_h2]:font-bold [&_h3]:mt-2 [&_h3]:font-semibold [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1.5 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-stone-100 [&_pre]:p-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:my-2 [&_table]:block [&_table]:overflow-x-auto [&_td]:border [&_td]:border-stone-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-stone-200 [&_th]:bg-stone-50 [&_th]:px-2 [&_th]:py-1 [&_ul]:list-disc [&_ul]:pl-5';
const LINKS: Components = { a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a> };

const DanBody = memo(function DanBody({ body, messageId }: { body: string; messageId: string }) {
  const media = useMemo(() => parseMediaContent(body), [body]);
  const segments = useMemo(() => splitShapeSegments(media.text), [media.text]);
  const keys = useMemo(() => partKeys(segments.flatMap(x => (x.kind === 'shape' ? [x.code] : []))), [segments]);
  const md = (text: string, key: string) => <div key={key} className={MD}><ReactMarkdown remarkPlugins={MD_PLUGINS} components={LINKS}>{text}</ReactMarkdown></div>;
  return (
    <>
      {media.text && segments.map((x, i) => (x.kind === 'markdown'
        ? md(x.text, `m${i}`)
        : <div key={`s${x.index}`}><ShapeBlock code={x.code} complete={x.complete} messageId={messageId} part={keys[x.index] || `i${x.index}`} renderFallback={code => md('```\n' + code + '\n```', `f${i}`)} /></div>))}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {media.images.map(url => <img key={url} src={url} alt="" className="mt-2 max-h-72 rounded-lg border" />)}
      {media.videos.map(url => <video key={url} src={url} controls playsInline preload="metadata" className="mt-2 max-h-72 rounded-lg border" />)}
    </>
  );
});

type Shown = ChatMessage & { pending?: boolean; failed?: string };
const byTime = (a: ChatMessage, b: ChatMessage) => a.created_at.localeCompare(b.created_at);
/** 送ったばかりの発言（pending）が、保存された発言として届いたか */
const sameSend = (local: Shown, saved: ChatMessage) =>
  saved.id === local.id || saved.client_message_id === local.id || (saved.sender_type !== 'ai' && saved.content === local.content);
const isDan = (m: ChatMessage) => m.sender_type === 'ai';
const clock = (at: string) => new Date(at).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const touchOnly = () => typeof window !== 'undefined' && window.matchMedia('(hover: none) and (pointer: coarse)').matches;

function ContextChip({ ctx, onClear, onClearPick }: { ctx: PromptChatContext; onClear?: () => void; onClearPick?: () => void }) {
  const sel = ctx.selection?.text.trim() ? ctx.selection : null;
  // 何も選んでいない時は札を出さない（2026-11-22 本人「×を押したら選択解除」＝外したら札も消える）
  if (!sel && !ctx.prompt && !ctx.place) return null;
  // ×は一番細かい物から外す: 全文の中で選んだ行 → 開いている文と図の箱
  const clear = sel ? onClear : onClearPick;
  return (
    <div className="flex min-w-0 items-start gap-1.5 rounded-lg bg-amber-50 px-2 py-1.5 text-[12px] leading-snug text-amber-950" data-prompts-chip>
      <span className="min-w-0 flex-1">
        <span className="font-semibold">{ctx.prompt ? `「${ctx.prompt.title}」` : `${ctx.place!.name}の箱`}</span>
        {sel ? <> の{linesText(sel)}：<span className="text-amber-900/80">「{sel.text.trim().replace(/\s+/g, ' ').slice(0, 60)}{sel.text.trim().length > 60 ? '…' : ''}」</span></> : 'について'}
        {ctx.draftDiff ? <span className="ml-1 text-amber-800">（保存していない書きかけも見せます）</span> : null}
      </span>
      {clear ? (
        <button type="button" onClick={clear} aria-label={sel ? '選んだ行を外す' : '選んだ所を外す'} data-prompts-chip-clear
          className="shrink-0 rounded p-0.5 text-amber-800 hover:bg-amber-100"><X className="h-3.5 w-3.5" /></button>
      ) : null}
    </div>
  );
}

/**
 * 会話の中身（発言の一覧・作業中の1行・入力欄）。PC は全文の横の列に、スマホは下から出す欄に入れる。
 * onPulse: ダンが動いている間（数秒ごと）と、ダンの返事が来た時・作業が終わった時に呼ぶ（全文の欄が新しい版を見に行く）。
 */
export function PromptsChat({ ctx, onClearSelection, onClearPick, onPulse, onBusy, header }: {
  ctx: PromptChatContext; onClearSelection: () => void; onClearPick?: () => void; onPulse: () => void; onBusy?: (busy: boolean) => void; header?: ReactNode;
}) {
  const [room, setRoom] = useState('');
  const [error, setError] = useState('');
  const [messages, setMessages] = useState<Shown[]>([]);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [steps, setSteps] = useState<ChatStep[]>([]);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const list = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);   // 一番下を見ている間は、新しい発言で下まで送る
  const pulse = useRef(onPulse);
  pulse.current = onPulse;
  const busyOut = useRef(onBusy);
  busyOut.current = onBusy;
  useEffect(() => { busyOut.current?.(busy); }, [busy]);

  const readAll = useCallback(async (r: string) => {
    const got = await promptsChat.messages(r, 40);
    setMessages(prev => {
      const pending = prev.filter(m => m.pending && !got.some(g => sameSend(m, g)));
      return [...got, ...pending].sort(byTime);
    });
    setMore(got.length >= 40);
  }, []);

  const readBusy = useCallback(async (r: string) => {
    try {
      const a = await promptsChat.active(r);
      setBusy(Boolean(a.active));
      if (a.active) setSteps(await promptsChat.steps(r).catch(() => []));
    } catch { /* 表示だけ */ }
  }, []);

  useEffect(() => {
    let live = true;
    promptsChat.room()
      .then(async got => {
        if (!live) return;
        setRoom(got.room_id);
        await readAll(got.room_id);
        await readBusy(got.room_id);
      })
      .catch(err => { if (live) setError(err instanceof Error ? err.message : '会話を開けませんでした。'); });
    return () => { live = false; };
  }, [readAll, readBusy]);

  // 新着の線。この部屋の発言と、作業の始まり・終わりだけを拾う
  useEffect(() => {
    if (!room) return;
    const line = oneLine(({ up, dropped }) => {
      const es = new EventSource('/api/v1/chat/feed', { withCredentials: true });
      es.addEventListener('hello', () => { up(); void readAll(room); void readBusy(room); });
      es.addEventListener('message', ev => {
        try {
          const data = JSON.parse((ev as MessageEvent).data) as { room_id: string; message: ChatMessage };
          if (data.room_id !== room || !data.message) return;
          const m = data.message;
          setMessages(prev => {
            const rest = prev.filter(x => x.id !== m.id && !(x.pending && sameSend(x, m)));
            return [...rest, m].sort(byTime);
          });
          if (isDan(m)) pulse.current();
        } catch { /* 読めない知らせは捨てる */ }
      });
      es.addEventListener('run', ev => {
        try {
          const data = JSON.parse((ev as MessageEvent).data) as { room_id: string; running?: boolean };
          if (data.room_id !== room) return;
          if (data.running) { setBusy(true); setSteps([]); } else { setBusy(false); setSteps([]); pulse.current(); void readAll(room); }
        } catch { /* 読めない知らせは捨てる */ }
      });
      es.onerror = () => dropped();
      return es;
    });
    const back = () => { if (document.visibilityState === 'visible') line.connectIfClosed(); };
    document.addEventListener('visibilitychange', back);
    line.connect();
    return () => { document.removeEventListener('visibilitychange', back); line.stop(); };
  }, [room, readAll, readBusy]);

  // ダンが動いている間だけ、今の段取りと、全文が変わったかを数秒ごとに見る
  useEffect(() => {
    if (!room || !busy) return;
    const tick = window.setInterval(() => { setNow(Date.now()); }, 1000);
    const look = window.setInterval(() => {
      promptsChat.steps(room).then(setSteps).catch(() => undefined);
      pulse.current();
    }, 3000);
    return () => { window.clearInterval(tick); window.clearInterval(look); };
  }, [room, busy]);

  useLayoutEffect(() => {
    const el = list.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, busy, steps]);

  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = 'auto';
    const want = el.scrollHeight + 2;
    el.style.height = `${Math.min(want, 180)}px`;
    el.style.overflowY = want > 180 ? 'auto' : 'hidden';
  }, [text]);

  async function readOlder() {
    if (!room || !messages.length) return;
    const el = list.current;
    const before = el ? el.scrollHeight - el.scrollTop : 0;
    const older = await promptsChat.messages(room, 40, messages[0].created_at).catch(() => []);
    setMore(older.length >= 40);
    stick.current = false;
    setMessages(prev => [...older.filter(o => !prev.some(p => p.id === o.id)), ...prev].sort(byTime));
    requestAnimationFrame(() => { if (el) el.scrollTop = el.scrollHeight - before; });
  }

  async function send() {
    const said = text.trim();
    if (!said || !room || sending) return;
    const id = crypto.randomUUID();
    const content = `${contextBlock(ctx)}\n${said}`;
    const mine: Shown = { id, sender_type: 'human', content, created_at: new Date().toISOString(), pending: true };
    stick.current = true;
    setMessages(prev => [...prev, mine]);
    setText('');
    setSending(true);
    try {
      await promptsChat.send(content, room, id);
      setBusy(true);
      onClearSelection();
    } catch (err) {
      setMessages(prev => prev.map(m => (m.id === id ? { ...m, failed: err instanceof Error ? err.message : '届きませんでした。' } : m)));
      setText(said);
    } finally {
      setSending(false);
    }
  }

  async function stop() {
    if (!room) return;
    try {
      const out = await promptsChat.stop(room);
      const back = out.withdrawn?.map(w => (w.content || '').replace(/<dan-context>[\s\S]*?<\/dan-context>\n?/g, '')).filter(Boolean).join('\n');
      if (back) setText(t => (t ? `${back}\n${t}` : back));
      setBusy(false);
      void readAll(room);
    } catch { /* もう止まっている */ }
  }

  const live = liveStepsFromEvents(steps);
  const sentTimes = sentSinceReply(messages.filter(m => !m.pending));
  const from = liveStartedAt(live.find(x => x.at)?.at, sentTimes);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {header}
      <div ref={list} onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain px-3 py-3">
        {more ? (
          <button type="button" onClick={() => void readOlder()} className="mx-auto block text-xs text-stone-500 underline">前の話を読む</button>
        ) : null}
        {!room && !error ? <p className="flex items-center gap-2 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" />会話を開いています</p> : null}
        {error ? <p className="rounded-md bg-rose-50 p-2 text-sm text-rose-800">{error}</p> : null}
        {messages.map(m => {
          if (isDan(m)) {
            return (
              <div key={m.id} className="max-w-full">
                <DanBody body={m.content || ''} messageId={m.id} />
                <time className="mt-0.5 block text-[11px] text-stone-400">ダン {clock(m.created_at)}</time>
              </div>
            );
          }
          const about = aboutOf(m.content || '');
          const said = parseMediaContent(m.content || '').text;
          return (
            <div key={m.id} className="ml-6 flex flex-col items-end">
              {about ? (
                <span className="mb-0.5 max-w-full truncate text-[11px] text-stone-500">
                  {about.title ? `「${about.title}」` : ''}{about.lines ? `の${about.lines}` : ''}{about.text ? `「${about.text.slice(0, 30)}${about.text.length > 30 ? '…' : ''}」` : ''}
                </span>
              ) : null}
              <p className={cn('max-w-full whitespace-pre-wrap break-words rounded-2xl rounded-br-md px-3 py-2 text-[14px] leading-relaxed', m.failed ? 'bg-rose-50 text-rose-900' : 'bg-amber-100 text-stone-900', m.pending && !m.failed && 'opacity-70')}>{said}</p>
              {m.failed ? <span className="mt-0.5 text-[11px] text-rose-700">{m.failed}</span> : <time className="mt-0.5 text-[11px] text-stone-400">{m.pending ? '送っています' : clock(m.created_at)}</time>}
            </div>
          );
        })}
        {busy ? (
          <div className="flex items-center gap-2 text-[13px] text-stone-600" role="status" aria-live="polite">
            <span className="flex gap-0.5" aria-hidden>
              <i className="h-1.5 w-1.5 animate-bounce rounded-full bg-amber-500 [animation-delay:-0.2s]" />
              <i className="h-1.5 w-1.5 animate-bounce rounded-full bg-amber-500 [animation-delay:-0.1s]" />
              <i className="h-1.5 w-1.5 animate-bounce rounded-full bg-amber-500" />
            </span>
            <span className="min-w-0 flex-1 truncate">{liveLineText(live)}</span>
            <span className="tabular-nums text-stone-400">{elapsedText(from, now)}</span>
          </div>
        ) : null}
      </div>
      <div className="space-y-1.5 border-t border-stone-200 bg-white p-2">
        <ContextChip ctx={ctx} onClear={onClearSelection} onClearPick={onClearPick} />
        <div className="flex items-end gap-1.5 rounded-xl border border-stone-300 bg-white p-1.5 focus-within:border-amber-500 focus-within:ring-2 focus-within:ring-amber-100">
          <textarea
            ref={area}
            rows={1}
            value={text}
            aria-label="ダンに書く"
            placeholder="ダンに聞く・頼む"
            onChange={e => setText(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229 && !touchOnly()) { e.preventDefault(); void send(); }
            }}
            className="min-h-[36px] flex-1 resize-none bg-transparent px-1.5 py-1.5 text-[14px] leading-relaxed text-stone-900 outline-none placeholder:text-stone-400"
          />
          {busy && !text.trim() ? (
            <button type="button" onClick={() => void stop()} aria-label="止める" title="止める"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-stone-800 text-white hover:bg-stone-700"><Square className="h-3.5 w-3.5 fill-current" /></button>
          ) : (
            <button type="button" onClick={() => void send()} disabled={!text.trim() || !room || sending} aria-label="送る"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-600 text-white hover:bg-amber-700 disabled:bg-stone-200 disabled:text-stone-400">
              {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" strokeWidth={2.6} />}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** スマホの「ダンと話す」の丸いボタン（押すと下から会話が出る） */
export function TalkButton({ onOpen, lift = 'low', busy }: { onOpen: () => void; lift?: 'low' | 'mid' | 'high'; busy?: boolean }) {
  return (
    <button type="button" onClick={onOpen}
      className={cn('fixed right-3 z-40 flex items-center gap-1.5 rounded-full bg-amber-600 px-4 py-3 text-sm font-bold text-white shadow-lg active:bg-amber-700',
        lift === 'high' ? 'bottom-[calc(env(safe-area-inset-bottom)+150px)]' : lift === 'mid' ? 'bottom-[calc(env(safe-area-inset-bottom)+76px)]' : 'bottom-[calc(env(safe-area-inset-bottom)+16px)]')}>
      <MessageCircle className="h-4 w-4" />ダンと話す{busy ? <span className="h-2 w-2 rounded-full bg-emerald-300" aria-label="作業中" /> : null}
    </button>
  );
}
