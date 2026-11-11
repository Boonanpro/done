'use client';

import { useEffect, useRef, useState } from 'react';
import type { StageCard } from './voice-stage';
import { stageHeaders } from './voice-stage';

type Proposal = { id: string; status: string; content: string; action_data?: Record<string, unknown> };

// Read the saved proposal, not the call's snapshot: a manual edit must survive reopening the call screen.
export function useStageDraft(card: StageCard) {
  const [current, setCurrent] = useState(card);
  const [body, setBody] = useState(card.body);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('読み込み中…');
  const dirty = useRef(false);
  const busy = useRef(false);
  const generation = useRef(0);
  const url = `/api/v1/chat/proposals/${encodeURIComponent(card.proposal_id)}`;

  function accept(row: Proposal) {
    const ad = row.action_data || {};
    setCurrent(previous => ({ ...previous, body: row.content, status: row.status,
      to: String(ad.to ?? previous.to), to_name: String(ad.to_name ?? previous.to_name ?? ''),
      subject: String(ad.subject ?? ''), revision: Number(ad.revision || 1) }));
    setBody(row.content);
    setLoaded(true);
  }

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function refresh() {
      const version = generation.current;
      try {
        if (!dirty.current && !busy.current) {
          const response = await fetch(url, { headers: stageHeaders(), cache: 'no-store', signal: controller.signal });
          if (!response.ok) throw new Error('load');
          const row: Proposal = await response.json();
          if (!stopped && version === generation.current && !dirty.current && !busy.current) {
            accept(row);
            setNotice('本文を直接編集できます');
          }
        }
      } catch {
        if (!stopped && !dirty.current) setNotice('読み込めませんでした。再接続を待っています');
      } finally {
        if (!stopped) timer = setTimeout(refresh, 3000);
      }
    }
    void refresh();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [url]);

  async function save() {
    if (!dirty.current || busy.current || current.status !== 'pending') return;
    busy.current = true;
    generation.current += 1;
    setSaving(true);
    setNotice('保存中…');
    try {
      const response = await fetch(`${url}/draft`, { method: 'PATCH',
        headers: { ...stageHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ body }) });
      if (!response.ok) throw new Error('save');
      const row: Proposal = await response.json();
      accept(row);
      dirty.current = false;
      setNotice('保存しました');
    } catch {
      setNotice('保存できませんでした。入力した文章は残っています。もう一度保存してください');
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }

  const editor = current.status === 'pending' ? (
    <div className="flex flex-col gap-2 text-left">
      <label className="text-xs text-muted-foreground" htmlFor={`stage-body-${card.proposal_id}`}>本文を編集</label>
      <textarea id={`stage-body-${card.proposal_id}`} aria-label="送信案の本文" value={body}
        readOnly={!loaded || saving} rows={12}
        className="w-full resize-y rounded-lg border border-neutral-600 bg-neutral-900 p-3 text-base leading-7 text-white focus:border-blue-400 focus:outline-none"
        style={{ height: 'clamp(140px, 48dvh, 520px)', minHeight: 100 }}
        onChange={event => { setBody(event.target.value); dirty.current = true; generation.current += 1; setNotice('未保存'); }} />
      <div className="sticky bottom-0 flex items-center gap-3 rounded-lg bg-neutral-950 py-2">
        <button type="button" disabled={!loaded || !dirty.current || saving} onClick={() => void save()}
          className="shrink-0 rounded-lg bg-blue-600 px-5 py-2.5 text-sm text-white disabled:opacity-40">{saving ? '保存中…' : '保存'}</button>
        <span role="status" className="text-xs text-neutral-300">{notice}</span>
      </div>
    </div>
  ) : null;
  return { current, editor };
}
