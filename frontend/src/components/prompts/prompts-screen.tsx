'use client';

// ダンを動かしている指示文を、本人が構成図から辿って読み、そのまま書き直し、前の版に戻す画面（2026-11-17）。
// 上は上から下への構成図（architecture.ts。箱と矢印はコードで確かめた呼び出し順）。箱を押すとその箱が読む指示文の一覧、
// 押すと全文がそのまま出て、その場で書き直せる。誰が読むか・いつ効くか・なぜある文か・履歴は全文の下にたたんである。
// 使う所: /prompts（app/prompts/page.tsx）と、開発室のボードの「指示文」（artifacts/dev-lead）。
// 裏側は app/api/prompts_screen.py、文の置き場所と履歴は app/services/prompt_store.py。
import { useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { ArrowLeft, BookOpen, Cpu, ChevronDown, History, Loader2, Lock, PenLine, RotateCcw, Save, Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';

import { READER_EXAMPLES, readerGroups, ReaderSkills } from './reader-skills';
import { ProgramEditor } from './program-editor';
import { SkillLibrary } from './skill-library';
import { Button } from '@/components/ui/button';
import { SideResizeHandle, useSideWidth } from '@/components/ui/side-resize';
import { ApiError } from '@/lib/api-client';
import { promptsApi, type PromptItem, type PromptSummary, type PromptVersion, type PromptWorking } from '@/lib/prompts-api';
import { cn } from '@/lib/utils';
import { BOARD_NODES, NODES, VIDEO_NODES, type ArchNode } from './architecture';
import { useCall } from '@/components/voice/call-provider';
import { ChangeList, useDevelopmentBoard, TurnDecision, type Turn } from './development-board';
import { ArchBoard } from './arch-board';
import { hostMap, type PlanMark } from '@/lib/map-focus';
import { ConversationCircuit, type TrialControls } from './conversation-circuit';
import type { Trace } from './architecture-trace';
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
const BY_ID = new Map([...NODES, ...BOARD_NODES].map(n => [n.id, n]));
const VIDEO_IDS = new Set(VIDEO_NODES.map(n => n.id));
/** 「動画を作る・直す時」の枝を見ているか（?place=video か、その中の箱） */
export const inVideo = (place: string) => place === 'video' || VIDEO_IDS.has(place);

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
  // 誰が直したか・元の文のままかは札に出さない（2026-11-22 本人「最終更新日時だけ」）。一度も直していない文は札なし
  if (!p.last_at || p.last_by === 'seed') return null;
  return <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-stone-600">最終更新 {when(p.last_at)}</span>;
}

// ---- 全文と書き直し ----
type DanChange = { before: string; beforeSha: string; after: string; note: string; by: string; at?: string };

/** 光らせる行（1から）。editing=ダンが今直している所、changed=ダンが直した所 */
type Lit = { kind: 'editing' | 'changed'; lines: Set<number>; first: number };
const RECENT_MS = 10 * 60_000;

function Editor({ id, pulse, work, onBack, onSaved, onState, onSelection }: {
  id: string;
  /** ダンが今この文のどこを直しているか（別の文・無い時は null） */
  work: PromptWorking | null;
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
  const back = useRef<HTMLDivElement>(null);
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
      const out = await promptsApi.revert(item.id, change.beforeSha, item.sha);
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
      .then(got => {
        if (!live) return;
        setItem(got); setDraft(got.text); setNote(''); setViewing(null);
        // ダンがついさっき直した文を後から開いた時も、直した所を見せる
        const [now, prev] = got.history;
        if (now?.by === 'dan' && prev && Date.now() - new Date(now.at).getTime() < RECENT_MS) {
          setChange({ before: prev.text, beforeSha: prev.sha, after: got.text, note: now.note || '', by: 'dan', at: now.at });
        }
      })
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

  // 光らせる行。ダンが直している間はその行、直した後は変わった行（書き直し始めたら行がずれるので消す）
  const lit = useMemo<Lit | null>(() => {
    if (!item || item.readonly || viewing) return null;
    if (work?.state === 'editing' && work.from && draft === item.text) {
      const lines = new Set<number>();
      for (let n = work.from; n <= (work.to || work.from); n++) lines.add(n);
      return { kind: 'editing', lines, first: work.from };
    }
    if (change && draft === change.after) {
      const lines = new Set<number>();
      for (const r of lineDiff(change.before, change.after)) {
        if (r.kind === 'add') lines.add(r.line);
        else if (r.kind === 'del') lines.add(Math.max(1, r.line));   // 消しただけの所は、その手前の行
      }
      return lines.size ? { kind: 'changed', lines, first: Math.min(...lines) } : null;
    }
    return null;
  }, [item, viewing, work, draft, change]);
  const litKey = lit ? `${lit.kind}:${lit.first}:${lit.lines.size}:${work?.at || change?.at || ''}` : '';
  useEffect(() => {   // 光った所が見える所まで送る
    if (!litKey) return;
    const t = window.setTimeout(() => back.current?.querySelector('[data-lit]')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
    return () => window.clearTimeout(t);
  }, [litKey]);

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
      const out = await promptsApi.revert(item.id, v.sha, item.sha);
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
          {lit?.kind === 'editing' ? (
            <p className="mb-1 flex items-center gap-1.5 rounded-md bg-violet-50 px-2 py-1 text-sm font-semibold text-violet-900" data-testid="dan-working">
              <Sparkles className="h-4 w-4 animate-pulse" />ダンが{work?.from === work?.to ? `${work?.from}行目` : `${work?.from}〜${work?.to}行目`}を直しています{work?.note ? `：${work.note}` : ''}
            </p>
          ) : null}
          <div className="relative rounded-lg bg-white">
          {/* 欄の後ろに同じ組みで全文を置き、光らせる行だけ色を付ける（欄そのものは行ごとに色を付けられない） */}
          <div ref={back} aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words rounded-lg border-2 border-transparent px-3 py-2 text-[14px] leading-relaxed text-transparent">
            {lit ? draft.split('\n').map((line, i) => (
              <div key={i} data-lit={lit.lines.has(i + 1) ? lit.kind : undefined}
                className={lit.lines.has(i + 1) ? (lit.kind === 'editing' ? 'dan-working-line' : 'dan-changed-line') : undefined}>{line || '\u200b'}</div>
            )) : null}
          </div>
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
            className="relative block w-full resize-none overflow-hidden rounded-lg border-2 border-amber-300 bg-transparent px-3 py-2 text-[14px] leading-relaxed text-stone-900 shadow-inner outline-none focus:border-amber-500 focus:ring-4 focus:ring-amber-100"
          />
          </div>
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
// ダンが直している所の光り方（動画・台本のエディターと同じく、今触っている所だけがゆっくり明滅する）
const GLOW_CSS = `
@keyframes dan-working-pulse { 0%, 100% { background-color: rgba(167, 139, 250, 0.22); } 50% { background-color: rgba(167, 139, 250, 0.5); } }
@keyframes dan-working-ring { 0%, 100% { box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.25); } 50% { box-shadow: 0 0 0 7px rgba(139, 92, 246, 0.45); } }
@keyframes dan-changed-fade { 0% { background-color: rgba(52, 211, 153, 0.55); } 100% { background-color: rgba(52, 211, 153, 0.2); } }
.dan-working-line { animation: dan-working-pulse 1.4s ease-in-out infinite; box-shadow: -3px 0 0 #7c3aed; border-radius: 3px; }
.dan-changed-line { animation: dan-changed-fade 2.4s ease-out both; box-shadow: -3px 0 0 #059669; border-radius: 3px; }
.dan-working-glow { animation: dan-working-ring 1.4s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) { .dan-working-line, .dan-working-glow, .dan-changed-line { animation: none; background-color: rgba(167, 139, 250, 0.3); } }
`;
export function PromptsScreen({ place, id, onGo, embedded = false }: {
  place: string; id: string; onGo: (next: { place: string; id?: string }) => void; embedded?: boolean;
}) {
  const [conversation, setConversation] = useState({ room: '', development: false });
  const onRoom = useCallback((room: string, development: boolean) => setConversation({room, development}), []);
  const call = useCall();
  const { setFocus } = call;
  useEffect(() => {
    if (conversation.development) setFocus(conversation.room);
  }, [conversation, setFocus]);
  const board = useDevelopmentBoard(conversation.development);
  const [baseline, setBaseline] = useState<Turn | null>(null);
  const [showLastCall, setShowLastCall] = useState(false);
  const [hiddenActivity, setHiddenActivity] = useState('');
  const [notedBox, setNotedBox] = useState('');
  const [prompts, setPrompts] = useState<PromptSummary[]>([]);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const reader = place.startsWith('reader-') && place.slice(7) in READER_EXAMPLES ? nodeOf(place.slice(7)) : undefined;
  // 「動画を作る・直す時」の枝（2026-11-23）。構成図の箱から降りる図で、中の箱を押すと下に読む文・プログラムが出る
  const video = !reader && inVideo(place);
  const library = !reader && !video && (place === 'skills' || id.startsWith('skill/'));
  const mapTop = useRef<HTMLDivElement>(null);
  const trial = useRef<TrialControls>(null);
  const circuit = useRef<HTMLDivElement>(null);
  const node = reader || (library ? undefined : nodeOf(place));
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
  // ダンが今どの文のどこを直しているか（2026-11-22 本人「編集してる時に編集してる場所を光らせて分かるようにして」）。
  // 画面が見えている間3秒ごとに聞く。直している文は図の箱・一覧・全文の行が光り、ほかを見ていればその文を開く
  const [work, setWork] = useState<PromptWorking | null>(null);
  const [hidWork, setHidWork] = useState('');
  useEffect(() => {
    let live = true;
    let seen: string | null = null;
    const ask = () => {
      if (document.visibilityState !== 'visible') return;
      promptsApi.working()
        .then(w => {
          if (!live) return;
          const key = w.id ? `${w.id}:${w.state}:${w.at}` : '';
          if (key === seen) return;
          const first = seen === null;
          seen = key;
          setWork(w.id ? w : null);
          if (w.state === 'saved' && !first) { setPulse(n => n + 1); setRound(n => n + 1); }   // 開いている文なら新しい版を読みに行く
        })
        .catch(() => undefined);
    };
    ask();
    const t = window.setInterval(ask, 3000);
    return () => { live = false; window.clearInterval(t); };
  }, []);
  const workKey = work ? `${work.id}:${work.state}:${work.at}` : '';
  const workNode = useMemo(() => (work?.id ? NODES.find(n => n.prompts?.includes(work.id!))?.id || '' : ''), [work]);
  const followed = useRef('');
  useEffect(() => {
    if (!work?.id || followed.current === workKey) return;
    followed.current = workKey;
    if (work.state === 'editing' && work.id !== id && !draftDiff) onGo({ place: workNode || place, id: work.id });   // 書きかけが無ければ、その文を開いて見せる
  }, [work, workKey, id, draftDiff, onGo, workNode, place]);
  const elsewhere = work?.id && work.id !== id && hidWork !== workKey ? work : null;
  // 選んだ箱・文を外す（2026-11-22 本人「選択解除できないから、関係ない所を押したり札の×で外せるように」）。
  // 保存していない書きかけがある時は、文を閉じると書きかけが消えるので、確かめてから閉じる
  const clearPick = useCallback(() => {
    if (!place && !id) return;
    if (draftDiff && !window.confirm('保存していない書きかけがあります。閉じると消えます。閉じますか？')) return;
    setPicked({ id: '', sel: null, cursor: null });
    onGo({ place: '' });
  }, [place, id, draftDiff, onGo, library, video]);
  // 左の余白を押した時だけ外す。押せる物・全文の欄・文字をなぞって選んでいる最中は外さない
  const onBlank = useCallback((e: ReactMouseEvent) => {
    if ((!place || library || place === 'video') && !id) return;
    const t = e.target as HTMLElement;
    if (t.closest('[data-freeboard], dialog, button, a, input, textarea, select, summary, label, [role="button"], main, details')) return;
    if (window.getSelection()?.toString()) return;
    if (draftDiff) { setPicked(v => ({ ...v, sel: null })); return; }   // 書きかけは消さない。選んだ行だけ外す
    clearPick();
  }, [place, id, draftDiff, clearPick, library]);
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
  const family = reader && id ? skills.filter(p => p.id.split('/')[1] === id.split('/')[1]) : [];
  const groups = useMemo(() => reader ? readerGroups(reader.id, skills) : [], [reader, skills]);
  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const n of [...NODES, ...VIDEO_NODES]) out[n.id] = (n.prompts || []).filter(pid => byId.has(pid)).length;
    return out;
  }, [byId]);
  // どの箱にも入っていない文（台帳に足されたのに図に無い物）も、失くさず下に出す
  const loose = useMemo(() => {
    const placed = new Set([...NODES, ...VIDEO_NODES].flatMap(n => n.prompts || []));
    return prompts.filter(p => !p.id.startsWith('skill/') && !placed.has(p.id));
  }, [prompts]);

  const here = (node?.prompts || []).map(pid => byId.get(pid)).filter((p): p is PromptSummary => !!p);
  const parameters = here.filter(p => p.kind === 'probability' || p.kind === 'jev_model');
  const editable = here.filter(p => !p.readonly && !parameters.includes(p));
  const readonly = here.filter(p => p.readonly);
  // 読む文が無く、プログラムと動き方だけの箱（動画の枝の道具など）は、右の全文の枠を出さずに横いっぱいに出す
  const progOnly = !!node && !here.length && !!(node.programs?.length || node.facts?.length);

  useEffect(() => {   // 狭い画面では、選んだ物の所まで送る
    if (reader && !id) { mapTop.current?.scrollIntoView({ block: 'start' }); return; }
    if (video && !id) { if (place !== 'video') list.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); return; }
    if (typeof window === 'undefined' || (!reader && !library && window.innerWidth >= 1280)) return;
    if (library && !id) return;
    const target = id ? detail.current : place ? list.current : null;
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [id, place, library, reader, video]);

  // チャットの直す案（部品 MapPlan）: 番号を地図に出し、案のカードを押すとその箱を開く（lib/map-focus.ts）
  const [planMarks, setPlanMarks] = useState<PlanMark[]>([]);
  const navigateRef = useRef<(next: { place: string; id?: string }) => boolean>(() => false);
  useEffect(() => hostMap({ focus: node => { navigateRef.current({ place: node }); }, plan: setPlanMarks }), []);

  const navigate = (next: { place: string; id?: string }) => {
    if (shown && open.draft !== shown.text && next.id !== id &&
      !window.confirm('保存していない書きかけがあります。閉じますか？')) return false;
    onGo(next);
    return true;
  };
  useLayoutEffect(() => { navigateRef.current = navigate; });

  // 構成図のボード。いつもの時は左の欄いっぱい、依頼の流れを再生する時はその枠の中で決まった高さ
  const showingCall = (!notedBox && !!board.session) || (showLastCall && board.turns.length > 0);
  const lastChange = board.changes[0];
  const activityNode = showingCall ? 'router' : notedBox || lastChange?.node || '';
  const changesHere = board.changes.filter(change => change.node === activityNode);
  const activityKey = showingCall ? 'voice/'+board.session : activityNode+'/'+(changesHere[0]?.id || '');
  const showActivity = !place && !id && activityNode && hiddenActivity !== activityKey;
  const renderDiagram = (trace?: Trace) => <div className={trace ? 'h-[min(70dvh,760px)]' : 'absolute inset-0'}>
    <ArchBoard trace={trace}
      annotation={!trace && showActivity ? {
        node: activityNode,
        title: showingCall ? 'Jevの判断' : (BY_ID.get(activityNode)?.name || activityNode) + 'の変更',
        body: showingCall ? <TurnDecision baseline={baseline} setBaseline={setBaseline} key={board.session || 'previous'} turns={board.turns} live={!!board.session} />
          : <ChangeList changes={changesHere} />,
        close: () => setHiddenActivity(activityKey),
        open: () => navigate({place: activityNode}),
      } : undefined} skills={skills} onSkills={(name, pid) => navigate({ place: 'reader-' + name, id: pid })} counts={counts}
      active={place === 'video' ? 'v-owner' : library ? 'skills' : node?.id || ''} glow={work?.state === 'editing' ? workNode : ''} marks={planMarks}
      onPick={p => { navigate({ place: p }); }}
      toolbar={<>
      {conversation.development && <button type="button" aria-label={call.room ? '通話を切る' : '指示文の見直しで通話する'}
        className="rounded-md border border-teal-800 bg-teal-800 px-3 py-1.5 text-xs font-semibold text-white"
        onClick={() => call.room ? call.end() : call.start(conversation.room, {chatTitle:'指示文の見直し'})}>{call.room ? '通話を切る' : '通話する'}</button>}
      {!trace && (lastChange || board.session || board.turns.length > 0) && <select aria-label="構成図に表示する変更や判断"
        className="max-w-36 rounded-md border bg-white px-1 py-1.5 text-xs" value="" onChange={e => {
          const value = e.target.value;
          if (!value || !navigate({place:''})) return;
          setNotedBox(value === 'call' ? '' : value);
          setShowLastCall(value === 'call'); setHiddenActivity('');
        }}>
        <option value="">変更・判断を見る</option>
        {(board.session || board.turns.length > 0) && <option value="call">通話の判断</option>}
        {[...new Set(board.changes.map(c => c.node))].map(key => <option key={key} value={key}>{BY_ID.get(key)?.name || key}の変更</option>)}
      </select>}
      <button type="button"  className="inline-flex h-8 items-center gap-1 rounded-md border border-stone-300 bg-white/95 px-2 text-xs font-semibold text-stone-800 shadow-sm hover:bg-stone-100" onClick={() => navigate({ place: 'skills' })}><BookOpen size={13} />スキルを探す</button></>} />
  </div>;

  const row = (p: PromptSummary) => (
    <li key={p.id}>
      <button type="button" onClick={() => navigate({ place, id: p.id })}
        className={cn('w-full rounded-lg border px-3 py-2 text-left transition hover:border-amber-400 hover:bg-amber-50',
          p.id === id ? 'border-amber-500 bg-amber-50' : 'border-stone-200 bg-white',
          work?.state === 'editing' && work.id === p.id && 'dan-working-glow border-violet-500')}>
        <div className="text-sm font-semibold leading-snug text-stone-900">{p.title}{p.value && <span className="ml-2 font-mono text-teal-800">{p.value}</span>}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {work?.state === 'editing' && work.id === p.id
            ? <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-semibold text-violet-900"><Sparkles className="h-3 w-3 animate-pulse" />ダンが直しています</span>
            : <StateBadge p={p} />}
          {p.chars ? <span className="text-[11px] text-stone-400">{p.chars.toLocaleString()}字</span> : null}
        </div>
      </button>
    </li>
  );

  return (
    <div className="lg:flex lg:h-full lg:min-h-0">
    <style>{GLOW_CSS}</style>
    {/* 左: 図・一覧・全文。PC はここだけがスクロールする */}
    {/* 左: 構成図のボードが欄いっぱい（2026-11-24 本人「表示領域を最大限でかく」。題と下の隙間を外した）。選んだ箱の中身はボードの上に下から重ねる */}
    <div className="relative flex min-h-0 flex-col gap-1.5 p-1.5 lg:min-w-0 lg:flex-1" onClick={onBlank} data-prompts-left>
      {error ? (
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {error} <a className="underline" href="/login?redirect=/prompts" target="_top">ログインする</a>
        </p>
      ) : null}
      {elsewhere ? (
        <div className="sticky top-0 z-20 flex items-center gap-2 rounded-lg border border-violet-300 bg-violet-50 px-3 py-2 text-sm text-violet-950 shadow" data-testid="dan-working-elsewhere">
          <Sparkles className={cn('h-4 w-4 shrink-0', elsewhere.state === 'editing' && 'animate-pulse')} />
          <span className="min-w-0 flex-1">ダンが「{elsewhere.title}」を{elsewhere.state === 'editing' ? '直しています' : '直しました'}</span>
          <Button size="sm" variant="outline" onClick={() => navigate({ place: workNode || place, id: elsewhere.id! })} className="h-8 border-violet-300 bg-white px-2 text-violet-900 hover:bg-violet-100">開く</Button>
          <button type="button" aria-label="閉じる" onClick={() => setHidWork(workKey)} className="rounded p-1 text-violet-800 hover:bg-violet-100"><X className="h-4 w-4" /></button>
        </div>
      ) : null}
      {board.error && <p role="status" className="text-xs text-amber-800">{board.error}</p>}
      <div ref={circuit} className="flex min-h-[calc(100dvh-12px)] flex-1 flex-col lg:min-h-0"><ConversationCircuit controls={trial} visible onEdit={p => { if (navigate({place:p})) requestAnimationFrame(() => list.current?.scrollIntoView({block:"start"})); }} renderDiagram={renderDiagram}
        onPrompt={(pid, source) => {
          const owner = NODES.find(n => n.id === source && n.prompts?.includes(pid)) || NODES.find(n => n.prompts?.includes(pid));
          navigate({place: pid.startsWith('skill/') ? 'skills' : owner?.id || source, id: pid});
        }} /></div>


      {(place || id) && <section aria-label="選んだ場所の中身" className="absolute inset-x-1.5 bottom-1.5 z-30 max-h-[50%] overflow-auto overscroll-contain rounded-xl border border-stone-300 bg-white p-3 shadow-lg">
      <div className="sticky top-0 z-10 mb-2 flex justify-end gap-2 bg-white">
        {(node || id) && <button disabled={!!draftDiff} className="rounded border px-3 py-1 text-xs disabled:opacity-50" onClick={() => {
          const channel = node?.id === 'editor' || node?.id === 'editor-ui' ? 'editor' : id.startsWith('call/') || ['voice','router','audio','stage','lookup','backend','pin'].includes(node?.id || '') ? 'voice' : 'chat';
          if (navigate({place:''})) { trial.current?.open(channel); circuit.current?.scrollIntoView({block:'start'}); }
        }}>保存した指示文で依頼を試す</button>}
        <button className="rounded border px-3 py-1 text-xs" onClick={() => navigate({place:''})}>中身を閉じる</button></div>
      {reader && <div ref={mapTop}>{id
        ? <div className="flex flex-wrap items-center justify-between gap-2">
            <button type="button" onClick={() => navigate({ place })} className="inline-flex items-center gap-1 text-sm text-teal-800 hover:underline"><ArrowLeft size={16} />{reader.name}のスキルに戻る</button>
            {family.length > 1 && <label className="flex min-w-0 max-w-full items-center gap-2 text-xs text-stone-600">
              <span className="shrink-0">手順書・参考ページ</span>
              <select className="min-w-0 max-w-64 rounded-md border bg-white px-2 py-1.5 text-sm" value={id} onChange={e => navigate({place, id:e.target.value})}>
                {family.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}
              </select></label>}
          </div>
        : <ReaderSkills node={reader} groups={groups} onBack={() => navigate({place: ''})} onPick={pid => navigate({place, id:pid})} />}</div>}
      {(!reader || id) && !(place === 'video' && !id) && <div className={cn('grid items-start gap-4', id && !reader && 'xl:grid-cols-[minmax(0,280px)_minmax(0,1fr)]')}>
        {!reader && <aside ref={list} className={cn('scroll-mt-2 space-y-3', id && 'hidden xl:block', (library || progOnly) && !id && 'xl:col-span-2')}>
          {library ? <SkillLibrary pages={skills} selected={id} loaded={loaded} onPick={pid => navigate({ place: 'skills', id: pid })} /> : <>
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
          {node && <ChangeList changes={board.changes.filter(c => c.node === node.id)} />}
          {node?.id === 'router' && (board.session || board.turns.length > 0) && <TurnDecision baseline={baseline} setBaseline={setBaseline} turns={board.turns} live={!!board.session} />}
          {node?.facts?.length ? <ul className="list-disc space-y-1 pl-5 text-sm text-stone-700" data-testid="node-facts">{node.facts.map(f => <li key={f}>{f}</li>)}</ul> : null}
          {parameters.length > 0 && <section><h3 className="mb-1 text-sm font-semibold">動作の設定</h3><ul className="space-y-1">{parameters.map(row)}</ul></section>}
          {editable.length ? <ul className="space-y-2">{editable.map(row)}</ul> : null}
          {readonly.length ? (
            <details open={!editable.length}>
              <summary className="cursor-pointer text-sm text-stone-600">まだプログラムの中にある文（読むだけ・{readonly.length}）</summary>
              <ul className="mt-2 space-y-2">{readonly.map(row)}</ul>
            </details>
          ) : null}
          {node?.programs?.length ? (
            <div className="space-y-1.5" data-testid="node-programs">
              <h3 className="flex items-center gap-1 text-sm font-semibold text-sky-900"><Cpu className="h-4 w-4" />ここで動くプログラム</h3>
              <ul className="space-y-1.5">{node.programs.map(pr => <li key={pr.path} className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2">
                <div className="break-all font-mono text-[12px] text-sky-900">{pr.path}</div>
                <div className="text-sm text-stone-700">{pr.what}</div>
              </li>)}</ul>
            </div>
          ) : null}
          {node && <ProgramEditor key={node.id} node={node.id} onChat={() => { if (window.innerWidth < 1024) setTalkOpen(true); }} />}
          {node?.same ? (
            <p className="text-sm text-stone-600">
              ここは「<button type="button" className="font-semibold text-amber-800 underline" onClick={() => onGo({ place: node.same! })}>{BY_ID.get(node.same)?.name}</button>」と同じ決まりも読みます。
            </p>
          ) : null}
          {node && node.id in READER_EXAMPLES && <button className="text-sm font-semibold text-teal-800 underline" type="button" onClick={() => navigate({ place: 'reader-' + node.id })}>{node.name}が読むスキルを開く</button>}
          {node && !here.length && !node.same && loaded && !error ? (
            <p className="text-sm text-stone-500">ここはプログラムだけで動いていて、モデルが読む指示文はありません。</p>
          ) : null}
          {loose.length ? (
            <details>
              <summary className="cursor-pointer text-xs text-stone-500">図のどの箱にもまだ入れていない文（{loose.length}）</summary>
              <ul className="mt-2 space-y-2">{loose.map(row)}</ul>
            </details>
          ) : null}
          </>}
        </aside>}
        <main ref={detail} className={cn('min-w-0 scroll-mt-2 rounded-xl border border-stone-200 bg-white p-3 sm:p-4', !id && 'hidden')}>
          {id ? (
            <Editor key={id} id={id} pulse={pulse} work={work?.id === id ? work : null} onBack={() => navigate({ place: library ? 'skills' : place })} onSaved={load} onState={onState} onSelection={onSelection} />
          ) : (
            <p className="text-sm text-stone-500">{library ? '手順書か参考ページを選ぶと、ここで編集できます。' : '左の一覧から文を選ぶと、ここに全文がそのまま出ます。'}</p>
          )}
        </main>
      </div>}
      </section>}
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
      <PromptsChat ctx={talkCtx} onRoom={onRoom} onPulse={bump} onBusy={setTalkBusy} onClearSelection={() => setPicked(v => ({ ...v, sel: null }))} onClearPick={clearPick}
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
