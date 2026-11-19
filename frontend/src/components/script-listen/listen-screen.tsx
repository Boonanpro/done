'use client';

// 台本を読み上げで聞いて、その場で直し、コメントでダンとやり取りする画面（2026-11-18、11-19 に作り直し）。
// - 台本の正本は Google ドキュメント。読むのは「◎台本」より下の黒い文だけ。サムネ・タイトル・前提と狙いは上に見せる（読まない）。
// - 再生: 1文ずつの音声を順につなぐ。どの文の後も同じ短い間で、段落や段の切れ目でも止まらない（11/19 本人「全部一気に
//   再生できるように」）。次の文は今の文の後ろの無音のうちに鳴らし始めるので、文と文の間に待ちが入らない。倍速でも声の高さは同じ。
// - 直す: 本文はそのまま書き換えられる（四角い入力欄は無い）。PC は文を押すとそこから鳴り、そのまま打てる。スマホは
//   鳴っている文をもう一度押すと打てる。打ち始めると止まり、Enter か外を押すとドキュメントに書き戻して、その文から鳴らし直す。
// - コメント: 文字を選ぶか、下の「コメント」で今の文に書く。ドキュメントのコメントとして入るので、ダンが返事と直しをし、
//   学習にも入る。ダンの直しは提案（緑＝足す、赤の線＝消す）で出て、ここで承認・却下できる。
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, Loader2, MessageSquare, MessageSquarePlus, Pause, Play, SkipBack, SkipForward, Volume2, X } from 'lucide-react';
import { toast } from 'sonner';

import {
  errorText, listenApi, type ListenDoc, type ListenUnit, type SayUnit, type Suggestion, type Thread,
} from '@/lib/script-listen-api';
import { cn } from '@/lib/utils';

import { Composer, SegText, SuggestionCard, ThreadCard } from './listen-cards';

const RATES = [1, 1.25, 1.5, 1.75, 2, 2.5, 3];
const RATE_KEY = 'script-listen-rate';
const VOICE_KEY = 'script-listen-voice';
const posKey = (doc: string) => `script-listen-pos-${doc}`;
// Every clip ends with 0.16 s of silence (+0.03 s kept after the voice). The next clip starts this many seconds of the
// clip before its end, so only silence is cut and the switch to the next clip happens inside the pause.
const LEAD = 0.17;

type Clip = { url: string; el: HTMLAudioElement };
type Sheet = { kind: 'threads'; ids: string[] } | { kind: 'suggestion'; id: string } | { kind: 'compose' } | { kind: 'all' } | null;
type Draft = { quote: string; n: number; start: number | null };

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

const squash = (s: string) => s.replace(/\s+/g, '');

/** Which unit each comment belongs to: where its quoted words are in the text (nearest to where it was made). */
function placeThreads(units: ListenUnit[], threads: Thread[]) {
  const parts: { n: number; from: number; start?: number }[] = [];
  let all = '';
  for (const u of units) {
    if (u.kind === 'image') continue;
    // With the struck-through words too: a comment's words are often the ones Dan's suggestion takes out (11/19).
    const segs = 'segs' in u ? u.segs : undefined;
    const t = squash(segs?.length ? segs.map(x => x.t).join('') : u.text);
    parts.push({ n: u.n, from: all.length, start: u.kind === 'say' ? u.start : undefined });
    all += t;
  }
  const unitAt = (pos: number) => {
    let hit = parts[0];
    for (const p of parts) { if (p.from <= pos) hit = p; else break; }
    return hit;
  };
  const place = new Map<string, number>();
  for (const th of threads) {
    const q = squash(th.quote || '');
    if (!q) continue;
    for (const probe of [q, q.slice(0, 24), q.slice(-24)]) {
      if (probe.length < 2) continue;
      const found: number[] = [];
      for (let i = all.indexOf(probe); i >= 0 && found.length < 20; i = all.indexOf(probe, i + 1)) found.push(i);
      if (!found.length) continue;
      let best = unitAt(found[0]);
      if (found.length > 1 && th.start != null) {
        let gap = Infinity;
        for (const f of found) {
          const p = unitAt(f);
          const d = p.start != null ? Math.abs(p.start - th.start) : Infinity;
          if (d < gap) { gap = d; best = p; }
        }
      }
      place.set(th.id, best.n);
      break;
    }
  }
  return place;
}

export function ListenScreen({ docId }: { docId: string }) {
  const [doc, setDoc] = useState<ListenDoc | null>(null);
  const [loadError, setLoadError] = useState('');
  const [voice, setVoice] = useState<string>(() => (typeof window !== 'undefined' && localStorage.getItem(VOICE_KEY)) || 'aida-calm');
  const [rate, setRate] = useState<number>(() => Number((typeof window !== 'undefined' && localStorage.getItem(RATE_KEY)) || 1.5));
  const [cur, setCur] = useState(0);            // index into says
  const [playing, setPlaying] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [armed, setArmed] = useState<number | null>(null);   // touch: the sentence that takes typing (unit n)
  const [threads, setThreads] = useState<Thread[]>([]);
  const [canComment, setCanComment] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [active, setActive] = useState<string | null>(null);  // thread or suggestion id
  const [draft, setDraft] = useState<Draft | null>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [selBtn, setSelBtn] = useState<(Draft & { x: number; y: number }) | null>(null);
  const [wide, setWide] = useState(() => typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches);
  const [touch, setTouch] = useState(() => typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches);
  const [remount, setRemount] = useState(0);    // bumps to throw away typed text the owner cancelled

  const says = useMemo(() => (doc?.units.filter(u => u.kind === 'say') as SayUnit[]) || [], [doc]);
  const sayIndex = useMemo(() => new Map(says.map((u, i) => [u.n, i])), [says]);

  const saysRef = useRef<SayUnit[]>([]);
  const rateRef = useRef(rate);
  const voiceRef = useRef(voice);
  const curRef = useRef(0);
  const playingRef = useRef(false);
  const clips = useRef(new Map<string, Promise<Clip>>());
  const active_ = useRef<HTMLAudioElement | null>(null);
  const tick = useRef<number | null>(null);
  const token = useRef(0);
  const lastUserScroll = useRef(0);
  const playFromRef = useRef<(i: number, natural?: boolean) => void>(() => {});
  const editingRef = useRef<{ n: number; dirty: boolean } | null>(null);
  const saveChain = useRef<Promise<unknown>>(Promise.resolve());
  const contentRef = useRef<HTMLDivElement | null>(null);
  const marginRef = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    saysRef.current = says;
    rateRef.current = rate;
    voiceRef.current = voice;
  }, [says, rate, voice]);

  useEffect(() => {
    const w = window.matchMedia('(min-width: 1024px)');
    const t = window.matchMedia('(pointer: coarse)');
    const set = () => { setWide(w.matches); setTouch(t.matches); };
    w.addEventListener('change', set);
    t.addEventListener('change', set);
    return () => { w.removeEventListener('change', set); t.removeEventListener('change', set); };
  }, []);

  // ---------------------------------------------------------------- audio
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
      if (clips.current.size > 60) {
        const first = clips.current.keys().next().value as string;
        const old = clips.current.get(first);
        clips.current.delete(first);
        old?.then(c => { if (c.el !== active_.current) URL.revokeObjectURL(c.url); }).catch(() => {});
      }
    }
    return p;
  }, []);

  const preload = useCallback((from: number) => {
    const list = saysRef.current;
    for (let i = from; i < Math.min(list.length, from + 5); i++) getClip(list[i]).catch(() => {});
  }, [getClip]);

  const sendAhead = useCallback((from: number) => {
    const list = saysRef.current;
    if (!list.length) return;
    const order = [...list.slice(from), ...list.slice(0, from)].map(u => ({ speak: u.speak, gap: u.gap }));
    listenApi.ahead(voiceRef.current, order).catch(() => {});
  }, []);

  const clearTick = () => { if (tick.current != null) { window.clearInterval(tick.current); tick.current = null; } };

  const stop = useCallback(() => {
    token.current += 1;
    clearTick();
    active_.current?.pause();
    playingRef.current = false;
    setPlaying(false);
    setWaiting(false);
  }, []);

  const playFrom = useCallback(async (i: number, natural = false) => {
    const list = saysRef.current;
    if (i < 0 || i >= list.length) { stop(); return; }
    const my = ++token.current;
    clearTick();
    // A jump stops the old sentence now; going on to the next one lets the old one's closing silence run out.
    if (!natural) active_.current?.pause();
    curRef.current = i;
    setCur(i);
    playingRef.current = true;
    setPlaying(true);
    try { localStorage.setItem(posKey(docId), String(list[i].start)); } catch { /* private mode */ }
    preload(i + 1);
    let clip: Clip;
    const ready = getClip(list[i]);
    const slow = window.setTimeout(() => { if (my === token.current) setWaiting(true); }, 120);
    try {
      clip = await ready;
    } catch (e) {
      window.clearTimeout(slow);
      if (my !== token.current) return;
      setWaiting(false);
      toast.error(errorText(e));
      stop();
      return;
    }
    window.clearTimeout(slow);
    if (my !== token.current) return;
    setWaiting(false);
    const prev = active_.current;
    const el = clip.el;
    active_.current = el;
    if (prev && prev !== el) prev.pause();
    el.currentTime = 0;
    setPitchKeep(el);
    el.playbackRate = rateRef.current;
    const next = () => { if (my === token.current) { clearTick(); playFromRef.current(i + 1, true); } };
    el.onended = next;
    try {
      await el.play();
    } catch {
      if (my === token.current) stop();
      return;
    }
    if (my !== token.current) return;
    // Start the next sentence inside this one's closing silence (onended stays as the fallback when the page is hidden
    // and timers slow down).
    tick.current = window.setInterval(() => {
      if (my !== token.current) { clearTick(); return; }
      const d = el.duration;
      if (Number.isFinite(d) && d > LEAD && d - el.currentTime <= LEAD) next();
    }, 15);
    if ('mediaSession' in navigator) {
      try {
        navigator.mediaSession.metadata = new MediaMetadata({ title: list[i].text.slice(0, 60), artist: list[i].section || '', album: '台本を聞く' });
      } catch { /* old browsers */ }
    }
  }, [docId, getClip, preload, stop]);

  useEffect(() => { playFromRef.current = (i: number, natural?: boolean) => void playFrom(i, natural); }, [playFrom]);

  const toggle = useCallback(() => {
    if (playingRef.current) { stop(); return; }
    void playFrom(curRef.current);
  }, [playFrom, stop]);

  // ---------------------------------------------------------------- doc and comments
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

  const loadComments = useCallback(async () => {
    try {
      const c = await listenApi.comments(docId);
      setThreads(c.threads);
      setCanComment(c.can_comment);
      return c.threads;
    } catch { return null; }
  }, [docId]);
  useEffect(() => {
    const t = window.setTimeout(() => void loadComments(), 0);
    return () => window.clearTimeout(t);
  }, [loadComments]);

  const busy = threads.some(t => t.working === 'pending' || t.working === 'running');
  useEffect(() => {
    const t = window.setInterval(() => { if (!document.hidden) void loadComments(); }, busy ? 4000 : 12000);
    return () => window.clearInterval(t);
  }, [busy, loadComments]);

  // The doc changed elsewhere (Dan's fix, Google Docs): read it again, unless the owner is typing here.
  useEffect(() => {
    const t = window.setInterval(async () => {
      if (!doc || editingRef.current || saving || document.hidden) return;
      try {
        const { version } = await listenApi.version(docId);
        if (version && doc.version && version !== doc.version && !editingRef.current) {
          const here = saysRef.current[curRef.current];
          const wasPlaying = playingRef.current;
          if (wasPlaying) stop();
          const d = await load(here ? { start: here.start, text: here.text } : undefined);
          if (d && wasPlaying) void playFrom(curRef.current);
        }
      } catch { /* next time */ }
    }, 8000);
    return () => window.clearInterval(t);
  }, [doc, docId, saving, load, playFrom, stop]);

  // ---------------------------------------------------------------- speed, voice, keys
  useEffect(() => {
    try { localStorage.setItem(RATE_KEY, String(rate)); } catch { /* ignore */ }
    if (active_.current) { setPitchKeep(active_.current); active_.current.playbackRate = rate; }
  }, [rate]);
  const changeVoice = (v: string) => {
    stop();
    try { localStorage.setItem(VOICE_KEY, v); } catch { /* ignore */ }
    setVoice(v);
  };

  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    const ms = navigator.mediaSession;
    ms.setActionHandler('play', () => { if (!playingRef.current) void playFrom(curRef.current); });
    ms.setActionHandler('pause', () => stop());
    ms.setActionHandler('previoustrack', () => void playFrom(Math.max(0, curRef.current - 1)));
    ms.setActionHandler('nexttrack', () => void playFrom(curRef.current + 1));
    return () => { for (const a of ['play', 'pause', 'previoustrack', 'nexttrack'] as const) ms.setActionHandler(a, null); };
  }, [playFrom, stop]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.tagName === 'SELECT')) return;
      if (e.code === 'Space') { e.preventDefault(); toggle(); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); void playFrom(curRef.current + 1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); void playFrom(Math.max(0, curRef.current - 1)); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [playFrom, toggle]);

  useEffect(() => {
    if (!says[cur] || Date.now() - lastUserScroll.current < 5000 || editingRef.current) return;
    document.getElementById(`u-${says[cur].n}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [cur, says]);

  useEffect(() => () => { token.current += 1; clearTick(); active_.current?.pause(); }, []);

  // ---------------------------------------------------------------- editing in place
  const save = useCallback((u: SayUnit, el: HTMLElement) => {
    const next = (el.textContent || '').replace(/\s*\n+\s*/g, '').trim();
    editingRef.current = null;
    setArmed(null);
    if (next === u.text) {
      setRemount(r => r + 1);
      return;
    }
    const run = async () => {
      setSaving(true);
      try {
        await listenApi.edit(docId, u.text, next, u.start);
        const d = await load({ start: u.start, text: next });
        if (d) void playFrom(curRef.current);
      } catch (e) {
        toast.error(errorText(e));
        await load({ start: u.start, text: u.text });
      } finally {
        setSaving(false);
        setRemount(r => r + 1);
      }
    };
    saveChain.current = saveChain.current.then(run, run);
  }, [docId, load, playFrom]);

  const onSayClick = (i: number, u: SayUnit) => {
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;          // selecting words to comment on
    if (editingRef.current?.dirty) return;
    if (touch) {
      if (armed === u.n) return;                   // second tap: the caret goes in, keyboard opens
      setArmed(u.n);
      void playFrom(i);
      return;
    }
    if (!(playingRef.current && curRef.current === i)) void playFrom(i);
  };

  // ---------------------------------------------------------------- comments and suggestions
  const units = useMemo(() => doc?.units || [], [doc]);
  const visibleThreads = useMemo(() => threads.filter(t => showResolved || !t.resolved), [threads, showResolved]);
  const place = useMemo(() => placeThreads(units, threads), [units, threads]);
  const threadsAt = useMemo(() => {
    const m = new Map<number, Thread[]>();
    for (const t of visibleThreads) {
      const n = place.get(t.id);
      if (n == null) continue;
      m.set(n, [...(m.get(n) || []), t]);
    }
    return m;
  }, [visibleThreads, place]);
  const unplaced = visibleThreads.filter(t => !place.has(t.id));
  const suggestions = doc?.suggestions || [];
  const openCount = threads.filter(t => !t.resolved).length;

  const openDraft = (d: Draft) => {
    if (!canComment) { toast.error('お客さんも開けるドキュメントなので、ここからはコメントできません。作業用の台本で書いてください。'); return; }
    stop();
    setDraft(d);
    setSelBtn(null);
    window.getSelection()?.removeAllRanges();
    if (!wide) setSheet({ kind: 'compose' });
  };

  const sendComment = async (text: string) => {
    if (!draft) return;
    try {
      const at = units.find(u => u.n === draft.n);
      const sentence = at && 'text' in at ? at.text : '';
      await listenApi.addComment(docId, { text, quote: draft.quote, start: draft.start, sentence });
      setDraft(null);
      setSheet(null);
      const list = await loadComments();
      const made = list?.slice().reverse().find(t => t.quote === draft.quote);
      if (made) setActive(made.id);
      toast('コメントしました。ダンが返事をします');
    } catch (e) { toast.error(errorText(e)); throw e; }
  };

  const sendReply = (t: Thread) => async (text: string) => {
    try { await listenApi.reply(docId, t.id, text); await loadComments(); } catch (e) { toast.error(errorText(e)); throw e; }
  };
  const settle = (t: Thread) => async (reopen: boolean) => {
    try { await listenApi.settle(docId, t.id, reopen); await loadComments(); } catch (e) { toast.error(errorText(e)); }
  };
  const decide = useCallback(async (s: Suggestion, accept: boolean) => {
    try {
      await listenApi.decide(docId, s.id, accept);
      const here = saysRef.current[curRef.current];
      await load(here ? { start: here.start, text: here.text } : undefined);
      setSheet(null);
      setActive(null);
    } catch (e) {
      toast.error(errorText(e));
      await load();
    }
  }, [docId, load]);

  const focusUnit = useCallback((n: number) => {
    lastUserScroll.current = Date.now();
    document.getElementById(`u-${n}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, []);
  const pickSuggestion = (id: string) => {
    setActive(id);
    if (!wide) setSheet({ kind: 'suggestion', id });
  };
  const pickThreads = (list: Thread[]) => {
    setActive(list[0]?.id || null);
    if (!wide) setSheet({ kind: 'threads', ids: list.map(t => t.id) });
  };

  // A floating 「コメント」 button next to selected words.
  useEffect(() => {
    const onSel = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount) { setSelBtn(null); return; }
      const text = sel.toString().replace(/\s+/g, ' ').trim();
      const node = sel.anchorNode instanceof Element ? sel.anchorNode : sel.anchorNode?.parentElement;
      const host = node?.closest('[data-n]') as HTMLElement | null;
      if (!text || !host || !contentRef.current?.contains(host)) { setSelBtn(null); return; }
      const n = Number(host.dataset.n);
      const u = units.find(x => x.n === n);
      const rect = sel.getRangeAt(0).getBoundingClientRect();
      setSelBtn({ quote: text.slice(0, 400), n, start: u?.kind === 'say' ? u.start : null, x: rect.right, y: rect.top });
    };
    document.addEventListener('selectionchange', onSel);
    return () => document.removeEventListener('selectionchange', onSel);
  }, [units]);

  // Cards in the right margin sit beside the words they are about (PC).
  const cardRefs = useRef(new Map<string, HTMLDivElement>());
  const layoutCards = useCallback(() => {
    const box = contentRef.current;
    if (!box || !marginRef.current) return;
    const top0 = box.getBoundingClientRect().top;
    const items: { el: HTMLDivElement; top: number; key: string }[] = [];
    cardRefs.current.forEach((el, key) => {
      const n = Number(el.dataset.anchor);
      const a = document.getElementById(`u-${n}`);
      if (!a) return;
      items.push({ el, key, top: a.getBoundingClientRect().top - top0 });
    });
    items.sort((a, b) => a.top - b.top || (a.key === 'draft' ? -1 : 0));
    let floor = 0;
    for (const it of items) {
      const top = Math.max(it.top, floor);
      it.el.style.top = `${top}px`;
      floor = top + it.el.offsetHeight + 8;
    }
    marginRef.current.style.minHeight = `${floor}px`;
  }, []);
  useLayoutEffect(() => { if (wide) layoutCards(); });
  useEffect(() => {
    if (!wide || !contentRef.current) return;
    const ro = new ResizeObserver(() => layoutCards());
    ro.observe(contentRef.current);
    return () => ro.disconnect();
  }, [wide, layoutCards, doc]);

  const remaining = useMemo(() => {
    let sec = 0;
    for (let i = cur; i < says.length; i++) sec += Math.max(0.1, (says[i].seconds ?? says[i].speak.length * 0.14 + 0.25) - LEAD);
    return sec / rate;
  }, [cur, rate, says]);

  if (loadError && !doc) {
    return <div className="p-6 text-[15px] text-red-700">{loadError}</div>;
  }
  if (!doc) {
    return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" />台本を読んでいます…</div>;
  }

  // ---------------------------------------------------------------- layout of the text
  const title = units.find(u => u.kind === 'title');
  const top: ListenUnit[] = [];
  const body: ListenUnit[] = [];
  let inScript = !units.some(u => u.kind === 'heading' && u.level === 1 && u.text.startsWith('◎台本'));
  for (const u of units) {
    if (u.kind === 'title') continue;
    if (u.kind === 'heading' && u.level === 1) { inScript = u.text.startsWith('◎台本'); if (!inScript) top.push(u); continue; }
    (inScript ? body : top).push(u);
  }
  // Sentences of one paragraph flow together like the doc.
  type Block = { kind: 'para'; key: string; items: ListenUnit[] } | { kind: 'one'; key: string; u: ListenUnit };
  const blocks: Block[] = [];
  for (const u of body) {
    const para = (u.kind === 'say' || u.kind === 'note' || u.kind === 'gone') ? u.para : undefined;
    const last = blocks[blocks.length - 1];
    if (para != null && u.kind !== 'gone' && last?.kind === 'para' && (last.items[0] as { para?: number }).para === para) last.items.push(u);
    else if (para != null && u.kind !== 'gone') blocks.push({ kind: 'para', key: `p${u.n}`, items: [u] });
    else blocks.push({ kind: 'one', key: `u${u.n}`, u });
  }

  const commentMark = (n: number) => {
    const list = threadsAt.get(n);
    if (!list?.length) return null;
    return (
      <button
        type="button"
        contentEditable={false}
        onClick={e => { e.stopPropagation(); pickThreads(list); }}
        className="mx-0.5 inline-flex translate-y-[-1px] items-center gap-0.5 rounded-full bg-yellow-300/80 px-1.5 align-middle text-[11px] font-semibold text-stone-800"
        aria-label="コメント"
      >
        <MessageSquare className="h-3 w-3" />{list.length > 1 ? list.length : ''}
      </button>
    );
  };

  const renderUnit = (u: ListenUnit) => {
    const marked = threadsAt.has(u.n);
    if (u.kind === 'say') {
      const i = sayIndex.get(u.n) ?? 0;
      const on = i === cur;
      const editable = !u.locked && !saving && (!touch || armed === u.n);
      const hasSug = u.segs?.some(s => s.ins || s.del);
      return (
        <span key={`${u.n}-${u.key}-${remount}`} className="inline">
          <span
            id={`u-${u.n}`}
            data-n={u.n}
            contentEditable={editable}
            suppressContentEditableWarning
            spellCheck={false}
            onClick={() => onSayClick(i, u)}
            onInput={() => {
              // Only typing counts as editing: a click to listen leaves the caret here, and that must not stop the
              // doc from being read again or the screen from following the voice.
              editingRef.current = { n: u.n, dirty: true };
              if (playingRef.current) stop();
            }}
            onBlur={e => { if (editingRef.current?.dirty) save(u, e.currentTarget); else editingRef.current = null; }}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.blur(); }
              // Space before any typing still means play / pause (the caret sits here after a click to listen).
              if (e.code === 'Space' && !e.nativeEvent.isComposing && !editingRef.current?.dirty) { e.preventDefault(); toggle(); }
              if (e.key === 'Escape') {
                editingRef.current = null;
                setRemount(r => r + 1);
                e.currentTarget.blur();
              }
            }}
            className={cn(
              'rounded-[3px] px-[1px] py-0.5 outline-none transition-colors [box-decoration-break:clone]',
              u.bold && 'font-bold',
              on ? 'bg-amber-200/80 text-stone-950' : marked ? 'bg-yellow-100' : 'hover:bg-stone-200/50',
              active && u.segs?.some(s => s.ins === active || s.del === active) && 'ring-2 ring-emerald-400',
              editable && 'focus:bg-white focus:ring-2 focus:ring-amber-400',
              touch && armed === u.n && 'ring-1 ring-amber-400',
            )}
          >
            {hasSug ? <SegText segs={u.segs || []} onSuggestion={pickSuggestion} /> : u.text}
          </span>
          {commentMark(u.n)}{' '}
        </span>
      );
    }
    if (u.kind === 'note') {
      return (
        <span key={u.n} id={`u-${u.n}`} data-n={u.n} className={cn('text-[14px] text-sky-700/80', marked && 'bg-yellow-100')}>
          {u.segs ? <SegText segs={u.segs} onSuggestion={pickSuggestion} /> : u.text}{commentMark(u.n)}{' '}
        </span>
      );
    }
    return null;
  };

  const renderBlock = (b: Block) => {
    if (b.kind === 'para') {
      const onlyNotes = b.items.every(u => u.kind === 'note');
      return <p key={b.key} className={cn('my-2.5 text-[16.5px] leading-[1.95]', onlyNotes && 'text-[14px] leading-relaxed')}>{b.items.map(renderUnit)}</p>;
    }
    const u = b.u;
    if (u.kind === 'heading') {
      const firstSay = says.findIndex(s => s.n > u.n);
      return (
        <div
          key={b.key}
          id={`u-${u.n}`}
          data-n={u.n}
          onClick={() => firstSay >= 0 && void playFrom(firstSay)}
          className={cn(
            'cursor-pointer',
            u.level === 2 ? 'mb-2 mt-8 border-b border-stone-300 pb-1 text-[17px] font-bold text-stone-800' : 'mb-1 mt-5 text-[15px] font-semibold text-amber-800',
            threadsAt.has(u.n) && 'bg-yellow-100',
          )}
        >
          {u.segs?.some(s => s.ins || s.del) ? <SegText segs={u.segs} onSuggestion={pickSuggestion} /> : u.text}{commentMark(u.n)}
        </div>
      );
    }
    if (u.kind === 'gone') {
      return (
        <p key={b.key} id={`u-${u.n}`} data-n={u.n} className="my-2.5 text-[16px] leading-[1.95]">
          <SegText segs={u.segs} onSuggestion={pickSuggestion} />
        </p>
      );
    }
    if (u.kind === 'note' || u.kind === 'say') return <p key={b.key} className="my-2">{renderUnit(u)}</p>;
    return null;
  };

  const sheetThreads = sheet?.kind === 'threads' ? threads.filter(t => sheet.ids.includes(t.id)) : sheet?.kind === 'all' ? visibleThreads : [];
  const sheetSuggestion = sheet?.kind === 'suggestion' ? suggestions.find(s => s.id === sheet.id) : undefined;

  return (
    <div className="flex h-dvh flex-col bg-[#faf8f4] text-stone-900">
      <header className="shrink-0 border-b border-stone-200 bg-white/90 px-3 py-2 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-6xl items-center gap-2">
          <Volume2 className="h-4 w-4 shrink-0 text-amber-700" />
          <div className="min-w-0 flex-1 truncate text-[14px] font-semibold">{doc.title}</div>
          <button
            type="button"
            onClick={() => (wide ? setShowResolved(v => !v) : setSheet({ kind: 'all' }))}
            className="flex shrink-0 items-center gap-1 rounded-md border border-stone-300 px-2 py-1 text-[12px] text-stone-700"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            {wide ? (showResolved ? '解決済みを隠す' : `コメント ${openCount}`) : `コメント ${openCount}`}
          </button>
          <select
            aria-label="声"
            value={voice}
            onChange={e => changeVoice(e.target.value)}
            className="max-w-[8rem] rounded-md border border-stone-300 bg-white px-1.5 py-1 text-[12px]"
          >
            {doc.voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          <a
            href={`https://docs.google.com/document/d/${doc.doc_id}/edit`}
            target="_blank"
            rel="noreferrer"
            aria-label="ドキュメント"
            className="flex shrink-0 items-center gap-1 rounded-md border border-stone-300 px-2 py-1 text-[12px] text-stone-700"
          >
            <ExternalLink className="h-3.5 w-3.5" /><span className="hidden sm:inline">ドキュメント</span>
          </a>
        </div>
      </header>

      <div
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
        onWheel={() => { lastUserScroll.current = Date.now(); }}
        onTouchMove={() => { lastUserScroll.current = Date.now(); }}
      >
        <div className="mx-auto flex max-w-6xl gap-6 px-3 pb-44 pt-4 sm:px-6">
          <div ref={contentRef} className="relative min-w-0 max-w-3xl flex-1">
            {title && title.kind === 'title' && <h1 className="mb-3 text-[20px] font-bold leading-snug">{title.text}</h1>}
            {top.length > 0 && (
              <section className="mb-6 rounded-lg border border-stone-200 bg-white/80 px-4 py-3">
                {top.map(u => {
                  if (u.kind === 'image') return <img key={u.n} src={u.src} alt="サムネ" referrerPolicy="no-referrer" className="my-2 w-full max-w-md rounded-md border border-stone-200" />;
                  if (u.kind === 'heading') {
                    return (
                      <div key={u.n} id={`u-${u.n}`} data-n={u.n} className="mt-3 flex items-center gap-2 text-[14px] font-bold text-stone-700 first:mt-0">
                        {u.text}<span className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-normal text-stone-500">読みません</span>{commentMark(u.n)}
                      </div>
                    );
                  }
                  if (u.kind === 'note' || u.kind === 'gone') {
                    return (
                      <div key={u.n} id={`u-${u.n}`} data-n={u.n} className={cn('my-1 text-[14px] leading-relaxed text-stone-700', threadsAt.has(u.n) && 'bg-yellow-100')}>
                        {u.segs ? <SegText segs={u.segs} onSuggestion={pickSuggestion} /> : u.text}{commentMark(u.n)}
                      </div>
                    );
                  }
                  return null;
                })}
              </section>
            )}
            {blocks.map(renderBlock)}
            {unplaced.length > 0 && (
              <div className="mt-10 border-t border-stone-300 pt-3">
                <div className="mb-2 text-[13px] font-semibold text-stone-600">本文の場所が分からないコメント</div>
                <div className="space-y-2">
                  {unplaced.map(t => (
                    <ThreadCard key={t.id} thread={t} active={active === t.id} onFocus={() => setActive(t.id)}
                      onReply={sendReply(t)} onSettle={settle(t)} canWrite={canComment} />
                  ))}
                </div>
              </div>
            )}
            <div className="mt-8 text-center text-[12px] text-stone-400">
              {touch ? '文を押すとそこから聞けます。もう一度押すと直せます。' : '文を押すとそこから聞けます。そのまま打つと直せて、Enter でドキュメントに入ります（文を全部消すと、その文が消えます）。'}
              文字を選ぶとコメントできます。
            </div>
          </div>

          {wide && (
            <div ref={marginRef} className="relative w-72 shrink-0">
              {draft && (
                <div ref={el => { if (el) cardRefs.current.set('draft', el); else cardRefs.current.delete('draft'); }}
                  data-anchor={draft.n} className="absolute inset-x-0 z-10">
                  <Composer quote={draft.quote} onSend={sendComment} onCancel={() => setDraft(null)} />
                </div>
              )}
              {visibleThreads.filter(t => place.has(t.id)).map(t => (
                <div key={t.id} ref={el => { if (el) cardRefs.current.set(t.id, el); else cardRefs.current.delete(t.id); }}
                  data-anchor={place.get(t.id)} className={cn('absolute inset-x-0', active === t.id && 'z-10')}>
                  <ThreadCard thread={t} active={active === t.id} onFocus={() => { setActive(t.id); focusUnit(place.get(t.id)!); }}
                    onReply={sendReply(t)} onSettle={settle(t)} canWrite={canComment} />
                </div>
              ))}
              {suggestions.map(s => (
                <div key={s.id} ref={el => { if (el) cardRefs.current.set(s.id, el); else cardRefs.current.delete(s.id); }}
                  data-anchor={s.n} className={cn('absolute inset-x-0', active === s.id && 'z-10')}>
                  <SuggestionCard s={s} active={active === s.id} onFocus={() => { setActive(s.id); focusUnit(s.n); }} onDecide={a => decide(s, a)} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {selBtn && (
        <button
          type="button"
          onMouseDown={e => e.preventDefault()}
          onClick={() => openDraft({ quote: selBtn.quote, n: selBtn.n, start: selBtn.start })}
          style={{ left: Math.min(selBtn.x + 6, window.innerWidth - 110), top: Math.max(selBtn.y - 40, 60) }}
          className="fixed z-30 flex items-center gap-1 rounded-full bg-stone-900 px-3 py-1.5 text-[13px] font-semibold text-white shadow-lg"
        >
          <MessageSquarePlus className="h-4 w-4" />コメント
        </button>
      )}

      {!wide && sheet && (
        <div className="fixed inset-x-0 bottom-0 z-40 max-h-[70dvh] overflow-y-auto rounded-t-2xl border-t border-stone-200 bg-[#faf8f4] px-3 pb-[max(env(safe-area-inset-bottom),0.75rem)] pt-2 shadow-2xl">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-[13px] font-semibold text-stone-700">
              {sheet.kind === 'suggestion' ? '提案' : sheet.kind === 'compose' ? 'コメントを書く' : 'コメント'}
            </div>
            <button type="button" aria-label="閉じる" onClick={() => { setSheet(null); setDraft(null); }} className="rounded-full p-1.5 text-stone-500 active:bg-stone-200">
              <X className="h-5 w-5" />
            </button>
          </div>
          {sheet.kind === 'compose' && draft && <Composer quote={draft.quote} onSend={sendComment} onCancel={() => { setDraft(null); setSheet(null); }} />}
          {sheetSuggestion && <SuggestionCard s={sheetSuggestion} active onDecide={a => decide(sheetSuggestion, a)} />}
          {sheet.kind === 'all' && (
            <label className="mb-2 flex items-center gap-1.5 text-[12px] text-stone-600">
              <input type="checkbox" checked={showResolved} onChange={e => setShowResolved(e.target.checked)} />解決済みも見る
            </label>
          )}
          {sheet.kind === 'all' && suggestions.length > 0 && (
            <div className="mb-3 space-y-2">
              {suggestions.map(s => <SuggestionCard key={s.id} s={s} onFocus={() => { focusUnit(s.n); }} onDecide={a => decide(s, a)} />)}
            </div>
          )}
          <div className="space-y-2">
            {sheetThreads.map(t => (
              <ThreadCard key={t.id} thread={t} active={active === t.id || sheet.kind === 'threads'}
                onFocus={() => { setActive(t.id); const n = place.get(t.id); if (n != null) focusUnit(n); }}
                onReply={sendReply(t)} onSettle={settle(t)} canWrite={canComment} />
            ))}
            {sheet.kind === 'all' && !sheetThreads.length && !suggestions.length && <div className="py-4 text-center text-[13px] text-stone-500">コメントはありません</div>}
          </div>
        </div>
      )}

      <div className="shrink-0 border-t border-stone-200 bg-white/95 px-3 pb-[max(env(safe-area-inset-bottom),0.5rem)] pt-2 backdrop-blur sm:px-6">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-center justify-between gap-2 text-[12px] text-stone-500">
            <span>{says.length ? `${cur + 1} / ${says.length}文` : '読む文がありません'}</span>
            <span className="flex items-center gap-1">
              {saving && <><Loader2 className="h-3 w-3 animate-spin" />ドキュメントに入れています</>}
              {!saving && waiting && <><Loader2 className="h-3 w-3 animate-spin" />声を作っています</>}
              {!saving && !waiting && says.length > 0 && `残り約${fmtMinutes(remaining)}`}
            </span>
          </div>
          <div className="mt-1.5 flex items-center justify-center gap-3">
            <button
              type="button"
              aria-label="今の文にコメント"
              disabled={!says[cur]}
              onClick={() => { const u = says[cur]; if (u) openDraft({ quote: u.text, n: u.n, start: u.start }); }}
              className="flex flex-col items-center rounded-lg px-2 py-1 text-[10px] text-stone-600 active:bg-stone-200 disabled:opacity-40"
            >
              <MessageSquarePlus className="h-5 w-5" />コメント
            </button>
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
            <div className="w-[52px]" />
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
