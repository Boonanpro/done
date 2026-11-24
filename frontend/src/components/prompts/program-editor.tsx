'use client';

import { useEffect, useRef, useState } from 'react';
import { promptRequest, promptsChat } from '@/lib/prompts-api';
import catalog from './program-sources.json';

interface Source { path: string; text: string; sha: string }
const paths: Record<string, string[]> = catalog;

export function ProgramEditor({ node, onChat }: { node: string; onChat: () => void }) {
  const files = paths[node] || [];
  const [selected, setSelected] = useState('');
  const [original, setOriginal] = useState<Source | null>(null);
  const [draft, setDraft] = useState('');
  const [scenario, setScenario] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  useEffect(() => {
    if (!historyOpen || !selected) return;
    let live = true;
    promptRequest<{diff:string; truncated:boolean}>('/program/change?path='+encodeURIComponent(selected)).then(result => {
      if (live) setHistory((result.diff || '履歴がありません。') + (result.truncated ? '\n（変更が大きいため最初の部分を表示）' : ''));
    }).catch(() => { if (live) setHistory('変更履歴を開けませんでした。'); });
    return () => { live = false; };
  }, [historyOpen, selected]);
  const dialog = useRef<HTMLDialogElement>(null);
  const submitting = useRef(false);
  const submission = useRef({key:'', id:''});
  useEffect(() => {
    if (!selected) return;
    let alive = true;
    const popup = dialog.current;
    popup?.showModal();
    promptRequest<Source>('/program?path='+encodeURIComponent(selected)).then(src => {
      if (alive) { setOriginal(src); setDraft(src.text); }
    }).catch(e => { if (alive) setError(String(e)); });
    return () => { alive = false; popup?.close(); };
  }, [selected]);
  function open(path: string) {
    setHistory(''); setHistoryOpen(false); setOriginal(null); setDraft(''); setScenario(''); setError(''); setSelected(path);
  }
  function dismiss() {
    if (submitting.current) return;
    if (original && (draft !== original.text || scenario) && !window.confirm('編集中の内容を閉じますか？')) return;
    setSelected('');
  }
  async function testChange() {
    if (!original || !scenario.trim() || submitting.current) return;
    submitting.current = true; setBusy(true); setError('');
    try {
      const {draft: saved} = await promptRequest<{draft: string}>('/program/draft', {
        path: original.path, base_sha: original.sha, text: draft, scenario: scenario.trim(),
      });
      const room = await promptsChat.room();
      const key = room.room_id + saved;
      if (submission.current.key !== key) submission.current = {key, id: crypto.randomUUID()};
      const message = [
        '構成図で編集した実装を、作業用の環境で試してください。',
        '対象ファイル ' + original.path,
        '試す内容 ' + scenario.trim(),
        '変更内容の控え ' + saved,
        '専用の作業場所で変更前の動作を確認し、scripts/try_program_draft.py に控えを渡して適用してください。変更後も同じ操作を試し、変更点と実際の結果をこの会話に返してください。本番への反映は結果を見てから決めます。',
      ].join('\n');
      await promptsChat.send(message, room.room_id, submission.current.id);
      setSelected(''); onChat();
    } catch (e) { setError(e instanceof Error ? e.message : '試す依頼が届きませんでした。'); }
    finally { submitting.current = false; setBusy(false); }
  }
  if (!files.length) return null;
  return <section className="space-y-1.5">
    <h3 className="text-sm font-semibold text-sky-900">実装を開く</h3>
    {files.map(path => <button key={path} className="block w-full break-all rounded-lg border border-sky-200 bg-white p-2 text-left font-mono text-xs text-sky-900 hover:bg-sky-50" onClick={() => open(path)}>{path}</button>)}
    {selected && <dialog ref={dialog} aria-label="実装を編集" onCancel={event => {event.preventDefault(); dismiss();}}
      className="fixed inset-0 m-auto w-[min(96vw,960px)] max-h-[92dvh] overflow-auto rounded-xl border bg-white p-4 text-stone-900 shadow-xl backdrop:bg-black/35">
      <header className="flex items-center justify-between gap-4"><h2 className="min-w-0 break-all font-mono text-sm">{selected}</h2>
        <button onClick={dismiss} disabled={busy} className="rounded border px-3 py-1">閉じる</button></header>
      {original ? <>
        <button className="mt-2 text-sm text-sky-900 underline" aria-expanded={historyOpen} onClick={() => setHistoryOpen(v => !v)}>直近の変更を見る</button>
        {historyOpen && <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded border bg-stone-50 p-2 text-xs">{history || '履歴を読んでいます…'}</pre>}
        <textarea aria-label="実装コード" spellCheck={false} value={draft} onChange={e => setDraft(e.target.value)} disabled={busy}
          className="my-3 h-[48dvh] w-full whitespace-pre rounded border bg-stone-50 p-3 font-mono text-xs leading-5" wrap="off" />
        <label className="block text-sm font-semibold">試したい依頼と期待する結果
          <textarea value={scenario} onChange={e => setScenario(e.target.value)} disabled={busy} maxLength={4000} rows={2} className="mt-1 w-full rounded border p-2 font-normal" />
        </label>
        <button onClick={testChange} disabled={busy || !scenario.trim()} className="mt-2 rounded bg-emerald-900 px-4 py-2 text-sm text-white disabled:opacity-40">
          {busy ? '依頼中…' : '作業用の環境で試す'}</button>
      </> : !error && <p>実装を読み込んでいます…</p>}
      {error && <p role="alert" className="mt-2 text-sm text-rose-800">{error}</p>}
    </dialog>}
  </section>;
}
