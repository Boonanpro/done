'use client';

// サムネの案を並べて増やす帯（2026-11-23 本人「サムネは何パターンか作りたいんで自由に増やせるように。canvaみたいな
// 使い心地」→ 11/24「どうやって別パターンのサムネ足すん？」）。エディターの下に、その動画の案が小さな絵で並ぶ。
// - 押すとその案を開く。先頭が表のサムネ（「表」の印）
// - 「＋」で白紙の案を足す。複製は Ctrl+D（部品を選んでいない時）と案の「…」の「複製する」
//   （2026-11-24 本人「案を足すというテキストいらない。＋ボタンを押したら普通に白紙を。複製はCtrl+Dと…だけで良い」）
// - 案の「…」で 表のサムネにする・複製・消す（消すのは控えに回すだけ。最後の1つは消せない）
// - ダンが案を足した・直した・並べ替えた時は、その案に光と「ダン」の印を出す（2026-11-24 本人「下の一覧から新規追加するとか
//   複製するとか画面外のものも全部、ダンが何かやる時は必ずその操作を見える化しなさい」）。2秒ごとに読み直す

import { useCallback, useEffect, useRef, useState } from 'react';
import { Copy, Loader2, MoreHorizontal, MousePointer2, Plus, Star, Trash2 } from 'lucide-react';
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
type DanMark = { kind: 'added' | 'edited' | 'moved'; until: number };
const DAN_MARK_MS = 3500;

function url(path: string, roomId: string) {
  return `/api/v1/production-assets/contents/${path}${path.includes('?') ? '&' : '?'}room_id=${encodeURIComponent(roomId)}`;
}

export type ThumbPatternActions = { duplicateCurrent: () => void };

export function ThumbPatterns({ roomId, currentId, liveDoc, link, compact, beforeSwitch, onActions }: {
  roomId: string; currentId: string; liveDoc: ThumbDoc; link: ThumbPatternLink; compact: boolean;
  /** 別の案へ移る・複製する前に、今の直しを保存しておく */
  beforeSwitch: () => Promise<void>;
  /** エディターの Ctrl+D（部品を選んでいない時）から今の案を複製できるよう、その操作を渡す */
  onActions?: (a: ThumbPatternActions | null) => void;
}) {
  const [items, setItems] = useState<Pattern[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  // 帯は横に送れる箱なので、小さな欄は画面に固定して出す（箱の中だと切れる）
  const [at, setAt] = useState<{ left: number; bottom: number }>({ left: 0, bottom: 0 });
  const place = (el: Element) => { const r = el.getBoundingClientRect(); setAt({ left: Math.max(8, Math.min(window.innerWidth - 184, r.right - 176)), bottom: window.innerHeight - r.top + 4 }); };
  const boxRef = useRef<HTMLDivElement | null>(null);
  // ダンの手の印（案ごと）。この画面で本人が足した案には出さない
  const [marks, setMarks] = useState<Record<string, DanMark>>({});
  const mine = useRef(new Set<string>());
  const seen = useRef<Map<string, { rev: number; k: number }> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(url(`${encodeURIComponent(link.videoId)}/thumbnail-patterns`, roomId), { credentials: 'include', cache: 'no-store' });
      if (!res.ok) return;
      const j = (await res.json()) as { now?: number; patterns: Array<{ id: string; title: string; doc: unknown }> };
      const next = j.patterns.map((p) => ({ id: p.id, title: p.title, doc: asThumbDoc(p.doc) }));
      const prev = seen.current;
      const now = j.now || Date.now() / 1000;
      if (prev && typeof document !== 'undefined' && !document.hidden) {
        const add: Record<string, DanMark> = {};
        const until = Date.now() + DAN_MARK_MS;
        next.forEach((p, k) => {
          const by = p.doc.saved_by, at = p.doc.saved_at ? Date.parse(p.doc.saved_at) / 1000 : 0;
          const fresh = by === 'dan' && at > 0 && now - at < 8;
          const was = prev.get(p.id);
          if (!was) { if (!mine.current.has(p.id) && (fresh || by === 'dan')) add[p.id] = { kind: 'added', until }; return; }
          if ((p.doc.rev ?? 0) !== was.rev && fresh) add[p.id] = { kind: 'edited', until };
          else if (was.k !== k && fresh) add[p.id] = { kind: 'moved', until };
        });
        // 本人の画面（帯の送り位置）は動かさない（2026-11-10 本人「自分のUIを奪われるのは避けたい」）
        if (Object.keys(add).length) setMarks((m) => ({ ...m, ...add }));
      }
      seen.current = new Map(next.map((p, k) => [p.id, { rev: p.doc.rev ?? 0, k }]));
      setItems(next);
    } catch { /* 次に */ }
  }, [roomId, link.videoId]);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(t);
  }, [load]);
  useEffect(() => {
    const live = Object.values(marks);
    if (!live.length) return;
    const t = window.setTimeout(() => setMarks((m) => Object.fromEntries(Object.entries(m).filter(([, v]) => v.until > Date.now()))),
      Math.max(50, Math.min(...live.map((v) => v.until)) - Date.now()));
    return () => window.clearTimeout(t);
  }, [marks]);

  // 帯の外を押したら開いている小さな欄を閉じる
  useEffect(() => {
    if (!menu) return;
    const onDown = (ev: PointerEvent) => {
      if (boxRef.current && !boxRef.current.contains(ev.target as Node)) setMenu(null);
    };
    window.addEventListener('pointerdown', onDown);
    return () => window.removeEventListener('pointerdown', onDown);
  }, [menu]);

  const add = async (fromId: string | null) => {
    if (busy === 'add') return;
    setMenu(null);
    setBusy('add');
    try {
      await beforeSwitch();
      const res = await fetch(url(`${encodeURIComponent(link.videoId)}/thumbnail-patterns`, roomId), {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ from_id: fromId }),
      });
      if (!res.ok) throw new Error(await res.text());
      const made = (await res.json()) as { id: string; title?: string };
      mine.current.add(made.id);
      await load();
      link.onChanged?.();
      link.onOpen(made);
    } catch (e) {
      toast.error('案を足せませんでした', { description: String((e as Error).message || e).slice(0, 160) });
    } finally {
      setBusy(null);
    }
  };

  const addRef = useRef(add);
  useEffect(() => { addRef.current = add; });
  useEffect(() => {
    if (!onActions) return;
    onActions({ duplicateCurrent: () => void addRef.current(currentId) });
    return () => onActions(null);
  }, [onActions, currentId]);

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
      <style>{'@keyframes thumbDanIn{from{opacity:0;transform:translateY(8px) scale(.85)}to{opacity:1;transform:none}}'}</style>
      {items.map((p, k) => {
        const cur = p.id === currentId;
        const dm = marks[p.id];
        return (
          <div key={p.id} className="relative shrink-0" style={{ width: cardW, animation: dm?.kind === 'added' ? 'thumbDanIn .45s cubic-bezier(.2,.8,.2,1)' : undefined }} data-thumb-pattern={p.id}>
            <button type="button" onClick={() => void open(p)} title={cur ? '今開いている案' : 'この案を開く'}
              className={`block w-full overflow-hidden rounded-md ${cur ? 'ring-2 ring-sky-500' : 'ring-1 ring-border hover:ring-sky-300'}`}
              style={dm ? { boxShadow: '0 0 0 2px #38bdf8, 0 0 14px 3px rgba(56,189,248,.65)' } : undefined}>
              <div className="pointer-events-none"><ThumbCanvas doc={cur ? liveDoc : p.doc} width="100%" /></div>
            </button>
            {dm ? (
              <div aria-hidden className="pointer-events-none absolute left-1/2 top-1/2 z-10" data-dan-pattern-mark={dm.kind}>
                <MousePointer2 className="h-5 w-5 fill-sky-400 text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.7)]" />
                <span className="ml-3 mt-[-2px] block w-max rounded-full bg-sky-500 px-1.5 py-[1px] text-[10px] font-semibold leading-tight text-white shadow">
                  ダン {dm.kind === 'added' ? '足しました' : dm.kind === 'moved' ? '並べ替えました' : '直しました'}
                </span>
              </div>
            ) : null}
            <div className="mt-1 flex items-center gap-1 text-[11px]">
              {k === 0 ? <span className="flex items-center gap-0.5 rounded bg-amber-400/90 px-1 font-semibold text-black" title="表のサムネ（動画に使う案）"><Star className="h-2.5 w-2.5" />表</span> : null}
              <span className={`min-w-0 flex-1 truncate ${cur ? 'font-semibold' : 'text-muted-foreground'}`}>{p.title || `案${k + 1}`}</span>
              {busy === p.id ? <Loader2 className="h-3 w-3 animate-spin" /> : (
                <button type="button" title="この案の操作" className="rounded p-0.5 hover:bg-muted" onClick={(e) => { place(e.currentTarget); setMenu((m) => (m === p.id ? null : p.id)); }} data-thumb-pattern-menu>
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
                  <Copy className="h-3.5 w-3.5" />複製する<span className="ml-auto text-[10px] text-muted-foreground">{p.id === currentId ? 'Ctrl+D' : ''}</span>
                </button>
                <button type="button" disabled={items.length <= 1} className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left text-destructive hover:bg-muted disabled:opacity-40" onClick={() => void remove(p.id)} data-thumb-pattern-remove>
                  <Trash2 className="h-3.5 w-3.5" />消す
                </button>
              </div>
            ) : null}
          </div>
        );
      })}
      <div className="relative shrink-0 self-start" style={{ width: Math.round(cardW * 0.6) }}>
        <button type="button" onClick={() => void add(null)} disabled={busy === 'add'} title="白紙の案を足す（複製は Ctrl+D か案の …）"
          className="flex w-full items-center justify-center rounded-md border-2 border-dashed border-border text-muted-foreground hover:border-sky-400 hover:text-sky-500"
          style={{ aspectRatio: '16 / 9' }} data-thumb-pattern-add>
          {busy === 'add' ? <Loader2 className="h-5 w-5 animate-spin" /> : <Plus className="h-5 w-5" />}
        </button>
      </div>
    </div>
  );
}
