'use client';

// サムネの案を大きく並べ、それぞれの絵の下で題とメモを書いて決める（2026-11-25 本人「別のタイムラインに分けずこっちの部屋の中に
// サムネを並べろ。画像枠の下にテキスト文字を入力したり編集できる項目ほしいですね。そうやって同時に並べてサムネとタイトルを決めたい」）。
// - その動画の案を全部、PC は2〜3列・スマホは1列で並べる。絵を押すとその案をいつもの直す画面で開く
// - 題（YouTube に出す題 = doc.title。「一覧で見る」の下の題も同じ）とメモ（企画の一言・冒頭5秒など = doc.plan_note）は
//   打った端から少し間を置いて保存する。保存は題とメモだけを書く API なので、ダンや直す画面の部品の直しと消し合わない
// - 2秒ごとに読み直し、ダンが絵・題・メモを直した案には光と「ダン」の印を出す（下の案の帯と同じ）。打っている欄は上書きしない

import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, MousePointer2, Pencil, Star } from 'lucide-react';

import { ThumbCanvas } from './thumb-canvas';
import { asThumbDoc, type ThumbDoc } from './thumb-doc';

type Pattern = { id: string; title: string; doc: ThumbDoc };
type Field = 'title' | 'plan_note';
type Draft = { title: string; plan_note: string };
type DanMark = { until: number };
const DAN_MARK_MS = 3500;
const SAVE_DELAY = 700;

function url(path: string, roomId: string) {
  return `/api/v1/production-assets/contents/${path}${path.includes('?') ? '&' : '?'}room_id=${encodeURIComponent(roomId)}`;
}

const metaOf = (d: ThumbDoc): Draft => ({ title: d.title || '', plan_note: d.plan_note || '' });

export function ThumbLineup({ roomId, videoId, currentId, liveDoc, compact, onOpen }: {
  roomId: string; videoId: string; currentId: string; liveDoc: ThumbDoc; compact: boolean;
  /** 絵を押した案を直す画面で開く */
  onOpen: (p: { id: string; title: string }) => void;
}) {
  const [items, setItems] = useState<Pattern[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saving, setSaving] = useState<Record<string, 'saving' | 'saved' | 'error'>>({});
  const [marks, setMarks] = useState<Record<string, DanMark>>({});
  // 打ったがまだ保存していない欄（読み直しで上書きしない）
  const pending = useRef(new Map<string, Partial<Draft>>());
  const timers = useRef(new Map<string, number>());
  const focused = useRef<string | null>(null);
  const seen = useRef<Map<string, string> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(url(`${encodeURIComponent(videoId)}/thumbnail-patterns`, roomId), { credentials: 'include', cache: 'no-store' });
      if (!res.ok) return;
      const j = (await res.json()) as { now?: number; patterns: Array<{ id: string; title: string; doc: unknown }> };
      const next = j.patterns.map((p) => ({ id: p.id, title: p.title, doc: asThumbDoc(p.doc) }));
      const now = j.now || Date.now() / 1000;
      const prev = seen.current;
      if (prev && typeof document !== 'undefined' && !document.hidden) {
        const until = Date.now() + DAN_MARK_MS;
        const add: Record<string, DanMark> = {};
        next.forEach((p) => {
          const at = p.doc.saved_at ? Date.parse(p.doc.saved_at) / 1000 : 0;
          const key = `${p.doc.rev ?? 0}`;
          if (p.doc.saved_by === 'dan' && at > 0 && now - at < 8 && prev.get(p.id) !== key) add[p.id] = { until };
        });
        if (Object.keys(add).length) setMarks((m) => ({ ...m, ...add }));
      }
      seen.current = new Map(next.map((p) => [p.id, `${p.doc.rev ?? 0}`]));
      setItems(next);
      setDrafts((cur) => {
        const out: Record<string, Draft> = {};
        for (const p of next) {
          const server = metaOf(p.doc);
          const mine = pending.current.get(p.id) || {};
          const had = cur[p.id];
          out[p.id] = {
            title: 'title' in mine || focused.current === `${p.id}:title` ? (had?.title ?? server.title) : server.title,
            plan_note: 'plan_note' in mine || focused.current === `${p.id}:plan_note` ? (had?.plan_note ?? server.plan_note) : server.plan_note,
          };
        }
        return out;
      });
    } catch { /* 次に */ }
  }, [roomId, videoId]);

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

  const flush = useCallback(async (id: string) => {
    const patch = pending.current.get(id);
    if (!patch || !Object.keys(patch).length) return;
    pending.current.delete(id);
    setSaving((s) => ({ ...s, [id]: 'saving' }));
    try {
      const res = await fetch(url(`${encodeURIComponent(id)}/thumbnail/meta`, roomId), {
        method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
      });
      if (!res.ok) throw new Error(await res.text());
      const j = (await res.json()) as { rev?: number };
      // 自分の保存は「ダンの直し」と見ない
      if (seen.current && typeof j.rev === 'number') seen.current.set(id, `${j.rev}`);
      setSaving((s) => ({ ...s, [id]: 'saved' }));
    } catch {
      // 保存できなかった分は戻して次の入力で出し直す
      pending.current.set(id, { ...patch, ...(pending.current.get(id) || {}) });
      setSaving((s) => ({ ...s, [id]: 'error' }));
    }
  }, [roomId]);

  // 開いている間の書きかけは、閉じる・案を開く時に出しておく
  useEffect(() => () => {
    timers.current.forEach((t) => window.clearTimeout(t));
    for (const id of Array.from(pending.current.keys())) void flush(id);
  }, [flush]);

  const edit = (id: string, field: Field, value: string) => {
    setDrafts((d) => ({ ...d, [id]: { ...(d[id] || { title: '', plan_note: '' }), [field]: value } }));
    pending.current.set(id, { ...(pending.current.get(id) || {}), [field]: value });
    const t = timers.current.get(id);
    if (t) window.clearTimeout(t);
    timers.current.set(id, window.setTimeout(() => { timers.current.delete(id); void flush(id); }, SAVE_DELAY));
  };

  const openPattern = async (p: Pattern) => {
    const t = timers.current.get(p.id);
    if (t) window.clearTimeout(t);
    await flush(p.id);
    onOpen({ id: p.id, title: p.title });
  };

  if (!items) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground" data-thumb-lineup>
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />案を読んでいます…
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto" data-thumb-lineup>
      <style>{'@keyframes thumbLineupDan{from{box-shadow:0 0 0 3px #38bdf8,0 0 22px 6px rgba(56,189,248,.75)}to{box-shadow:0 0 0 0 rgba(56,189,248,0)}}'}</style>
      <div className={`grid gap-5 ${compact ? 'grid-cols-1 p-3' : 'grid-cols-[repeat(auto-fit,minmax(340px,1fr))] p-5'}`}>
        {items.map((p, k) => {
          const cur = p.id === currentId;
          const d = drafts[p.id] || metaOf(p.doc);
          const dm = marks[p.id];
          const st = saving[p.id];
          return (
            <div key={p.id} className="relative mx-auto w-full max-w-[720px] min-w-0" data-thumb-lineup-card={p.id}>
              <div className="mb-1.5 flex items-center gap-1.5 text-xs">
                {k === 0 ? <span className="flex items-center gap-0.5 rounded bg-amber-400/90 px-1.5 py-[1px] font-semibold text-black" title="表のサムネ（動画に使う案）"><Star className="h-3 w-3" />表</span> : null}
                <span className="min-w-0 flex-1 truncate font-semibold">{p.title || `案${k + 1}`}</span>
                <span className="text-[11px] text-muted-foreground">{st === 'saving' ? '保存中…' : st === 'error' ? '保存できていません' : st === 'saved' ? '保存しました' : ''}</span>
              </div>
              <button type="button" onClick={() => void openPattern(p)} title="この案を開いて直す"
                className={`group relative block w-full overflow-hidden rounded-lg ${cur ? 'ring-2 ring-sky-500' : 'ring-1 ring-border hover:ring-sky-300'}`}
                style={dm ? { animation: `thumbLineupDan ${DAN_MARK_MS}ms ease-out` } : undefined} data-thumb-lineup-open>
                <div className="pointer-events-none"><ThumbCanvas doc={cur ? liveDoc : p.doc} width="100%" /></div>
                <span className="absolute right-2 top-2 flex items-center gap-1 rounded-full bg-black/60 px-2 py-1 text-[11px] text-white opacity-0 transition group-hover:opacity-100">
                  <Pencil className="h-3 w-3" />開いて直す
                </span>
              </button>
              {dm ? (
                <div aria-hidden className="pointer-events-none absolute left-1/2 top-1/3 z-10" data-dan-lineup-mark>
                  <MousePointer2 className="h-6 w-6 fill-sky-400 text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.7)]" />
                  <span className="ml-4 mt-[-2px] block w-max rounded-full bg-sky-500 px-2 py-[2px] text-[11px] font-semibold text-white shadow">ダン 直しました</span>
                </div>
              ) : null}
              <textarea rows={2} value={d.title} placeholder="テキスト" aria-label="タイトル"
                onFocus={() => { focused.current = `${p.id}:title`; }} onBlur={() => { focused.current = null; }}
                onChange={(e) => edit(p.id, 'title', e.target.value)}
                className="mt-2 block w-full resize-none rounded-md border border-transparent bg-transparent px-1 py-0.5 text-[16px] font-bold leading-snug outline-none placeholder:font-normal placeholder:text-muted-foreground/50 hover:border-border focus:border-sky-500" data-thumb-lineup-title />
            </div>
          );
        })}
      </div>
    </div>
  );
}
