'use client';

// ダンを動かしている指示文を、本人が「どこで働いている文か」から辿って読み、直し、前の版に戻す画面（2026-11-17）。
// 上は家の断面の絵（場所ごとに押せる）。押すとその場所の指示文の一覧、押すと全文と履歴。
// 裏側は app/api/prompts_screen.py、文の置き場所と履歴は app/services/prompt_store.py。
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, History, Loader2, Lock, RotateCcw, Save } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api-client';
import { promptsApi, type PromptItem, type PromptPlace, type PromptSummary, type PromptVersion } from '@/lib/prompts-api';
import { cn } from '@/lib/utils';

// 絵（public/prompts/dan-house.jpg）の中で、それぞれの場所がある所（横・縦の%）。
const SPOTS: Record<string, { x: number; y: number }> = {
  owner: { x: 12, y: 74 },
  voice: { x: 25, y: 60 },
  router: { x: 49, y: 62 },
  backend: { x: 65, y: 70 },
  lookup: { x: 20, y: 31 },
  stage: { x: 42, y: 26 },
  work: { x: 64, y: 30 },
  editor: { x: 80, y: 33 },
  chat: { x: 91, y: 62 },
};

const WHO: Record<string, string> = { owner: 'みきさん', dan: 'ダン', seed: '元の文' };

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

function StateBadge({ p }: { p: PromptSummary }) {
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

function House({ places, counts, active, onPick }: {
  places: PromptPlace[]; counts: Record<string, number>; active: string; onPick: (id: string) => void;
}) {
  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-stone-200 bg-stone-100 shadow-sm">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/prompts/dan-house.jpg" alt="ダンの中の場所" className="block w-full select-none" draggable={false} />
      {places.map(place => {
        const spot = SPOTS[place.id];
        if (!spot) return null;
        const on = place.id === active;
        return (
          <button
            key={place.id}
            type="button"
            onClick={() => onPick(place.id)}
            style={{ left: `${spot.x}%`, top: `${spot.y}%` }}
            className={cn(
              'absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold shadow-md transition sm:px-3 sm:py-1 sm:text-sm',
              on ? 'border-amber-500 bg-amber-400 text-stone-900 ring-4 ring-amber-300/60'
                : 'border-white/80 bg-white/90 text-stone-800 hover:bg-amber-100',
            )}
          >
            {place.name}
            {counts[place.id] ? <span className="ml-1 font-normal text-stone-500">{counts[place.id]}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

function Editor({ id, onBack, onSaved }: { id: string; onBack: () => void; onSaved: () => void }) {
  const [item, setItem] = useState<PromptItem | null>(null);
  const [draft, setDraft] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [viewing, setViewing] = useState<PromptVersion | null>(null);

  const load = useCallback(async () => {
    setError('');
    try {
      const got = await promptsApi.item(id);
      setItem(got); setDraft(got.text); setNote(''); setViewing(null);
    } catch (err) { setError(errorText(err)); }
  }, [id]);

  useEffect(() => { setItem(null); void load(); }, [load]);

  const changed = item ? draft !== item.text : false;

  async function save() {
    if (!item) return;
    setBusy(true); setError('');
    try {
      const out = await promptsApi.save(item.id, draft, note, item.sha);
      setItem(out.item); setDraft(out.item.text); setNote(''); setViewing(null);
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

  return (
    <div className="space-y-4">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm text-stone-500 hover:text-stone-800 lg:hidden">
        <ArrowLeft className="h-4 w-4" />一覧に戻る
      </button>
      <div>
        <h2 className="text-lg font-bold leading-snug text-stone-900">{item.title}</h2>
        <div className="mt-1"><StateBadge p={{ ...item, last_by: item.history[0]?.by, last_at: item.history[0]?.at }} /></div>
      </div>
      <dl className="grid gap-x-4 gap-y-1 rounded-lg bg-stone-50 p-3 text-sm sm:grid-cols-[7em_1fr]">
        <dt className="text-stone-500">誰が読むか</dt><dd className="text-stone-800">{item.reader}</dd>
        <dt className="text-stone-500">いつ効くか</dt><dd className="text-stone-800">{item.when}</dd>
        <dt className="text-stone-500">なぜある文か</dt><dd className="text-stone-800">{item.why}</dd>
        <dt className="text-stone-500">元の場所</dt><dd className="break-all font-mono text-xs text-stone-500">{item.source}</dd>
      </dl>

      {item.kind === 'sections' && !item.readonly ? (
        <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">「## 名前」の行は、プログラムがその名前で選ぶ印です。見出しの行は変えずに、その下の文を直してください。</p>
      ) : null}
      {item.kind === 'words' && !item.readonly ? (
        <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">1行に1つの言葉です。行を足すと、その言葉でも作業が起きるようになります。</p>
      ) : null}
      {item.marks?.length ? (
        <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">
          {item.marks.map(m => `{${m}} には${item.mark_notes?.[m] || '値'}が入ります`).join('。')}。この印は消さないでください。
        </p>
      ) : null}

      {viewing ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">{when(viewing.at)} の版（{WHO[viewing.by] || viewing.by}）</span>
            <Button size="sm" variant="outline" onClick={() => setViewing(null)}>今の文に戻る</Button>
            {!item.readonly && viewing.sha !== item.sha ? (
              <Button size="sm" onClick={() => void revert(viewing)} disabled={busy}><RotateCcw className="mr-1 h-4 w-4" />この版に戻す</Button>
            ) : null}
          </div>
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md border bg-stone-50 p-3 text-[13px] leading-relaxed text-stone-800">{viewing.text}</pre>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-stone-500">
            <span>全文（{draft.length.toLocaleString()}字）</span>
            {changed ? <span className="text-amber-700">直した所は、まだ保存していません</span> : null}
          </div>
          <Textarea
            value={draft}
            onChange={e => setDraft(e.target.value)}
            readOnly={item.readonly}
            spellCheck={false}
            className={cn('min-h-[45vh] font-[inherit] text-[13px] leading-relaxed', item.readonly && 'bg-stone-50')}
          />
          {item.readonly ? (
            <p className="text-xs text-stone-500">この文はまだプログラムの中にあるので、ここでは読むだけです。直したい時はダンに言ってください。この画面で直せる形に移します。</p>
          ) : (
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder="なぜ直したか（履歴に残ります。空でも保存できます）"
                className="h-9 flex-1 rounded-md border border-input bg-transparent px-3 text-sm"
              />
              <div className="flex gap-2">
                <Button variant="outline" disabled={!changed || busy} onClick={() => setDraft(item.text)}>元に戻す</Button>
                <Button disabled={!changed || busy} onClick={() => void save()}>
                  {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}保存
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
      {error ? <p className="rounded-md bg-rose-50 p-2 text-sm text-rose-800">{error}</p> : null}

      {item.history.length ? (
        <section>
          <h3 className="mb-1 flex items-center gap-1 text-sm font-semibold text-stone-700"><History className="h-4 w-4" />この画面での履歴</h3>
          <ul className="divide-y rounded-md border text-sm">
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
        </section>
      ) : null}

      {item.code_history?.length ? (
        <section>
          <h3 className="mb-1 text-sm font-semibold text-stone-700">プログラムの中にあった頃に直された日（{item.code_history.length}回）</h3>
          <ul className="space-y-0.5 text-xs text-stone-600">
            {item.code_history.map((h, i) => (
              <li key={`${h.date}-${i}`}><span className="tabular-nums text-stone-400">{h.date}</span> {h.what || '（直した理由の記録なし）'}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function PromptsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [places, setPlaces] = useState<PromptPlace[]>([]);
  const [prompts, setPrompts] = useState<PromptSummary[]>([]);
  const [error, setError] = useState('');
  const place = params.get('place') || 'voice';
  const id = params.get('id') || '';

  const load = useCallback(async () => {
    try {
      const data = await promptsApi.list();
      setPlaces(data.places); setPrompts(data.prompts); setError('');
    } catch (err) { setError(errorText(err)); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const p of prompts) out[p.place] = (out[p.place] || 0) + 1;
    return out;
  }, [prompts]);
  const here = prompts.filter(p => p.place === place);
  const editable = here.filter(p => !p.readonly);
  const readonly = here.filter(p => p.readonly);
  const current = places.find(p => p.id === place);

  const go = (next: { place?: string; id?: string }) => {
    const q = new URLSearchParams();
    q.set('place', next.place ?? place);
    if (next.id) q.set('id', next.id);
    router.replace(`/prompts?${q.toString()}`, { scroll: false });
  };

  const row = (p: PromptSummary) => (
    <li key={p.id}>
      <button
        type="button"
        onClick={() => go({ id: p.id })}
        className={cn('w-full rounded-lg border px-3 py-2 text-left transition hover:border-amber-400 hover:bg-amber-50',
          p.id === id ? 'border-amber-500 bg-amber-50' : 'border-stone-200 bg-white')}
      >
        <div className="text-sm font-semibold leading-snug text-stone-900">{p.title}</div>
        <div className="mt-0.5 text-xs text-stone-500">{p.reader}・{p.when}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <StateBadge p={p} />
          {p.chars ? <span className="text-[11px] text-stone-400">{p.chars.toLocaleString()}字</span> : null}
        </div>
      </button>
    </li>
  );

  return (
    <div className="min-h-screen bg-[#faf8f4] text-stone-900">
      <div className="mx-auto max-w-7xl space-y-4 px-3 py-4 sm:px-6">
        <header>
          <h1 className="text-xl font-bold">ダンを動かしている指示文</h1>
          <p className="text-sm text-stone-600">絵の場所を押すと、そこで働いている係が読む文が出ます。直して保存すると、次にその文が読まれる時から効きます。前の版にはいつでも戻せます。</p>
        </header>
        {error ? (
          <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-800">
            {error} <a className="underline" href="/login?redirect=/prompts">ログインする</a>
          </p>
        ) : null}
        <House places={places} counts={counts} active={place} onPick={p => go({ place: p })} />

        <div className="grid gap-4 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
          <aside className={cn('space-y-3', id && 'hidden lg:block')}>
            {current ? (
              <div>
                <h2 className="text-lg font-bold">{current.name}</h2>
                <p className="text-sm text-stone-600">{current.line}</p>
              </div>
            ) : null}
            {editable.length ? <ul className="space-y-2">{editable.map(row)}</ul> : null}
            {readonly.length ? (
              <details open={!editable.length} className="rounded-lg">
                <summary className="cursor-pointer text-sm text-stone-600">まだプログラムの中にある文（読むだけ・{readonly.length}）</summary>
                <ul className="mt-2 space-y-2">{readonly.map(row)}</ul>
              </details>
            ) : null}
            {!here.length && !error ? (
              <p className="text-sm text-stone-500">{place === 'owner' ? 'ここはみきさん自身です。ダンが読む指示文はありません。' : '読んでいます…'}</p>
            ) : null}
          </aside>
          <main className={cn('min-w-0 rounded-xl border border-stone-200 bg-white p-4', !id && 'hidden lg:block')}>
            {id ? (
              <Editor id={id} onBack={() => go({})} onSaved={() => void load()} />
            ) : (
              <p className="text-sm text-stone-500">左の一覧から文を選ぶと、ここに全文が出ます。</p>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

export default function PromptsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-stone-500">読んでいます…</div>}>
      <PromptsInner />
    </Suspense>
  );
}
