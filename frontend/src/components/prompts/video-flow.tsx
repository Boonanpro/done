'use client';

// 動画を編集する作業の図（指示文の画面の「動画の編集」）。2026-11-23 本人「お前がこうやって直しても良い？って聞いて来ても
// どこをどう変えようとしてるのかが分からないので、良し悪しの判断もできず承認も却下もできない」「あらゆる場面で何が起きているかを
// ちゃんと理解したい。そうすればどこに何を足したり引いたりすればどうなるかっていう検証を回していける」。
// 段ごとに、ダンが読む手順書の文（今の版から抜き出す）と使うプログラム。過去の作業を選ぶと、段ごとに何をしたかと出来たコマ。
// ダンの直しの案は「どの段の・どの文を・こう変える」と前後のコマで出し、本人は承認か却下を押すだけ（文の案は承認でその場で保存）。
// 裏側は app/services/video_flow.py、段の定義は app/prompts/video_flow.json、ダンが載せるのは scripts/video_flow.py。
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowDown, Check, CircleAlert, Clapperboard, Cpu, FileText, Loader2, PenLine, X } from 'lucide-react';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api-client';
import { promptsChat, videoFlowApi, type VideoFlow, type VideoFlowFrame, type VideoFlowProposal, type VideoFlowRun, type VideoFlowStage } from '@/lib/prompts-api';
import { cn } from '@/lib/utils';

const STATE: Record<string, { label: string; box: string; tag: string }> = {
  ok: { label: '手順どおり', box: 'border-emerald-500 bg-emerald-50', tag: 'bg-emerald-600 text-white' },
  bad: { label: 'ここで崩れた', box: 'border-rose-500 bg-rose-50', tag: 'bg-rose-600 text-white' },
  skipped: { label: '飛ばした', box: 'border-amber-500 bg-amber-50', tag: 'bg-amber-500 text-white' },
  na: { label: 'この作業では無し', box: 'border-stone-300 bg-stone-50', tag: 'bg-stone-400 text-white' },
};

const reason = (e: unknown) => e instanceof ApiError ? String((e.data as { detail?: string })?.detail || '読み込めませんでした。') : e instanceof Error ? e.message : '読み込めませんでした。';

function Frames({ frames, onZoom }: { frames: VideoFlowFrame[]; onZoom: (f: VideoFlowFrame) => void }) {
  if (!frames.length) return null;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {frames.map((f, i) => (
        <button key={i} type="button" onClick={() => onZoom(f)} className="group min-w-0 text-left">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={f.src} alt={f.label || f.time} className="aspect-video w-full rounded-md border border-stone-200 object-cover group-hover:ring-2 group-hover:ring-amber-400" />
          <span className="mt-0.5 block text-[11px] leading-tight text-stone-600"><b>{f.time}</b>{f.label ? ` ${f.label}` : ''}</span>
        </button>
      ))}
    </div>
  );
}

function ReadText({ text }: { text: string }) {
  return <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-stone-50 p-2 font-sans text-[13px] leading-relaxed text-stone-800">{text}</pre>;
}

function StageDetail({ stage, run, onOpen, onZoom }: { stage: VideoFlowStage; run?: VideoFlowRun; onOpen: (id: string) => void; onZoom: (f: VideoFlowFrame) => void }) {
  const did = run?.stages[stage.id];
  return (
    <div className="space-y-4" data-testid="video-flow-detail">
      <div>
        <h3 className="text-lg font-bold">{stage.name}</h3>
        <p className="text-sm text-stone-700">{stage.line}</p>
      </div>
      {did ? (
        <section className={cn('space-y-2 rounded-lg border-2 p-3', STATE[did.state]?.box)}>
          <div className="flex items-center gap-2 text-sm font-bold"><span className={cn('rounded px-2 py-0.5 text-xs', STATE[did.state]?.tag)}>{STATE[did.state]?.label}</span>「{run!.title}」でしたこと</div>
          {did.did && <p className="whitespace-pre-wrap text-sm text-stone-900">{did.did}</p>}
          {did.should && <p className="whitespace-pre-wrap text-sm text-stone-600"><b>本来は:</b> {did.should}</p>}
          <Frames frames={did.frames} onZoom={onZoom} />
        </section>
      ) : null}
      <section className="space-y-2">
        <h4 className="flex items-center gap-1.5 text-sm font-bold"><FileText className="size-4" />この段でダンが読む文（{stage.reads.length}）</h4>
        <p className="text-xs text-stone-500">手順書の今の版から、そのまま抜き出しています。直すとここも変わります。</p>
        {stage.reads.map((r, i) => (
          <details key={i} className="rounded-lg border border-stone-200 bg-white p-2" open={i === 0}>
            <summary className="cursor-pointer text-sm">
              <b>{r.title}</b>{r.heading ? <span className="text-stone-600"> ／ {r.heading.replace(/^#+\s*/, '')}</span> : <span className="text-stone-600"> ／ 全部</span>}
              {r.why ? <span className="ml-1 text-xs text-stone-500">（{r.why}）</span> : null}
              {r.case ? <span className="ml-1 rounded bg-sky-100 px-1.5 text-[11px] text-sky-900">案件の決まり</span> : null}
              {!r.found ? <span className="ml-1 rounded bg-rose-100 px-1.5 text-[11px] text-rose-900">この見出しが見つかりません</span> : null}
            </summary>
            {r.found ? <div className="mt-2 space-y-2"><ReadText text={r.whole && r.text.length > 4000 ? r.text.slice(0, 4000) + '\n…' : r.text} />
              <button type="button" onClick={() => onOpen(r.id)} className="inline-flex items-center gap-1 text-sm font-semibold text-teal-800 hover:underline"><PenLine className="size-3.5" />この手順書を開いて直す</button></div> : null}
          </details>
        ))}
      </section>
      <section className="space-y-2">
        <h4 className="flex items-center gap-1.5 text-sm font-bold"><Cpu className="size-4" />この段で使うプログラム</h4>
        <ul className="space-y-1">
          {stage.programs.map(p => (
            <li key={p.path} className="rounded-lg border border-stone-200 bg-white p-2 text-sm">
              <code className="text-[12px] text-stone-500">{p.path}</code>{!p.exists && <span className="ml-1 text-xs text-rose-700">（見つかりません）</span>}
              <p className="text-stone-800">{p.what}</p>
            </li>
          ))}
        </ul>
        {stage.gap ? <p className="flex gap-1.5 rounded-lg bg-amber-50 p-2 text-sm text-amber-950"><CircleAlert className="mt-0.5 size-4 shrink-0" />{stage.gap}</p> : null}
        {stage.trial ? <p className="rounded-lg bg-stone-100 p-2 text-sm text-stone-700">{stage.trial}</p> : null}
      </section>
    </div>
  );
}

function Proposal({ p, stage, onDecide, busy, onOpen, onZoom }: { p: VideoFlowProposal; stage?: VideoFlowStage; busy: boolean; onDecide: (p: VideoFlowProposal, d: 'approve' | 'reject') => void; onOpen: (id: string) => void; onZoom: (f: VideoFlowFrame) => void }) {
  const pending = p.state === 'pending';
  return (
    <article className={cn('space-y-3 rounded-xl border-2 bg-white p-3', pending ? 'border-violet-400' : 'border-stone-200 opacity-80')} data-testid="video-flow-proposal">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-900">{stage?.name || p.stage}</span>
        <span className="rounded bg-stone-100 px-2 py-0.5 text-xs text-stone-700">{p.kind === 'text' ? '手順書の文を変える' : '作業（プログラムなど）を足す'}</span>
        {!pending && <span className={cn('rounded px-2 py-0.5 text-xs font-semibold', p.state === 'approved' ? 'bg-emerald-600 text-white' : 'bg-stone-500 text-white')}>{p.state === 'approved' ? '承認済み' : '却下'}</span>}
      </div>
      <h4 className="font-bold leading-snug">{p.title}</h4>
      {p.why ? <p className="whitespace-pre-wrap text-sm text-stone-800"><b>なぜ:</b> {p.why}</p> : null}
      {p.effect ? <p className="whitespace-pre-wrap text-sm text-stone-800"><b>変わること:</b> {p.effect}</p> : null}
      {p.kind === 'text' ? (
        <div className="space-y-1 text-sm">
          <button type="button" onClick={() => onOpen(p.prompt_id)} className="text-xs font-semibold text-teal-800 hover:underline">{p.prompt_id.replace(/^skill\//, '')} を開く</button>
          <div className="rounded-md border border-rose-200 bg-rose-50 p-2"><span className="text-[11px] font-semibold text-rose-800">今の文</span><p className="whitespace-pre-wrap text-rose-950 line-through decoration-rose-400">{p.find}</p></div>
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-2"><span className="text-[11px] font-semibold text-emerald-800">直した後</span><p className="whitespace-pre-wrap text-emerald-950">{p.replace || '（この文を消す）'}</p></div>
          {pending && p.applies === false && <p className="text-xs text-rose-700">案を出した後にこの文が直されたので、このままでは承認できません。</p>}
        </div>
      ) : null}
      {(p.before.frames.length || p.after.frames.length) ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {[p.before, p.after].map((side, i) => side.frames.length ? (
            <div key={i} className="space-y-1">
              <div className={cn('text-xs font-bold', i === 0 ? 'text-rose-800' : 'text-emerald-800')}>{side.label || (i === 0 ? '今' : '直した後')}</div>
              <Frames frames={side.frames} onZoom={onZoom} />
            </div>
          ) : null)}
        </div>
      ) : null}
      {pending ? (
        <div className="flex gap-2">
          <button type="button" disabled={busy || (p.kind === 'text' && p.applies === false)} onClick={() => onDecide(p, 'approve')}
            className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"><Check className="size-4" />承認</button>
          <button type="button" disabled={busy} onClick={() => onDecide(p, 'reject')}
            className="inline-flex items-center gap-1 rounded-lg border border-stone-300 bg-white px-4 py-2 text-sm font-semibold text-stone-700 hover:bg-stone-100 disabled:opacity-40"><X className="size-4" />却下</button>
        </div>
      ) : null}
    </article>
  );
}

export function VideoFlowView({ onOpenPrompt }: { onOpenPrompt: (id: string) => void }) {
  const [data, setData] = useState<VideoFlow | null>(null);
  const [error, setError] = useState('');
  const [caseId, setCaseId] = useState('');
  const [runId, setRunId] = useState('');
  const [stageId, setStageId] = useState('');
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState<VideoFlowFrame | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let live = true;
    videoFlowApi.get(caseId).then(d => { if (!live) return; setData(d); setError(''); }).catch(e => { if (live) setError(reason(e)); });
    return () => { live = false; };
  }, [caseId, round]);
  useEffect(() => {   // ダンが作業や案を足したら出す（見えている間だけ15秒ごと）
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') setRound(n => n + 1); }, 15000);
    return () => window.clearInterval(t);
  }, []);

  const run = data?.runs.find(r => r.id === runId);
  const stage = data?.stages.find(s => s.id === stageId);
  const pending = useMemo(() => (data?.proposals || []).filter(p => p.state === 'pending'), [data]);
  const decided = useMemo(() => (data?.proposals || []).filter(p => p.state !== 'pending'), [data]);
  const byStage = useMemo(() => {
    const out: Record<string, number> = {};
    for (const p of pending) out[p.stage] = (out[p.stage] || 0) + 1;
    return out;
  }, [pending]);

  const pickRun = (id: string) => {
    setRunId(id);
    const r = data?.runs.find(x => x.id === id);
    if (r?.case && r.case !== (caseId || data?.case)) setCaseId(r.case);
    const bad = r && data?.stages.find(s => ['bad', 'skipped'].includes(r.stages[s.id]?.state));
    if (bad) setStageId(bad.id);
  };

  const decide = useCallback(async (p: VideoFlowProposal, d: 'approve' | 'reject') => {
    const verb = d === 'approve' ? '承認' : '却下';
    if (!window.confirm(`「${p.title}」を${verb}しますか？${d === 'approve' && p.kind === 'text' ? '\n手順書の文がこの場で書き換わります（履歴から戻せます）。' : ''}`)) return;
    setBusy(true);
    try {
      await videoFlowApi.decide(p.id, d);
      try {   // ダンに知らせる（指示文の見直しの会話へ）。作業の案はこれでダンが動き出す
        const room = await promptsChat.room();
        const msg = d === 'approve'
          ? (p.kind === 'work' ? `動画の編集の図で「${p.title}」を承認しました。進めてください。` : `動画の編集の図で「${p.title}」を承認しました（手順書は保存済み）。`)
          : `動画の編集の図で「${p.title}」を却下しました。`;
        await promptsChat.send(msg, room.room_id, crypto.randomUUID());
      } catch { /* 決めた結果は保存済み。知らせが届かなくても図には残る */ }
      toast.success(`${verb}しました`);
      setRound(n => n + 1);
    } catch (e) { toast.error(reason(e)); }
    finally { setBusy(false); }
  }, []);

  if (error) return <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-800">{error}</p>;
  if (!data) return <p className="flex items-center gap-2 text-sm text-stone-500"><Loader2 className="size-4 animate-spin" />読み込んでいます</p>;

  return (
    <div className="space-y-4" data-testid="video-flow">
      <p className="text-sm text-stone-600">ダンが話す人の動画を編集する時に通る段です。箱を押すと、その段で読む手順書の文と使うプログラムが出ます。過去の作業を選ぶと、どの段で何をしたかが色で出ます。</p>
      {pending.length ? (
        <section className="space-y-2">
          <h2 className="text-base font-bold text-violet-950">ダンからの直しの案（{pending.length}）</h2>
          {pending.map(p => <Proposal key={p.id} p={p} stage={data.stages.find(s => s.id === p.stage)} busy={busy} onDecide={decide} onOpen={onOpenPrompt} onZoom={setZoom} />)}
        </section>
      ) : null}
      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-stone-200 bg-white p-3">
        <label className="min-w-0 flex-1 space-y-1 text-sm font-semibold"><span className="flex items-center gap-1"><Clapperboard className="size-4" />流し直す作業</span>
          <select className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-normal" value={runId} onChange={e => pickRun(e.target.value)}>
            <option value="">選ばない（段の中身だけ見る）</option>
            {data.runs.map(r => <option key={r.id} value={r.id}>{new Date(r.at).toLocaleDateString('ja-JP', { month: 'numeric', day: 'numeric' })} · {r.title}</option>)}
          </select></label>
        <label className="space-y-1 text-sm font-semibold">案件の決まり
          <select className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-normal" value={caseId || data.case} onChange={e => setCaseId(e.target.value)}>
            {data.cases.map(c => <option key={c.id} value={c.id}>{c.title.replace(/のテイストと決定|の決定/, '')}</option>)}
          </select></label>
      </div>
      {run ? (
        <div className="flex flex-wrap items-start gap-3 rounded-xl border border-stone-200 bg-white p-3 text-sm">
          {run.work.thumb ? (
            <a href={run.work.url || undefined} target="_blank" rel="noreferrer" className="shrink-0">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={run.work.thumb} alt="" className="h-20 rounded-md border" />
            </a>
          ) : null}
          <div className="min-w-0 flex-1 space-y-1">
            <b>{run.title}</b>
            {run.result ? <p className="text-stone-800">{run.result}</p> : null}
            {run.owner ? <p className="text-stone-600">みきさんの評価: {run.owner}</p> : null}
            {run.work.url ? <a className="text-xs font-semibold text-teal-800 hover:underline" href={run.work.url} target="_blank" rel="noreferrer">エディターで開く</a> : null}
          </div>
        </div>
      ) : null}
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <ol className="space-y-1">
          {data.stages.map((s, i) => {
            const did = run?.stages[s.id];
            return (
              <li key={s.id}>
                {i > 0 && <ArrowDown className="mx-auto my-0.5 size-4 text-stone-400" />}
                <button type="button" onClick={() => setStageId(stageId === s.id ? '' : s.id)} aria-pressed={stageId === s.id}
                  className={cn('w-full rounded-xl border-2 p-3 text-left transition hover:border-amber-400',
                    did ? STATE[did.state]?.box : 'border-stone-200 bg-white', stageId === s.id && 'ring-2 ring-amber-500 ring-offset-1')}>
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-bold">{i + 1}. {s.name}</span>
                    {did ? <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold', STATE[did.state]?.tag)}>{STATE[did.state]?.label}</span> : null}
                  </div>
                  {did?.did ? <p className="mt-1 line-clamp-3 text-xs text-stone-800">{did.did}</p> : <p className="mt-1 text-xs text-stone-600">{s.line}</p>}
                  <div className="mt-1.5 flex flex-wrap gap-1 text-[11px]">
                    <span className="rounded bg-stone-100 px-1.5 text-stone-700">読む文 {s.reads.length}</span>
                    <span className="rounded bg-stone-100 px-1.5 text-stone-700">プログラム {s.programs.length}</span>
                    {s.gap ? <span className="rounded bg-amber-100 px-1.5 text-amber-900">点検のプログラムが無い</span> : null}
                    {s.reads.some(r => !r.found) ? <span className="rounded bg-rose-100 px-1.5 text-rose-900">見つからない文あり</span> : null}
                    {byStage[s.id] ? <span className="rounded bg-violet-600 px-1.5 font-semibold text-white">直しの案 {byStage[s.id]}</span> : null}
                  </div>
                </button>
                {stageId === s.id && <div className="mt-2 rounded-xl border border-stone-200 bg-white p-3 xl:hidden"><StageDetail stage={s} run={run} onOpen={onOpenPrompt} onZoom={setZoom} /></div>}
              </li>
            );
          })}
        </ol>
        <div className="hidden rounded-xl border border-stone-200 bg-white p-3 xl:block">
          {stage ? <StageDetail stage={stage} run={run} onOpen={onOpenPrompt} onZoom={setZoom} /> : <p className="text-sm text-stone-500">左の段を押すと、ここにその段で読む文と使うプログラムが出ます。</p>}
        </div>
      </div>
      {decided.length ? (
        <details className="space-y-2">
          <summary className="cursor-pointer text-sm text-stone-600">決まった案（{decided.length}）</summary>
          <div className="space-y-2 pt-2">{decided.map(p => <Proposal key={p.id} p={p} stage={data.stages.find(s => s.id === p.stage)} busy={busy} onDecide={decide} onOpen={onOpenPrompt} onZoom={setZoom} />)}</div>
        </details>
      ) : null}
      {zoom ? (
        <div role="dialog" aria-label="コマを大きく見る" className="fixed inset-0 z-[80] flex flex-col items-center justify-center bg-black/85 p-4" onClick={() => setZoom(null)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={zoom.src} alt={zoom.label} className="max-h-[85dvh] max-w-full rounded" />
          <p className="mt-2 text-sm text-white">{zoom.time} {zoom.label}</p>
        </div>
      ) : null}
    </div>
  );
}
