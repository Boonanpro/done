'use client';

// サムネの案を並べて増やす帯（2026-11-23 本人「サムネは何パターンか作りたいんで自由に増やせるように。canvaみたいな
// 使い心地」→ 11/24「どうやって別パターンのサムネ足すん？」）。エディターの下に、その動画の案が小さな絵で並ぶ。
// - 押すとその案を開く。先頭が表のサムネ（「表」の印）
// - 「＋」で今の案を複製するか白紙から足す
// - 案の「…」で 表のサムネにする・複製・消す（消すのは控えに回すだけ。最後の1つは消せない）

import { useCallback, useEffect, useRef, useState } from 'react';
import { Copy, FilePlus2, Loader2, MoreHorizontal, Plus, Star, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { ThumbCanvas } from './thumb-canvas';
import { asThumbDoc, type ThumbDoc } from './thumb-doc';

export type ThumbPatternLink = {
  videoId: string;
  /** 案を開く（足した案もこれで開く） */
  onOpen: (content: { id: string; title?: string; [k: string]: unknown }) => void;
  /** 並び・数が変わった（上の切り替えの札を読み直す） */
  onChanged?: () => void;
};

type Pattern = { id: string; title: string; doc: ThumbDoc };

function url(path: string, roomId: string) {
  return `/api/v1/production-assets/contents/${path}${path.includes('?') ? '&' : '?'}room_id=${encodeURIComponent(roomId)}`;
}

export function ThumbPatterns({ roomId, currentId, liveDoc, link, compact, beforeSwitch }: {
  roomId: string; currentId: string; liveDoc: ThumbDoc; link: ThumbPatternLink; compact: boolean;
  /** 別の案へ移る・複製する前に、今の直しを保存しておく */
  beforeSwitch: () => Promise<void>;
}) {
  const [items, setItems] = useState<Pattern[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  // 帯は横に送れる箱なので、小さな欄は画面に固定して出す（箱の中だと切れる）
  const [at, setAt] = useState<{ left: number; bottom: number }>({ left: 0, bottom: 0 });
  const place = (el: Element) => { const r = el.getBoundingClientRect(); setAt({ left: Math.max(8, Math.min(window.innerWidth - 184, r.right - 176)), bottom: window.innerHeight - r.top + 4 }); };
  const boxRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(url(`${encodeURIComponent(link.videoId)}/thumbnail-patterns`, roomId), { credentials: 'include', cache: 'no-store' });
      if (!res.ok) return;
      const j = (await res.json()) as { patterns: Array<{ id: string; title: string; doc: unknown }> };
      setItems(j.patterns.map((p) => ({ id: p.id, title: p.title, doc: asThumbDoc(p.doc) })));
    } catch { /* 次に */ }
  }, [roomId, link.videoId]);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(t);
  }, [load]);

  // 帯の外を押したら開いている小さな欄を閉じる
  useEffect(() => {
    if (!menu && !addOpen) return;
    const onDown = (ev: PointerEvent) => {
      if (boxRef.current && !boxRef.current.contains(ev.target as Node)) { setMenu(null); setAddOpen(false); }
    };
    window.addEventListener('pointerdown', onDown);
    return () => window.removeEventListener('pointerdown', onDown);
  }, [menu, addOpen]);

  const add = async (fromId: string | null) => {
    setAddOpen(false); setMenu(null);
    setBusy('add');
    try {
      await beforeSwitch();
      const res = await fetch(url(`${encodeURIComponent(link.videoId)}/thumbnail-patterns`, roomId), {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ from_id: fromId }),
      });
      if (!res.ok) throw new Error(await res.text());
      const made = (await res.json()) as { id: string; title?: string };
      await load();
      link.onChanged?.();
      link.onOpen(made);
    } catch (e) {
      toast.error('案を足せませんでした', { description: String((e as Error).message || e).slice(0, 160) });
    } finally {
      setBusy(null);
    }
  };

  const makePrimary = async (id: string) => {
    setMenu(null);
    setBusy(id);
    try {
      const res = await fetch(url(`${encodeURIComponent(link.videoId)}/thumbnail-patterns/order`, roomId), {
        method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: [id] }),
      });
      if (!res.ok) throw new Error(await res.text());
      await load();
      link.onChanged?.();
    } catch (e) {
      toast.error('表のサムネにできませんでした', { description: String((e as Error).message || e).slice(0, 160) });
    } finally {
      setBusy(null);
    }
  };

  const remove = async (id: string) => {
    setMenu(null);
    if (items.length <= 1) { toast.message('最後の1つの案は消せません'); return; }
    const p = items.find((x) => x.id === id);
    if (!window.confirm(`「${p?.title || '案'}」を消しますか？`)) return;
    setBusy(id);
    try {
      const res = await fetch(url(`${encodeURIComponent(id)}/thumbnail`, roomId), { method: 'DELETE', credentials: 'include' });
      if (!res.ok) throw new Error(await res.text());
      const rest = items.filter((x) => x.id !== id);
      setItems(rest);
      link.onChanged?.();
      if (id === currentId && rest[0]) link.onOpen({ id: rest[0].id, title: rest[0].title });
    } catch (e) {
      toast.error('消せませんでした', { description: String((e as Error).message || e).slice(0, 160) });
    } finally {
      setBusy(null);
    }
  };

  const open = async (p: Pattern) => {
    if (p.id === currentId) return;
    setMenu(null);
    await beforeSwitch();
    link.onOpen({ id: p.id, title: p.title });
  };

  const cardW = compact ? 112 : 132;
  return (
    <div ref={boxRef} className="flex shrink-0 items-end gap-2 overflow-x-auto px-3 py-2" data-thumb-patterns>
      {items.map((p, k) => {
        const cur = p.id === currentId;
        return (
          <div key={p.id} className="relative shrink-0" style={{ width: cardW }} data-thumb-pattern={p.id}>
            <button type="button" onClick={() => void open(p)} title={cur ? '今開いている案' : 'この案を開く'}
              className={`block w-full overflow-hidden rounded-md ${cur ? 'ring-2 ring-sky-500' : 'ring-1 ring-border hover:ring-sky-300'}`}>
              <div className="pointer-events-none"><ThumbCanvas doc={cur ? liveDoc : p.doc} width="100%" /></div>
            </button>
            <div className="mt-1 flex items-center gap-1 text-[11px]">
              {k === 0 ? <span className="flex items-center gap-0.5 rounded bg-amber-400/90 px-1 font-semibold text-black" title="表のサムネ（動画に使う案）"><Star className="h-2.5 w-2.5" />表</span> : null}
              <span className={`min-w-0 flex-1 truncate ${cur ? 'font-semibold' : 'text-muted-foreground'}`}>{p.title || `案${k + 1}`}</span>
              {busy === p.id ? <Loader2 className="h-3 w-3 animate-spin" /> : (
                <button type="button" title="この案の操作" className="rounded p-0.5 hover:bg-muted" onClick={(e) => { place(e.currentTarget); setAddOpen(false); setMenu((m) => (m === p.id ? null : p.id)); }} data-thumb-pattern-menu>
                  <MoreHorizontal className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            {menu === p.id ? (
              <div className="fixed z-[60] w-44 overflow-hidden rounded-md border border-border bg-popover text-xs shadow-lg" style={{ left: at.left, bottom: at.bottom }}>
                {k !== 0 ? (
                  <button type="button" className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left hover:bg-muted" onClick={() => void makePrimary(p.id)} data-thumb-pattern-primary>
                    <Star className="h-3.5 w-3.5" />表のサムネにする
                  </button>
                ) : null}
                <button type="button" className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left hover:bg-muted" onClick={() => void add(p.id)} data-thumb-pattern-dup>
                  <Copy className="h-3.5 w-3.5" />複製する
                </button>
                <button type="button" disabled={items.length <= 1} className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left text-destructive hover:bg-muted disabled:opacity-40" onClick={() => void remove(p.id)} data-thumb-pattern-remove>
                  <Trash2 className="h-3.5 w-3.5" />消す
                </button>
              </div>
            ) : null}
          </div>
        );
      })}
      <div className="relative shrink-0" style={{ width: Math.round(cardW * 0.6) }}>
        <button type="button" onClick={(e) => { place(e.currentTarget); setMenu(null); setAddOpen((v) => !v); }} disabled={busy === 'add'} title="案を足す"
          className="flex w-full items-center justify-center rounded-md border-2 border-dashed border-border text-muted-foreground hover:border-sky-400 hover:text-sky-500"
          style={{ aspectRatio: '16 / 9' }} data-thumb-pattern-add>
          {busy === 'add' ? <Loader2 className="h-5 w-5 animate-spin" /> : <Plus className="h-5 w-5" />}
        </button>
        <div className="mt-1 text-center text-[11px] text-muted-foreground">案を足す</div>
        {addOpen ? (
          <div className="fixed z-[60] w-44 overflow-hidden rounded-md border border-border bg-popover text-xs shadow-lg" style={{ left: at.left, bottom: at.bottom }}>
            <button type="button" className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left hover:bg-muted" onClick={() => void add(currentId)} data-thumb-pattern-add-copy>
              <Copy className="h-3.5 w-3.5" />今の案を複製
            </button>
            <button type="button" className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left hover:bg-muted" onClick={() => void add(null)} data-thumb-pattern-add-blank>
              <FilePlus2 className="h-3.5 w-3.5" />白紙から
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
