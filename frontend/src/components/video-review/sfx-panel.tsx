'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Play, Plus, Square } from 'lucide-react';

/** 効果音の一覧の1行（サーバー: app/services/editor_instructions.py sfx_library） */
export type SfxItem = {
  key: string;
  name: string;
  filename: string;
  uses: number;
  duration: number;
  source_room_id: string;
  source_asset_id: string;
  in_room_asset_id: string | null;
  preview_url: string;
};

/** タイムラインの音の段へ引きずる時の印（エディターの handleLaneDrop が受ける） */
export const SFX_DND_TYPE = 'application/x-dan-sfx';

/** 効果音の一覧（2026-11-14 本人「よく使う効果音を一覧にして、自分で手動で貼れるように」）。
 *  作品で使われた回数の多い順。▶で試し聞き、＋か行を押すと再生位置に入る、音の段へ引きずるとそこに入る。 */
export function SfxPanel({
  roomId,
  onAdd,
  onClose,
}: {
  roomId: string;
  onAdd: (item: SfxItem) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<SfxItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [playing, setPlaying] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(`/api/v1/production-assets/sfx-library?room_id=${encodeURIComponent(roomId)}`, { credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.text()).slice(0, 160));
        return res.json() as Promise<{ items: SfxItem[] }>;
      })
      .then((body) => { if (alive) setItems(body.items); })
      .catch((e) => { if (alive) setError(String(e)); });
    return () => { alive = false; audioRef.current?.pause(); };
  }, [roomId]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items || []).filter((it) => !q || it.name.toLowerCase().includes(q));
  }, [items, query]);

  const preview = (it: SfxItem) => {
    const cur = audioRef.current;
    if (cur) cur.pause();
    if (playing === it.key) { setPlaying(null); return; }
    const a = new Audio(it.preview_url);
    audioRef.current = a;
    a.onended = () => setPlaying((p) => (p === it.key ? null : p));
    setPlaying(it.key);
    void a.play().catch(() => setPlaying(null));
  };

  return (
    <div
      data-sfx-panel
      className="absolute bottom-full left-2 z-40 mb-2 flex max-h-[min(60vh,460px)] w-[340px] flex-col rounded-md border border-border bg-background/98 shadow-2xl"
      onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Escape') onClose(); }}
    >
      <div className="flex items-center gap-2 border-b border-border p-2">
        <div className="text-sm font-medium">効果音</div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="名前で探す（太鼓・whoosh…）"
          className="h-7 min-w-0 flex-1 rounded border border-input bg-background px-2 text-xs"
        />
        <button type="button" className="px-1 text-muted-foreground hover:text-foreground" onClick={onClose} aria-label="閉じる">✕</button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {error ? <div className="p-2 text-xs text-red-500">一覧を読めませんでした: {error}</div> : null}
        {!items && !error ? <div className="p-2 text-xs text-muted-foreground">読み込み中…</div> : null}
        {items && !shown.length ? <div className="p-2 text-xs text-muted-foreground">見つかりません</div> : null}
        {shown.map((it) => (
          <div
            key={it.key}
            data-sfx-key={it.key}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData(SFX_DND_TYPE, JSON.stringify(it));
              e.dataTransfer.effectAllowed = 'copy';
              (window as unknown as { __danDragAsset?: { duration?: number } }).__danDragAsset = { duration: it.duration };
            }}
            onDragEnd={() => { delete (window as unknown as { __danDragAsset?: unknown }).__danDragAsset; }}
            className="group flex cursor-grab items-center gap-1.5 rounded px-1.5 py-1 text-xs hover:bg-muted active:cursor-grabbing"
            title="押すと再生位置に入る。音の段へ引きずるとそこに入る"
            onDoubleClick={() => onAdd(it)}
          >
            <button
              type="button"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-border hover:bg-background"
              onClick={(e) => { e.stopPropagation(); preview(it); }}
              aria-label="試し聞き"
              title="試し聞き"
            >
              {playing === it.key ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            </button>
            <span className="min-w-0 flex-1 truncate">{it.name}</span>
            <span className="shrink-0 tabular-nums text-[10px] text-muted-foreground">{it.duration.toFixed(1)}秒</span>
            {it.uses ? <span className="shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground" title="作品で使った回数">{it.uses}回</span> : null}
            <button
              type="button"
              data-sfx-add
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-yellow-500/80 text-black hover:bg-yellow-400"
              onClick={(e) => { e.stopPropagation(); onAdd(it); }}
              aria-label="再生位置に入れる"
              title="再生位置に入れる"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
