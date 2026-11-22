'use client';

// ダンを動かしている指示文を、本人が構成図から辿って読み、そのまま書き直し、前の版に戻す画面（2026-11-17）。
// 上は上から下への構成図（architecture.ts。箱と矢印はコードで確かめた呼び出し順）。箱を押すとその箱が読む指示文の一覧、
// 押すと全文がそのまま出て、その場で書き直せる。誰が読むか・いつ効くか・なぜある文か・履歴は全文の下にたたんである。
// 使う所: /prompts（app/prompts/page.tsx）と、開発室のボードの「指示文」（artifacts/dev-lead）。
// 裏側は app/api/prompts_screen.py、文の置き場所と履歴は app/services/prompt_store.py。
import { useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { ArrowLeft, ChevronDown, History, Loader2, Lock, PenLine, RotateCcw, Save, X } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { SideResizeHandle, useSideWidth } from '@/components/ui/side-resize';
import { ApiError } from '@/lib/api-client';
import { promptsApi, type PromptItem, type PromptSummary, type PromptVersion } from '@/lib/prompts-api';
import { cn } from '@/lib/utils';
import { BOX_H, EDGES, H, NODES, W, WORK_FRAME, type ArchEdge, type ArchNode } from './architecture';
import { diffText, hunks, lineDiff } from './line-diff';
import { PromptsChat, TalkButton, type PromptChatContext } from './prompts-chat';

type Selection = { from: number; to: number; text: string };
/** 文の中の位置（何文字目）から行番号（1から） */
const lineAt = (text: string, offset: number) => text.slice(0, offset).split('\n').length;
function selectionOf(text: string, start: number, end: number): Selection | null {
  if (end <= start) return null;
  const picked = text.slice(start, end);
  if (!picked.trim()) return null;
  const to = lineAt(text, picked.endsWith('\n') ? end - 1 : end);
  return { from: lineAt(text, start), to, text: picked };
}

/** 変わった所（ダンが直した所）。消した行は赤い線、足した行は緑 */
function DiffView({ before, after }: { before: string; after: string }) {
  const rows = useMemo(() => hunks(lineDiff(before, after)), [before, after]);
  return (
    <div className="max-h-72 overflow-auto rounded-md border border-stone-200 bg-white font-mono text-[12.5px] leading-relaxed">
      {rows.map((r, i) => ('gap' in r
        ? <div key={i} className="bg-stone-50 px-2 text-[11px] text-stone-400">… 同じ行 {r.gap}</div>
        : <div key={i} className={cn('flex gap-2 whitespace-pre-wrap break-all px-2', r.kind === 'add' ? 'bg-emerald-50 text-emerald-900' : r.kind === 'del' ? 'bg-rose-50 text-rose-900 line-through decoration-rose-400' : 'text-stone-600')}>
            <span className="w-8 shrink-0 select-none text-right text-stone-400">{r.kind === 'del' ? '' : r.line}</span>
            <span className="w-3 shrink-0 select-none">{r.kind === 'add' ? '+' : r.kind === 'del' ? '−' : ''}</span>
            <span className="min-w-0 flex-1">{r.text || ' '}</span>
          </div>))}
    </div>
  );
}

const WHO: Record<string, string> = { owner: 'みきさん', dan: 'ダン', seed: '元の文' };
// 前の画面（家の絵）の場所の名前で開かれた時の行き先
const OLD_PLACE: Record<string, string> = { work: 'parallel' };
const BY_ID = new Map(NODES.map(n => [n.id, n]));

export function nodeOf(place: string): ArchNode | undefined {
  return BY_ID.get(OLD_PLACE[place] || place);
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.data as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') return detail;
    if (err.status === 401) return 'ログインが切れています。';
  }
  return err instanceof Error ? err.message : '失敗しました。';
}

function when(at?: string | null): string {
  if (!at) return '';
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return at;
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function StateBadge({ p }: { p: Pick<PromptSummary, 'readonly' | 'last_by' | 'last_at'> }) {
  if (p.readonly) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-stone-600">
        <Lock className="h-3 w-3" />プログラムの中（読むだけ）
      </span>
    );
  }
  if (p.last_by === 'owner') return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-800">みきさんが直した {when(p.last_at)}</span>;
  if (p.last_by === 'dan') return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-800">ダンが直した {when(p.last_at)}</span>;
  return <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-800">元の文のまま</span>;
}

// ---- 構成図 ----
function anchor(n: ArchNode, side: 't' | 'b' | 'l' | 'r', at?: number): [number, number] {
  if (side === 't') return [n.x + (at ?? n.w / 2), n.y];
  if (side === 'b') return [n.x + (at ?? n.w / 2), n.y + BOX_H];
  if (side === 'l') return [n.x, n.y + BOX_H / 2];
  return [n.x + n.w, n.y + BOX_H / 2];
}
const NORMAL = { t: [0, -1], b: [0, 1], l: [-1, 0], r: [1, 0] } as const;

function edgePath(e: ArchEdge) {
  const a = BY_ID.get(e.from)!, b = BY_ID.get(e.to)!;
  const sa = e.a || 'b', sb = e.b || 't';
  const [x1, y1] = anchor(a, sa, e.ax), [x2, y2] = anchor(b, sb, e.bx);
  const bend = e.bend ?? Math.max(18, Math.abs(y2 - y1) * 0.45);
  const c1 = [x1 + NORMAL[sa][0] * bend, y1 + NORMAL[sa][1] * bend];
  const c2 = [x2 + NORMAL[sb][0] * bend, y2 + NORMAL[sb][1] * bend];
  const t = e.at ?? 0.5, u = 1 - t;
  const mx = u * u * u * x1 + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * x2;
  const my = u * u * u * y1 + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * y2;
  return { d: `M${x1},${y1} C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${x2},${y2}`, mx, my };
}

function Diagram({ counts, active, onPick }: { counts: Record<string, number>; active: string; onPick: (id: string) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const fit = () => setScale(Math.min(1, Math.max(0.62, el.clientWidth / W)));
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // 図が枠より広い時（スマホ）は、押した箱（無ければ真ん中の通話の列）が見える所まで横に送る
  useEffect(() => {
    const el = wrap.current;
    if (!el || el.scrollWidth <= el.clientWidth) return;
    const n = BY_ID.get(active) || BY_ID.get('voice')!;
    el.scrollTo({ left: Math.max(0, (n.x + n.w / 2) * scale - el.clientWidth / 2), behavior: 'smooth' });
  }, [active, scale]);
  const edges = useMemo(() => EDGES.map(e => ({ e, ...edgePath(e) })), []);
  return (
    <div ref={wrap} className="w-full overflow-x-auto rounded-xl border border-stone-200 bg-white">
      <div style={{ width: W * scale, height: H * scale }} className="relative mx-auto">
        <div style={{ width: W, height: H, transform: `scale(${scale})`, transformOrigin: '0 0' }} className="absolute left-0 top-0">
          <div className="absolute rounded-2xl border-2 border-dashed border-stone-300 bg-stone-50"
            style={{ left: WORK_FRAME.x, top: WORK_FRAME.y, width: WORK_FRAME.w, height: WORK_FRAME.h }}>
            <span className="absolute left-3 top-1.5 text-[13px] font-bold text-stone-600">{WORK_FRAME.name}</span>
          </div>
          <p className="absolute text-[12px] text-stone-500" style={{ left: WORK_FRAME.x + 4, top: WORK_FRAME.y + WORK_FRAME.h + 6, width: WORK_FRAME.w }}>
            {WORK_FRAME.line}
          </p>
          <svg width={W} height={H} className="absolute left-0 top-0 overflow-visible" aria-hidden="true">
            <defs>
              <marker id="arch-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#78716c" />
              </marker>
            </defs>
            {edges.map(({ e, d }) => (
              <path key={`${e.from}-${e.to}`} d={d} fill="none" stroke="#a8a29e" strokeWidth={2} strokeDasharray={e.dashed ? '6 5' : undefined} markerEnd="url(#arch-arrow)" />
            ))}
          </svg>
          {edges.filter(x => x.e.label).map(({ e, mx, my }) => (
            <span key={`l-${e.from}-${e.to}`} className="absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded bg-white/95 px-1 text-[11px] leading-tight text-stone-500"
              style={{ left: mx, top: my }}>{e.label}</span>
          ))}
          {NODES.map(n => {
            const on = n.id === active, count = counts[n.id] || 0;
            return (
              <button key={n.id} type="button" onClick={() => onPick(n.id)}
                style={{ left: n.x, top: n.y, width: n.w, height: BOX_H }}
                className={cn('absolute flex items-center gap-2 rounded-xl border-2 bg-white p-1.5 text-left shadow-sm transition hover:border-amber-400 hover:bg-amber-50',
                  on ? 'border-amber-500 bg-amber-50 ring-4 ring-amber-200' : 'border-stone-300')}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`/prompts/arch/${n.icon}.webp`} alt="" className="h-[60px] w-[60px] shrink-0 rounded-lg object-cover" draggable={false} />
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 block text-[14px] font-bold leading-tight text-stone-900">{n.name}</span>
                  <span className="mt-0.5 block truncate text-[11px] leading-tight text-stone-500">{n.model}</span>
                  {count ? <span className="mt-1 inline-block rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-900">指示文 {count}</span>
                    : n.same ? <span className="mt-1 inline-block text-[11px] text-stone-400">{BY_ID.get(n.same)?.name}と同じ文</span> : null}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---- 全文と書き直し ----
type DanChange = { before: string; beforeSha: string; after: string; note: string; by: string; at?: string };

function Editor({ id, pulse, onBack, onSaved, onState, onSelection }: {
  id: string;
  /** 会話のダンが動いている間・返事が来た時に増える。そのたびに版を見て、ダンが直していれば全文を新しい版にする */
  pulse: number;
  onBack: () => void; onSaved: () => void;
  /** 開いている文と書きかけ（会話に添える） */
  onState: (item: PromptItem | null, draft: string) => void;
  /** 選んでいる所・カーソルの行（会話に添える） */
  onSelection: (sel: Selection | null, cursor: number | null) => void;
}) {
  const [item, setItem] = useState<PromptItem | null>(null);
  const [draft, setDraft] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [viewing, setViewing] = useState<PromptVersion | null>(null);
  const [change, setChange] = useState<DanChange | null>(null);   // ダンが会話から直した所（元に戻すまで出す）
  const [waiting, setWaiting] = useState<PromptItem | null>(null);   // 書きかけがある間に届いたダンの版
  const [showDiff, setShowDiff] = useState(true);
  const area = useRef<HTMLTextAreaElement>(null);
  const plain = useRef<HTMLPreElement>(null);
  const itemRef = useRef<PromptItem | null>(null);
  const draftRef = useRef('');
  useLayoutEffect(() => { itemRef.current = item; draftRef.current = draft; }, [item, draft]);
  useEffect(() => { onState(item, draft); }, [item, draft, onState]);

  // ダンが直したか（会話のダンが動いている間と返事が来た時）。版の印だけ聞き、変わっていたら全文を読み直す
  const checking = useRef(false);
  useEffect(() => {
    if (!pulse || checking.current) return;
    const now = itemRef.current;
    if (!now || now.readonly) return;
    checking.current = true;
    promptsApi.sha(now.id)
      .then(async got => {
        if (got.sha === itemRef.current?.sha) return;
        const fresh = await promptsApi.item(now.id);
        const old = itemRef.current;
        if (!old || fresh.sha === old.sha) return;
        const last = fresh.history[0];
        const dirty = draftRef.current !== old.text;
        if (dirty) { setWaiting(fresh); return; }
        setItem(fresh); setDraft(fresh.text); setViewing(null); setWaiting(null); setShowDiff(true);
        setChange({ before: old.text, beforeSha: old.sha, after: fresh.text, note: last?.note || '', by: last?.by || 'dan', at: last?.at });
        toast.success(`${WHO[last?.by || 'dan'] || 'ダン'}が「${fresh.title}」を直しました。`);
        onSaved();
      })
      .catch(() => undefined)
      .finally(() => { checking.current = false; });
  }, [pulse, onSaved]);

  function takeWaiting() {
    const old = itemRef.current;
    if (!waiting || !old) return;
    const last = waiting.history[0];
    setChange({ before: old.text, beforeSha: old.sha, after: waiting.text, note: last?.note || '', by: last?.by || 'dan', at: last?.at });
    setItem(waiting); setDraft(waiting.text); setWaiting(null); setShowDiff(true);
    onSaved();
  }

  async function undoChange() {
    if (!item || !change) return;
    setBusy(true); setError('');
    try {
      const out = await promptsApi.revert(item.id, change.beforeSha);
      setItem(out.item); setDraft(out.item.text); setChange(null);
      toast.success('ダンが直す前の文に戻しました。');
      onSaved();
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  const report = (el: HTMLTextAreaElement) => {
    onSelection(selectionOf(el.value, el.selectionStart, el.selectionEnd), lineAt(el.value, el.selectionStart));
  };
  // 読むだけの文・前の版は <pre>。その中で選んだ文を拾う
  const reportPlain = () => {
    const pre = plain.current, sel = typeof window !== 'undefined' ? window.getSelection() : null;
    if (!pre || !sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    if (!pre.contains(range.startContainer) || !pre.contains(range.endContainer)) return;
    const head = document.createRange();
    head.selectNodeContents(pre);
    head.setEnd(range.startContainer, range.startOffset);
    const start = head.toString().length;
    const whole = pre.textContent || '';
    onSelection(selectionOf(whole, start, start + range.toString().length), lineAt(whole, start));
  };

  // 文が替わる時は呼ぶ側が key={id} で作り直すので、ここは開いた時に1回読むだけ
  useEffect(() => {
    let live = true;
    promptsApi.item(id)
      .then(got => { if (live) { setItem(got); setDraft(got.text); setNote(''); setViewing(null); } })
      .catch(err => { if (live) setError(errorText(err)); });
    return () => { live = false; };
  }, [id]);

  // 欄の高さを中身に合わせる（全文がそのまま並び、欄の中で別にスクロールしない）
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + 4}px`;
  }, [draft, item, viewing]);

  const changed = item ? draft !== item.text : false;

  async function save() {
    if (!item) return;
    setBusy(true); setError('');
    try {
      const out = await promptsApi.save(item.id, draft, note, item.sha);
      setItem(out.item); setDraft(out.item.text); setNote(''); setViewing(null); setChange(null); setWaiting(null);
      toast.success(out.saved ? '保存しました。次にこの文が読まれる時から効きます。' : '中身が同じなので変えていません。');
      onSaved();
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  async function revert(v: PromptVersion) {
    if (!item) return;
    if (!window.confirm(`${when(v.at)}（${WHO[v.by] || v.by}）の版に戻しますか？今の文も履歴に残ります。`)) return;
    setBusy(true); setError('');
    try {
      const out = await promptsApi.revert(item.id, v.sha);
      setItem(out.item); setDraft(out.item.text); setViewing(null);
      toast.success('戻しました。');
      onSaved();
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  if (!item) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-stone-500">
        {error ? <span className="text-rose-700">{error}</span> : <><Loader2 className="h-4 w-4 animate-spin" />読んでいます</>}
      </div>
    );
  }

  const last = item.history[0];
  const cautions = [
    item.kind === 'sections' && !item.readonly ? '「## 名前」の行は、プログラムがその名前で選ぶ印です。見出しの行は変えずに、その下の文を直してください。' : '',
    item.kind === 'words' && !item.readonly ? '1行に1つの言葉です。行を足すと、その言葉でも作業が起きるようになります。' : '',
    item.marks?.length && !item.readonly ? `${item.marks.map(m => `{${m}} には${item.mark_notes?.[m] || '値'}が入ります`).join('。')}。この印は消さないでください。` : '',
  ].filter(Boolean);

  return (
    <div className="space-y-3">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm text-stone-500 hover:text-stone-800 xl:hidden">
        <ArrowLeft className="h-4 w-4" />一覧に戻る
      </button>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-base font-bold leading-snug text-stone-900">{item.title}</h2>
        <StateBadge p={{ readonly: item.readonly, last_by: last?.by, last_at: last?.at }} />
        <span className="text-xs text-stone-400">{draft.length.toLocaleString()}字</span>
      </div>

      {waiting ? (
        <div className="flex flex-col gap-2 rounded-lg border border-sky-300 bg-sky-50 p-2.5 text-sm text-sky-950 sm:flex-row sm:items-center">
          <span className="flex-1">ダンがこの文の新しい版を保存しました。今の書きかけはまだ保存していません。</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={takeWaiting} className="border-sky-300 bg-white text-sky-900 hover:bg-sky-100">ダンの版を開く（書きかけは消える）</Button>
          </div>
        </div>
      ) : null}
      {change ? (
        <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-2.5" data-testid="dan-change">
          <div className="flex flex-wrap items-start gap-2">
            <p className="min-w-0 flex-1 text-sm text-amber-950">
              <b>{WHO[change.by] || 'ダン'}が直しました{change.at ? `（${when(change.at)}）` : ''}</b>{change.note ? `：${change.note}` : ''}
            </p>
            <div className="flex shrink-0 gap-1.5">
              <Button size="sm" variant="outline" onClick={() => setShowDiff(v => !v)} className="h-8 border-amber-300 bg-white px-2 text-amber-900 hover:bg-amber-100">{showDiff ? '変わった所を隠す' : '変わった所'}</Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void undoChange()} className="h-8 border-amber-300 bg-white px-2 text-amber-900 hover:bg-amber-100"><RotateCcw className="mr-1 h-3.5 w-3.5" />元に戻す</Button>
              <button type="button" aria-label="閉じる" onClick={() => setChange(null)} className="rounded p-1 text-amber-800 hover:bg-amber-100"><X className="h-4 w-4" /></button>
            </div>
          </div>
          {showDiff ? <DiffView before={change.before} after={change.after} /> : null}
        </div>
      ) : null}

      {viewing ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">{when(viewing.at)} の版（{WHO[viewing.by] || viewing.by}）</span>
            <Button size="sm" variant="outline" onClick={() => setViewing(null)} className="border-stone-300 bg-white text-stone-700 hover:bg-stone-100">今の文に戻る</Button>
            {!item.readonly && viewing.sha !== item.sha ? (
              <Button size="sm" onClick={() => void revert(viewing)} disabled={busy}><RotateCcw className="mr-1 h-4 w-4" />この版に戻す</Button>
            ) : null}
          </div>
          <pre ref={plain} onMouseUp={reportPlain} onTouchEnd={reportPlain} className="whitespace-pre-wrap rounded-md border bg-stone-50 p-3 text-[14px] leading-relaxed text-stone-800">{viewing.text}</pre>
        </div>
      ) : item.readonly ? (
        <div className="space-y-2">
          <pre ref={plain} onMouseUp={reportPlain} onTouchEnd={reportPlain} className="whitespace-pre-wrap rounded-md border bg-stone-50 p-3 text-[14px] leading-relaxed text-stone-800">{item.text}</pre>
          <p className="text-xs text-stone-500">この文はまだプログラムの中にあるので、ここでは読むだけです。直したい時はダンに言ってください。この画面で直せる形に移します。</p>
        </div>
      ) : (
        <div>
          <label htmlFor="prompt-text" className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-amber-800">
            <PenLine className="h-4 w-4" />この文は、ここでそのまま書き直せます
          </label>
          <textarea
            id="prompt-text"
            ref={area}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onSelect={e => report(e.currentTarget)}
            onMouseUp={e => report(e.currentTarget)}
            onKeyUp={e => report(e.currentTarget)}
            onTouchEnd={e => report(e.currentTarget)}
            spellCheck={false}
            className="block w-full resize-none overflow-hidden rounded-lg border-2 border-amber-300 bg-white px-3 py-2 text-[14px] leading-relaxed text-stone-900 shadow-inner outline-none focus:border-amber-500 focus:ring-4 focus:ring-amber-100"
          />
          {cautions.map(c => <p key={c} className="mt-1 text-xs text-amber-900">{c}</p>)}
          <div className={cn('sticky bottom-0 z-10 -mx-1 mt-2 rounded-lg border px-2 py-2 shadow-lg', changed ? 'border-amber-400' : 'border-stone-200')}
            style={{ background: changed ? '#fff7e0' : 'rgba(255,255,255,0.97)' }}>
            {changed ? (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <input
                  value={note}
                  onChange={e => setNote(e.target.value)}
                  placeholder="なぜ直したか（空でも保存できます）"
                  className="h-9 flex-1 rounded-md border border-stone-300 bg-white px-3 text-sm text-stone-900"
                />
                <div className="flex gap-2">
                  <Button variant="outline" disabled={busy} onClick={() => setDraft(item.text)} className="border-stone-300 bg-white text-stone-700 hover:bg-stone-100">直す前に戻す</Button>
                  <Button disabled={busy} onClick={() => void save()} className="bg-amber-600 text-white hover:bg-amber-700">
                    {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}保存
                  </Button>
                </div>
              </div>
            ) : (
              <p className="text-xs text-stone-500">文を書き直すと、ここに「保存」が出ます。保存すると、次にこの文が読まれる時から効きます。</p>
            )}
          </div>
        </div>
      )}
      {error ? <p className="rounded-md bg-rose-50 p-2 text-sm text-rose-800">{error}</p> : null}

      <details className="group rounded-lg border border-stone-200 bg-stone-50">
        <summary className="flex cursor-pointer list-none items-center gap-1 px-3 py-2 text-sm text-stone-600">
          <ChevronDown className="h-4 w-4 transition group-open:rotate-180" />この文について（誰が読むか・いつ効くか・なぜある文か・元の場所）
        </summary>
        <dl className="grid gap-x-4 gap-y-1 px-3 pb-3 text-sm sm:grid-cols-[7em_1fr]">
          <dt className="text-stone-500">誰が読むか</dt><dd className="text-stone-800">{item.reader}</dd>
          <dt className="text-stone-500">いつ効くか</dt><dd className="text-stone-800">{item.when}</dd>
          <dt className="text-stone-500">なぜある文か</dt><dd className="text-stone-800">{item.why}</dd>
          <dt className="text-stone-500">元の場所</dt><dd className="break-all font-mono text-xs text-stone-500">{item.source}</dd>
        </dl>
      </details>

      {item.history.length || item.code_history?.length ? (
        <details className="group rounded-lg border border-stone-200">
          <summary className="flex cursor-pointer list-none items-center gap-1 px-3 py-2 text-sm text-stone-600">
            <ChevronDown className="h-4 w-4 transition group-open:rotate-180" /><History className="h-4 w-4" />
            履歴（この画面で{item.history.length}版{item.code_history?.length ? `・プログラムの中で${item.code_history.length}回` : ''}）
          </summary>
          <div className="space-y-3 px-3 pb-3">
            {item.history.length ? (
              <ul className="divide-y rounded-md border bg-white text-sm">
                {item.history.map((v, i) => (
                  <li key={`${v.sha}-${v.at}-${i}`}>
                    <button type="button" onClick={() => setViewing(v)} className="flex w-full flex-wrap items-baseline gap-x-2 px-3 py-2 text-left hover:bg-stone-50">
                      <span className="tabular-nums text-stone-500">{when(v.at)}</span>
                      <span className={cn('font-semibold', v.by === 'owner' ? 'text-emerald-700' : v.by === 'dan' ? 'text-amber-700' : 'text-sky-700')}>{WHO[v.by] || v.by}</span>
                      {i === 0 ? <span className="text-xs text-stone-400">今の文</span> : null}
                      <span className="w-full text-stone-600 sm:w-auto">{v.note}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {item.code_history?.length ? (
              <div>
                <h3 className="mb-1 text-xs font-semibold text-stone-600">プログラムの中にあった頃に直された日</h3>
                <ul className="space-y-0.5 text-xs text-stone-600">
                  {item.code_history.map((h, i) => (
                    <li key={`${h.date}-${i}`}><span className="tabular-nums text-stone-400">{h.date}</span> {h.what || '（直した理由の記録なし）'}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

// ---- 画面全体 ----
export function PromptsScreen({ place, id, onGo, embedded = false }: {
  place: string; id: string; onGo: (next: { place: string; id?: string }) => void; embedded?: boolean;
}) {
  const [prompts, setPrompts] = useState<PromptSummary[]>([]);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const node = nodeOf(place);
  const detail = useRef<HTMLElement>(null);
  const list = useRef<HTMLElement>(null);

  const [round, setRound] = useState(0);   // 保存・戻すの後に一覧を読み直す
  const load = useCallback(() => setRound(n => n + 1), []);

  // ---- ダンとの会話（2026-11-21）。今開いている文・選んだ所・書きかけを会話に添える ----
  const [pulse, setPulse] = useState(0);
  const [talkOpen, setTalkOpen] = useState(false);   // スマホの下から出す会話
  const [talkBusy, setTalkBusy] = useState(false);
  const [open, setOpen] = useState<{ item: PromptItem | null; draft: string }>({ item: null, draft: '' });
  // 選んだ所は、どの文で選んだかと一緒に持つ（別の文を開いたら使わない）
  const [picked, setPicked] = useState<{ id: string; sel: Selection | null; cursor: number | null }>({ id: '', sel: null, cursor: null });
  const onState = useCallback((item: PromptItem | null, draft: string) => setOpen({ item, draft }), []);
  const onSelection = useCallback((next: Selection | null, cursor: number | null) => setPicked({ id, sel: next, cursor }), [id]);
  const sel = useMemo(() => (picked.id === id ? picked : { sel: null, cursor: null }), [picked, id]);
  const shownDraft = useDeferredValue(open.draft);
  const shown = open.item && open.item.id === id ? open.item : null;
  const draftDiff = useMemo(() => (shown && !shown.readonly && shownDraft !== shown.text ? diffText(shown.text, shownDraft) : null), [shown, shownDraft]);
  const talkCtx = useMemo<PromptChatContext>(() => ({
    place: node ? { id: node.id, name: node.name } : null,
    prompt: shown ? { id: shown.id, title: shown.title, reader: shown.reader, when: shown.when, readonly: shown.readonly, source: shown.source, chars: shown.chars } : null,
    selection: sel.sel,
    cursor: sel.cursor,
    draftDiff,
  }), [node, shown, sel, draftDiff]);
  const bump = useCallback(() => setPulse(n => n + 1), []);
  // 選んだ箱・文を外す（2026-11-22 本人「選択解除できないから、関係ない所を押したり札の×で外せるように」）。
  // 保存していない書きかけがある時は、文を閉じると書きかけが消えるので、確かめてから閉じる
  const clearPick = useCallback(() => {
    if (!place && !id) return;
    if (draftDiff && !window.confirm('保存していない書きかけがあります。閉じると消えます。閉じますか？')) return;
    setPicked({ id: '', sel: null, cursor: null });
    onGo({ place: '' });
  }, [place, id, draftDiff, onGo]);
  // 左の余白を押した時だけ外す。押せる物・全文の欄・文字をなぞって選んでいる最中は外さない
  const onBlank = useCallback((e: ReactMouseEvent) => {
    if (!place && !id) return;
    const t = e.target as HTMLElement;
    if (t.closest('button, a, input, textarea, select, summary, label, [role="button"], main, details')) return;
    if (window.getSelection()?.toString()) return;
    if (draftDiff) { setPicked(v => ({ ...v, sel: null })); return; }   // 書きかけは消さない。選んだ行だけ外す
    clearPick();
  }, [place, id, draftDiff, clearPick]);
  // PC の会話の欄は右に常にいる（スクロールしても動かない）。左の表示との境目を引いて幅を変える（2026-11-21 本人）
  const [talkRef, side] = useSideWidth('dan-prompts-chat-width', 400);
  // スマホの「ダンと話す」は、全文の下に貼り付く保存の帯の上に出す
  const lift = draftDiff ? 'high' : shown && !shown.readonly ? 'mid' : 'low';
  useEffect(() => {
    let live = true;
    promptsApi.list()
      .then(data => { if (live) { setPrompts(data.prompts); setError(''); } })
      .catch(err => { if (live) setError(errorText(err)); })
      .finally(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, [round]);

  const byId = useMemo(() => new Map(prompts.map(p => [p.id, p])), [prompts]);
  const skills = useMemo(() => prompts.filter(p => p.id.startsWith('skill/')), [prompts]);
  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const n of NODES) out[n.id] = (n.prompts || []).filter(pid => byId.has(pid)).length;
    return out;
  }, [byId]);
  // どの箱にも入っていない文（台帳に足されたのに図に無い物）も、失くさず下に出す
  const loose = useMemo(() => {
    const placed = new Set(NODES.flatMap(n => n.prompts || []));
    return prompts.filter(p => !p.id.startsWith('skill/') && !placed.has(p.id));
  }, [prompts]);

  const here = (node?.prompts || []).map(pid => byId.get(pid)).filter((p): p is PromptSummary => !!p);
  const editable = here.filter(p => !p.readonly);
  const readonly = here.filter(p => p.readonly);

  useEffect(() => {   // 狭い画面では、選んだ物の所まで送る
    if (typeof window === 'undefined' || window.innerWidth >= 1280) return;
    const target = id ? detail.current : place ? list.current : null;
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [id, place]);

  const row = (p: PromptSummary) => (
    <li key={p.id}>
      <button type="button" onClick={() => onGo({ place, id: p.id })}
        className={cn('w-full rounded-lg border px-3 py-2 text-left transition hover:border-amber-400 hover:bg-amber-50',
          p.id === id ? 'border-amber-500 bg-amber-50' : 'border-stone-200 bg-white')}>
        <div className="text-sm font-semibold leading-snug text-stone-900">{p.title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <StateBadge p={p} />
          {p.chars ? <span className="text-[11px] text-stone-400">{p.chars.toLocaleString()}字</span> : null}
        </div>
      </button>
    </li>
  );

  return (
    <div className="lg:flex lg:h-full lg:min-h-0">
    {/* 左: 図・一覧・全文。PC はここだけがスクロールする */}
    <div className={cn('space-y-4 lg:min-w-0 lg:flex-1 lg:overflow-y-auto lg:overscroll-contain', embedded ? 'p-3 sm:p-4' : 'px-3 py-4 sm:px-6')} onClick={onBlank} data-prompts-left>
      <div className="mx-auto max-w-[1100px] space-y-4">
      <header>
        <h1 className="text-xl font-bold">ダンを動かしている指示文</h1>
        <p className="text-sm text-stone-600">上から下へ、みきさんの頼みが流れる順に並んでいます。箱を押すと、その箱が読む指示文が出ます。</p>
      </header>
      {error ? (
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {error} <a className="underline" href="/login?redirect=/prompts" target="_top">ログインする</a>
        </p>
      ) : null}
      <Diagram counts={counts} active={node?.id || ''} onPick={p => onGo({ place: p })} />

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
        <aside ref={list} className={cn('scroll-mt-2 space-y-3', id && 'hidden xl:block')}>
          {node ? (
            <div className="flex items-start gap-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`/prompts/arch/${node.icon}.webp`} alt="" className="h-14 w-14 shrink-0 rounded-lg" />
              <div>
                <h2 className="text-lg font-bold leading-tight">{node.name}</h2>
                <p className="text-xs text-stone-500">{node.model}</p>
                <p className="mt-1 text-sm text-stone-700">{node.line}</p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-stone-500">図の箱を押すと、ここにその箱が読む指示文が並びます。</p>
          )}
          {editable.length ? <ul className="space-y-2">{editable.map(row)}</ul> : null}
          {readonly.length ? (
            <details open={!editable.length}>
              <summary className="cursor-pointer text-sm text-stone-600">まだプログラムの中にある文（読むだけ・{readonly.length}）</summary>
              <ul className="mt-2 space-y-2">{readonly.map(row)}</ul>
            </details>
          ) : null}
          {node?.same ? (
            <p className="text-sm text-stone-600">
              ここは「<button type="button" className="font-semibold text-amber-800 underline" onClick={() => onGo({ place: node.same! })}>{BY_ID.get(node.same)?.name}</button>」と同じ決まりも読みます。
            </p>
          ) : null}
          {node?.skills && skills.length ? (
            <details>
              <summary className="cursor-pointer text-sm text-stone-600">手順書と案件ごとの参考（{skills.length}）</summary>
              <h3 className="mt-3 text-sm font-semibold">動画編集の共通手順</h3>
              <ul className="mt-2 space-y-2">{skills.filter(p => !p.readonly && !p.id.includes('/references/')).map(row)}</ul>
              <h3 className="mt-3 text-sm font-semibold">案件ごとの編集方針</h3>
              <ul className="mt-2 space-y-2">{skills.filter(p => p.id.includes('/references/')).map(row)}</ul>
              <h3 className="mt-3 text-sm font-semibold">その他の手順書</h3>
              <ul className="mt-2 space-y-2">{skills.filter(p => p.readonly).map(row)}</ul>
            </details>
          ) : null}
          {node && !here.length && !node.same && loaded && !error ? (
            <p className="text-sm text-stone-500">ここはプログラムだけで動いていて、モデルが読む指示文はありません。</p>
          ) : null}
          {loose.length ? (
            <details>
              <summary className="cursor-pointer text-xs text-stone-500">図のどの箱にもまだ入れていない文（{loose.length}）</summary>
              <ul className="mt-2 space-y-2">{loose.map(row)}</ul>
            </details>
          ) : null}
        </aside>
        <main ref={detail} className={cn('min-w-0 scroll-mt-2 rounded-xl border border-stone-200 bg-white p-3 sm:p-4', !id && 'hidden xl:block')}>
          {id ? (
            <Editor key={id} id={id} pulse={pulse} onBack={() => onGo({ place })} onSaved={load} onState={onState} onSelection={onSelection} />
          ) : (
            <p className="text-sm text-stone-500">左の一覧から文を選ぶと、ここに全文がそのまま出ます。</p>
          )}
        </main>
      </div>
      </div>
    </div>
    {/* 右: ダンとの会話。PC は右に常にいて、境目を引いて幅を変える。スマホは下から出す。中身は1つだけ置く（会話の線を2本にしない） */}
    <section ref={talkRef} aria-label="ダンと話す" style={side.style}
      className={cn(
        'z-50 flex-col overflow-hidden bg-white',
        talkOpen ? 'flex' : 'hidden',
        'fixed inset-x-0 bottom-0 h-[72dvh] rounded-t-2xl border-t border-stone-300 shadow-[0_-8px_30px_rgba(0,0,0,0.18)]',
        'lg:relative lg:inset-auto lg:z-auto lg:flex lg:h-full lg:w-[var(--side-w)] lg:shrink-0 lg:overflow-visible lg:rounded-none lg:border-l lg:border-t-0 lg:border-stone-200 lg:shadow-none',
      )}>
      <SideResizeHandle side={side} className="hidden lg:block" />
      <PromptsChat ctx={talkCtx} onPulse={bump} onBusy={setTalkBusy} onClearSelection={() => setPicked(v => ({ ...v, sel: null }))} onClearPick={clearPick}
        header={(
          <div className="flex items-center justify-end border-b border-stone-200 px-2 py-1 lg:hidden">
            <button type="button" onClick={() => setTalkOpen(false)} aria-label="会話を閉じる" className="rounded p-1 text-stone-500 hover:bg-stone-100"><X className="h-5 w-5" /></button>
          </div>
        )} />
    </section>
      {!talkOpen ? <div className="lg:hidden"><TalkButton onOpen={() => setTalkOpen(true)} lift={lift} busy={talkBusy} /></div> : null}
    </div>
  );
}
