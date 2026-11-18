'use client';

// 台本を読み上げで聞いて、その場で文を直す画面（2026-11-18、本人「文字で良いと思った台本でも聞いてみたらダメってことが
// 結構ある。聞いてチェックして、その場でテキストを編集したらその音声ですぐ再生できるやつほしい」）。
// - 台本の正本は Google ドキュメント。読むのは「◎台本」より下の黒い文だけで、見出し・［］の指示・青い文・サムネ〜前提と
//   狙いは読まない（画面には出す）。
// - 1文ずつの音声を順につないで鳴らす。文の頭と尻の無音は裏で削ってあり、文の後に短い間（段落・段の終わりは少し長く）が
//   付いている。倍速は <audio> の preservesPitch で声の高さを変えない。
// - 文を押すと直せる。「直して聞く」でドキュメントに書き戻し（変わった字だけ・太字はそのまま）、その文から鳴らし直す。
// - ドキュメントが別に直されたら（10秒ごとに見る）読み直し、変わった文だけ音声が作り直される。
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, Loader2, Pause, Play, SkipBack, SkipForward, Volume2 } from 'lucide-react';
import { toast } from 'sonner';

import { errorText, listenApi, type ListenDoc, type ListenUnit, type SayUnit } from '@/lib/script-listen-api';
import { cn } from '@/lib/utils';

const RATES = [1, 1.25, 1.5, 1.75, 2, 2.5, 3];
const RATE_KEY = 'script-listen-rate';
const VOICE_KEY = 'script-listen-voice';
const posKey = (doc: string) => `script-listen-pos-${doc}`;

type Clip = { url: string; el: HTMLAudioElement };

function setPitchKeep(el: HTMLAudioElement) {
  const a = el as HTMLAudioElement & { preservesPitch?: boolean; webkitPreservesPitch?: boolean; mozPreservesPitch?: boolean };
  a.preservesPitch = true;
  a.webkitPreservesPitch = true;
  a.mozPreservesPitch = true;
}

function fmtMinutes(sec: number) {
  if (sec < 60) return `${Math.max(1, Math.round(sec))}秒`;
  return `${Math.round(sec / 60)}分`;
}

export function ListenScreen({ docId }: { docId: string }) {
  const [doc, setDoc] = useState<ListenDoc | null>(null);
  const [loadError, setLoadError] = useState('');
  const [voice, setVoice] = useState<string>(() => (typeof window !== 'undefined' && localStorage.getItem(VOICE_KEY)) || 'aida-calm');
  const [rate, setRate] = useState<number>(() => Number((typeof window !== 'undefined' && localStorage.getItem(RATE_KEY)) || 1.5));
  const [cur, setCur] = useState(0);            // index into says
  const [playing, setPlaying] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const says = useMemo(() => (doc?.units.filter(u => u.kind === 'say') as SayUnit[]) || [], [doc]);
  const sayIndex = useMemo(() => new Map(says.map((u, i) => [u.n, i])), [says]);

  // refs the audio callbacks read (they outlive renders)
  const saysRef = useRef<SayUnit[]>([]);
  const rateRef = useRef(rate);
  const voiceRef = useRef(voice);
  const curRef = useRef(0);
  const playingRef = useRef(false);
  const clips = useRef(new Map<string, Promise<Clip>>());
  const active = useRef<HTMLAudioElement | null>(null);
  const token = useRef(0);                      // bumps on every jump so stale callbacks stop
  const lastUserScroll = useRef(0);
  const playFromRef = useRef<(i: number) => void>(() => {});
  useLayoutEffect(() => {
    saysRef.current = says;
    rateRef.current = rate;
    voiceRef.current = voice;
  }, [says, rate, voice]);

  const getClip = useCallback((u: SayUnit): Promise<Clip> => {
    const k = `${voiceRef.current}|${u.key}`;
    let p = clips.current.get(k);
    if (!p) {
      p = listenApi.clip(u, voiceRef.current).then(blob => {
        const url = URL.createObjectURL(blob);
        const el = new Audio();
        el.preload = 'auto';
        el.src = url;
        setPitchKeep(el);
        return { url, el };
      });
      p.catch(() => clips.current.delete(k));
      clips.current.set(k, p);
      // keep memory bounded: drop the oldest finished clips
      if (clips.current.size > 60) {
        const first = clips.current.keys().next().value as string;
        const old = clips.current.get(first);
        clips.current.delete(first);
        old?.then(c => { if (c.el !== active.current) URL.revokeObjectURL(c.url); }).catch(() => {});
      }
    }
    return p;
  }, []);

  const preload = useCallback((from: number) => {
    const list = saysRef.current;
    for (let i = from; i < Math.min(list.length, from + 4); i++) getClip(list[i]).catch(() => {});
  }, [getClip]);

  const sendAhead = useCallback((from: number) => {
    const list = saysRef.current;
    if (!list.length) return;
    const order = [...list.slice(from), ...list.slice(0, from)].map(u => ({ speak: u.speak, gap: u.gap }));
    listenApi.ahead(voiceRef.current, order).catch(() => {});
  }, []);

  const stop = useCallback(() => {
    token.current += 1;
    active.current?.pause();
    playingRef.current = false;
    setPlaying(false);
    setWaiting(false);
  }, []);

  const playFrom = useCallback(async (i: number) => {
    const list = saysRef.current;
    if (i < 0 || i >= list.length) { stop(); return; }
    const my = ++token.current;
    active.current?.pause();
    curRef.current = i;
    setCur(i);
    playingRef.current = true;
    setPlaying(true);
    try { localStorage.setItem(posKey(docId), String(list[i].start)); } catch { /* private mode */ }
    preload(i + 1);
    setWaiting(true);
    let clip: Clip;
    try {
      clip = await getClip(list[i]);
    } catch (e) {
      if (my !== token.current) return;
      setWaiting(false);
      toast.error(errorText(e));
      stop();
      return;
    }
    if (my !== token.current) return;
    setWaiting(false);
    const el = clip.el;
    active.current = el;
    el.currentTime = 0;
    setPitchKeep(el);
    el.playbackRate = rateRef.current;
    el.onended = () => { if (my === token.current) playFromRef.current(i + 1); };
    try {
      await el.play();
    } catch {
      if (my === token.current) stop();
      return;
    }
    if ('mediaSession' in navigator) {
      try {
        navigator.mediaSession.metadata = new MediaMetadata({ title: list[i].text.slice(0, 60), artist: list[i].section || '', album: '台本を聞く' });
      } catch { /* old browsers */ }
    }
  }, [docId, getClip, preload, stop]);

  useEffect(() => { playFromRef.current = (i: number) => void playFrom(i); }, [playFrom]);

  const toggle = useCallback(() => {
    if (playingRef.current) { stop(); return; }
    void playFrom(curRef.current);
  }, [playFrom, stop]);

  // ---- load the doc (and again when it changes)
  const load = useCallback(async (keepText?: { start: number; text: string }) => {
    try {
      const d = await listenApi.doc(docId, voiceRef.current);
      setDoc(d);
      setLoadError('');
      const list = d.units.filter(u => u.kind === 'say') as SayUnit[];
      saysRef.current = list;
      let at = 0;
      if (keepText) {
        at = list.findIndex(u => u.start === keepText.start);
        if (at < 0) at = list.findIndex(u => u.text === keepText.text);
        if (at < 0) at = Math.min(curRef.current, list.length - 1);
      } else {
        const saved = Number(localStorage.getItem(posKey(docId)) || NaN);
        at = Number.isFinite(saved) ? Math.max(0, list.findIndex(u => u.start >= saved)) : 0;
      }
      curRef.current = Math.max(0, at);
      setCur(curRef.current);
      sendAhead(curRef.current);
      return d;
    } catch (e) {
      setLoadError(errorText(e));
      return null;
    }
  }, [docId, sendAhead]);

  useEffect(() => { void load(); }, [load, voice]);

  useEffect(() => {
    const t = window.setInterval(async () => {
      if (!doc || editing !== null || saving) return;
      try {
        const { version } = await listenApi.version(docId);
        if (version && doc.version && version !== doc.version) {
          const here = saysRef.current[curRef.current];
          const wasPlaying = playingRef.current;
          stop();
          const d = await load(here ? { start: here.start, text: here.text } : undefined);
          if (d) {
            toast('ドキュメントの直しを読み込みました');
            if (wasPlaying) void playFrom(curRef.current);
          }
        }
      } catch { /* try again next time */ }
    }, 10000);
    return () => window.clearInterval(t);
  }, [doc, docId, editing, saving, load, playFrom, stop]);

  // speed and voice
  useEffect(() => {
    try { localStorage.setItem(RATE_KEY, String(rate)); } catch { /* ignore */ }
    if (active.current) { setPitchKeep(active.current); active.current.playbackRate = rate; }
  }, [rate]);
  const changeVoice = (v: string) => {
    stop();
    try { localStorage.setItem(VOICE_KEY, v); } catch { /* ignore */ }
    setVoice(v);
  };

  // media keys / lock screen
  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    const ms = navigator.mediaSession;
    ms.setActionHandler('play', () => { if (!playingRef.current) void playFrom(curRef.current); });
    ms.setActionHandler('pause', () => stop());
    ms.setActionHandler('previoustrack', () => void playFrom(Math.max(0, curRef.current - 1)));
    ms.setActionHandler('nexttrack', () => void playFrom(curRef.current + 1));
    return () => { for (const a of ['play', 'pause', 'previoustrack', 'nexttrack'] as const) ms.setActionHandler(a, null); };
  }, [playFrom, stop]);

  // keyboard on the PC
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (editing !== null || (t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.tagName === 'SELECT'))) return;
      if (e.code === 'Space') { e.preventDefault(); toggle(); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); void playFrom(curRef.current + 1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); void playFrom(Math.max(0, curRef.current - 1)); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editing, playFrom, toggle]);

  // keep the sentence being read in view, unless the owner is scrolling around
  useEffect(() => {
    if (!says[cur] || Date.now() - lastUserScroll.current < 5000 || editing !== null) return;
    document.getElementById(`say-${says[cur].n}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [cur, says, editing]);

  useEffect(() => () => { token.current += 1; active.current?.pause(); }, []);

  const openEdit = (i: number) => {
    stop();
    curRef.current = i;
    setCur(i);
    setEditing(i);
    setDraft(says[i].text);
  };

  const saveEdit = async () => {
    if (editing === null) return;
    const u = says[editing];
    const next = draft.replace(/\s*\n+\s*/g, '').trim();
    if (!next) { toast.error('空の文にはできません'); return; }
    setSaving(true);
    try {
      if (next !== u.text) await listenApi.edit(docId, u.text, next, u.start);
      setEditing(null);
      const d = await load({ start: u.start, text: next });
      if (d) void playFrom(curRef.current);
    } catch (e) {
      toast.error(errorText(e));
      setEditing(null);
      await load({ start: u.start, text: u.text });
    } finally {
      setSaving(false);
    }
  };

  const remaining = useMemo(() => {
    let sec = 0;
    for (let i = cur; i < says.length; i++) sec += says[i].seconds ?? says[i].speak.length * 0.14 + 0.25;
    return sec / rate;
  }, [cur, rate, says]);

  if (loadError && !doc) {
    return <div className="p-6 text-[15px] text-red-700">{loadError}</div>;
  }
  if (!doc) {
    return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" />台本を読んでいます…</div>;
  }

  const top: ListenUnit[] = [];
  const body: ListenUnit[] = [];
  let inScript = !doc.units.some(u => u.kind === 'heading' && u.level === 1 && u.text.startsWith('◎台本'));
  for (const u of doc.units) {
    if (u.kind === 'title') continue;
    if (u.kind === 'heading' && u.level === 1) { inScript = u.text.startsWith('◎台本'); if (!inScript) top.push(u); continue; }
    (inScript ? body : top).push(u);
  }

  return (
    <div className="flex h-dvh flex-col bg-[#faf8f4] text-stone-900">
      <header className="shrink-0 border-b border-stone-200 bg-white/90 px-3 py-2 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-3xl items-center gap-2">
          <Volume2 className="h-4 w-4 shrink-0 text-amber-700" />
          <div className="min-w-0 flex-1 truncate text-[14px] font-semibold">{doc.title}</div>
          <select
            aria-label="声"
            value={voice}
            onChange={e => changeVoice(e.target.value)}
            className="max-w-[9.5rem] rounded-md border border-stone-300 bg-white px-1.5 py-1 text-[12px]"
          >
            {doc.voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          <a
            href={`https://docs.google.com/document/d/${doc.doc_id}/edit`}
            target="_blank"
            rel="noreferrer"
            className="flex shrink-0 items-center gap-1 rounded-md border border-stone-300 px-2 py-1 text-[12px] text-stone-700"
          >
            <ExternalLink className="h-3.5 w-3.5" />ドキュメント
          </a>
        </div>
      </header>

      <div
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
        onWheel={() => { lastUserScroll.current = Date.now(); }}
        onTouchMove={() => { lastUserScroll.current = Date.now(); }}
      >
        <div className="mx-auto max-w-3xl px-3 pb-40 pt-3 sm:px-6">
          {top.length > 0 && (
            <details className="mb-4 rounded-lg border border-stone-200 bg-white/70 px-3 py-2 text-[13px] text-stone-500">
              <summary className="cursor-pointer select-none">サムネ・タイトル・前提と狙い（読みません）</summary>
              <div className="mt-2 space-y-1">
                {top.map((u, k) => (
                  <div key={k} className={u.kind === 'heading' ? 'pt-1 font-semibold text-stone-600' : ''}>{u.text}</div>
                ))}
              </div>
            </details>
          )}
          {body.map(u => {
            if (u.kind === 'heading') {
              const firstSay = says.findIndex(s => s.n > u.n);
              return (
                <button
                  key={u.n}
                  type="button"
                  onClick={() => firstSay >= 0 && void playFrom(firstSay)}
                  className={cn(
                    'block w-full text-left',
                    u.level === 2 ? 'mt-6 mb-2 border-b border-stone-300 pb-1 text-[16px] font-bold text-stone-800' : 'mt-4 mb-1.5 text-[14px] font-semibold text-amber-800',
                  )}
                >
                  {u.text}
                </button>
              );
            }
            if (u.kind === 'note') {
              return <div key={u.n} className="my-1.5 text-[13px] leading-relaxed text-sky-700/80">{u.text}</div>;
            }
            if (u.kind !== 'say') return null;
            const i = sayIndex.get(u.n) ?? 0;
            const on = i === cur;
            if (editing === i) {
              return (
                <div key={u.n} id={`say-${u.n}`} className="my-2 rounded-lg border-2 border-amber-400 bg-white p-2 shadow-sm">
                  <textarea
                    autoFocus
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void saveEdit(); }
                      if (e.key === 'Escape') setEditing(null);
                    }}
                    rows={Math.min(8, Math.max(2, Math.ceil(draft.length / 28)))}
                    className="w-full resize-none rounded-md border border-stone-200 p-2 text-[16px] leading-relaxed outline-none focus:border-amber-500"
                  />
                  {u.locked && (
                    <div className="mt-1 text-[12px] text-red-700">この文には提案モードの直しが入っているので、ここでは直せません。</div>
                  )}
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={saving || u.locked}
                      onClick={() => void saveEdit()}
                      className="flex items-center gap-1 rounded-md bg-amber-600 px-3 py-2 text-[14px] font-semibold text-white disabled:opacity-50"
                    >
                      {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}直して聞く
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => { setEditing(null); void playFrom(i); }}
                      className="rounded-md border border-stone-300 bg-white px-3 py-2 text-[14px]"
                    >
                      ここから聞く
                    </button>
                    <button type="button" disabled={saving} onClick={() => setEditing(null)} className="rounded-md px-3 py-2 text-[14px] text-stone-500">
                      やめる
                    </button>
                  </div>
                </div>
              );
            }
            return (
              <button
                key={u.n}
                id={`say-${u.n}`}
                type="button"
                data-say={i}
                onClick={() => openEdit(i)}
                className={cn(
                  'my-0.5 block w-full rounded-md px-2 py-1.5 text-left text-[16px] leading-relaxed transition-colors',
                  u.bold && 'font-bold',
                  on ? 'bg-amber-200/80 text-stone-950' : 'hover:bg-stone-200/50',
                  u.gap !== 's' && 'mb-2',
                )}
              >
                {u.text}
              </button>
            );
          })}
          <div className="mt-8 text-center text-[12px] text-stone-400">文を押すと直せます。直すとドキュメントにも入ります。</div>
        </div>
      </div>

      <div className="shrink-0 border-t border-stone-200 bg-white/95 px-3 pb-[max(env(safe-area-inset-bottom),0.5rem)] pt-2 backdrop-blur sm:px-6">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-center justify-between gap-2 text-[12px] text-stone-500">
            <span>{says.length ? `${cur + 1} / ${says.length}文` : '読む文がありません'}</span>
            <span className="flex items-center gap-1">
              {waiting && <><Loader2 className="h-3 w-3 animate-spin" />声を作っています</>}
              {!waiting && says.length > 0 && `残り約${fmtMinutes(remaining)}`}
            </span>
          </div>
          <div className="mt-1.5 flex items-center justify-center gap-3">
            <button type="button" aria-label="前の文" onClick={() => void playFrom(Math.max(0, cur - 1))} className="rounded-full p-2.5 text-stone-700 active:bg-stone-200">
              <SkipBack className="h-6 w-6" />
            </button>
            <button
              type="button"
              aria-label={playing ? '止める' : '聞く'}
              onClick={toggle}
              disabled={!says.length}
              className="flex h-14 w-14 items-center justify-center rounded-full bg-amber-600 text-white shadow active:bg-amber-700 disabled:opacity-40"
            >
              {playing ? <Pause className="h-7 w-7" /> : <Play className="ml-0.5 h-7 w-7" />}
            </button>
            <button type="button" aria-label="次の文" onClick={() => void playFrom(cur + 1)} className="rounded-full p-2.5 text-stone-700 active:bg-stone-200">
              <SkipForward className="h-6 w-6" />
            </button>
          </div>
          <div className="mt-2 flex items-center justify-center gap-1 overflow-x-auto">
            {RATES.map(r => (
              <button
                key={r}
                type="button"
                onClick={() => setRate(r)}
                className={cn(
                  'shrink-0 rounded-full border px-2.5 py-1 text-[13px] tabular-nums',
                  r === rate ? 'border-amber-600 bg-amber-600 text-white' : 'border-stone-300 bg-white text-stone-700',
                )}
              >
                {r}倍
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
