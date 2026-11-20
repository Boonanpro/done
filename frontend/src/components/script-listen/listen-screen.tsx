'use client';

// 台本を読み上げで聞いて、その場で直し、コメントでダンとやり取りする画面（2026-11-18、11-19 に作り直し）。
// - 台本の正本は Google ドキュメント。読むのは「◎台本」より下の黒い文だけ。サムネ・タイトル・前提と狙いは上に見せる（読まない）。
// - 再生: 1文ずつの音声を順につなぐ。どの文の後も同じ短い間で、段落や段の切れ目でも止まらない（11/19 本人「全部一気に
//   再生できるように」）。次の文は今の文の後ろの無音のうちに鳴らし始めるので、文と文の間に待ちが入らない。倍速でも声の高さは同じ。
// - 直す: 本文全体が Google ドキュメントのように1枚で直せる（11/19 本人「Googleドキュメントと同じくらいの使い勝手にしろ」）。
//   文や段落ごとの枠は無く、段落をまたいで選べる。Enter で改行、Ctrl+Z で戻す、Ctrl+Shift+Z / Ctrl+Y でやり直す、Ctrl+B で太字。
//   打つのを止めると、変わった段落だけが自動でドキュメントに入る（editor-dom.ts の diffLines → replace）。
//   押すだけでは鳴らない。鳴らす・止めるのは文のダブルクリック（スマホは2回続けて押す）だけ（11/20 本人「編集したいだけで
//   カーソルを合わせたときにも音が鳴るのが鬱陶しい」）。スマホは1回押すとそこで打てる。
// - 画面は勝手に動かさない: 承認・却下やダンの直しでドキュメントを読み直しても、見ている所はそのまま（11/20 本人「承認ボタンを
//   押すと上の方まで飛ばされる」。読み直すたびに再生位置の文へ戻していた）。鳴っている文が画面の外へ出た時だけ追いかける。
// - コメント: 文字を選ぶと右の余白（スマホは選んだ所の下）にコメントの印が出る。ドキュメントのコメントとして入るので、ダンが
//   返事と直しをし、学習にも入る。ダンの直しは提案（緑＝足す、赤の線＝消す）で出て、ここで承認・却下できる。
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Bot, CheckCheck, Columns2, ExternalLink, ImagePlus, Loader2, MessageSquare, MessageSquarePlus, Pause, PenLine, Pencil, Play, SkipBack, SkipForward, Volume2, X } from 'lucide-react';
import { toast } from 'sonner';
import { get as idbGet, set as idbSet } from 'idb-keyval';

import {
  errorText, listenApi, type DanJob, type EditMode, type ListenDoc, type ListenUnit, type Reference, type SayUnit, type Suggestion, type Thread,
} from '@/lib/script-listen-api';
import { cn } from '@/lib/utils';

import { buildHtml, diffLines, extract, getPos, isOwnSuggestion, leaves, nodeAt, OWN_DEL, OWN_INS, setPos, type Line, type Pos } from './editor-dom';
import { Composer, SuggestionCard, ThreadCard } from './listen-cards';
import { DanLiveContext, isLive } from './listen-dan';
import { RefsPanel, type SectionHead } from './listen-refs';
import { ListenChat, ListenThumb, type ThumbTarget } from './listen-side';

const RATES = [1, 1.25, 1.5, 1.75, 2, 2.5, 3, 3.5, 4];   // 11/20 本人「4倍までつけてほしい」
const RATE_KEY = 'script-listen-rate';
const VOICE_KEY = 'script-listen-voice';
const MODE_KEY = 'script-listen-mode';
const COMPARE_KEY = 'script-listen-compare';
const CHAT_KEY = 'script-listen-chat';
const posKey = (doc: string) => `script-listen-pos-${doc}`;
const cacheKey = (doc: string, voice: string) => `script-listen-doc-${doc}-${voice}`;
// Every clip ends with 0.16 s of silence (+0.03 s kept after the voice). The next clip starts this many seconds of the
// clip before its end, so only silence is cut and the switch to the next clip happens inside the pause.
const LEAD = 0.17;
// Typing that pauses this long is written into the doc.
const SAVE_AFTER = 900;

type Clip = { url: string; el: HTMLAudioElement };
/** Which of the suggestions now in the sentence Dan put in for the gone one: the one sharing the most of its words.
 * Other suggestions in the same sentence (Dan's or someone's) are not it — 11/20 the talk about 「、税込」→「（税込）」
 * moved to the 「月々約33,000円から、総額でも」 card next to it. With more than one and nothing shared, none. */
function followingSuggestion(cands: Suggestion[], old?: { ins: string; del: string } | null): Suggestion | undefined {
  if (cands.length <= 1) return cands[0];
  if (!old) return undefined;
  const grams = (t: string) => {
    const g = new Set<string>();
    const c = t.replace(/\s+/g, '');
    if (c.length === 1) g.add(c);
    for (let i = 0; i + 1 < c.length; i++) g.add(c.slice(i, i + 2));
    return g;
  };
  const was = grams(old.del + '\n' + old.ins);
  let best: Suggestion | undefined, top = 0;
  for (const s of cands) {
    const now = grams(s.del + '\n' + s.ins);
    let hit = 0;
    for (const g of now) if (was.has(g)) hit++;
    const score = hit / Math.max(1, Math.min(was.size, now.size));
    if (score > top) { top = score; best = s; }
  }
  return best;
}

type Sheet = { kind: 'threads'; ids: string[] } | { kind: 'suggestion'; id: string } | { kind: 'compose' } | { kind: 'all' } | null;
type Draft = { quote: string; n: number; start: number | null; from?: Pos | null; to?: Pos | null };
// Taps on a phone: one tap types there, two taps in a row play from there.
const DOUBLE_TAP = 300;
/** How long a suggestion of Dan's stays lit after it comes in; then it looks like any suggestion. */
const FRESH_MS = 2500;
type Snap = { html: string; pos: Pos | null };
type AfterBuild = { pos: Pos | null; focus: boolean; play: boolean; line?: string };

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

const unitN = (node: Node | null) => {
  const el = node && (node.nodeType === 1 ? (node as Element) : node.parentElement);
  const host = el?.closest('[data-n]') as HTMLElement | null;
  return host ? Number(host.dataset.n) : null;
};

/** The sentence under the pointer. The event's target can be the paragraph around the sentences (its margins, the gap
 * between two sentences, the end of a line), so the letter at that point decides. */
const unitAtPoint = (x: number, y: number, fallback: EventTarget | null) => {
  const doc_ = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null };
  const r = doc_.caretRangeFromPoint?.(x, y);
  let n = r ? unitN(r.startContainer) : null;
  if (n == null && r && r.startContainer.nodeType === 1) {
    const kids = r.startContainer.childNodes;
    n = unitN(kids[Math.min(r.startOffset, kids.length - 1)] || null) ?? unitN(kids[r.startOffset - 1] || null);
  }
  return n ?? unitN(fallback as Node | null);
};

/** Bring a sentence into view only when it is off the screen (or behind the bars), the way a document follows a reader. */
function revealUnit(n: number) {
  const el = document.getElementById(`u-${n}`);
  const box = el?.closest('[data-scroller]') as HTMLElement | null;
  if (!el || !box) return;
  const r = el.getBoundingClientRect();
  const b = box.getBoundingClientRect();
  if (r.top >= b.top + 24 && r.bottom <= b.bottom - 24) return;
  el.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

// ---------------------------------------------------------------- the owner's suggestion mode (11/20)
// 本人「僕の方で提案モードで何か書き込んだりするということができないので、それもできるようにしたい」. Typing in suggestion
// mode puts the new words in the owner's colour and strikes the words taken out instead of removing them, like Docs. The
// change goes to the server as it would in edit mode (struck letters marked), which keeps it as the owner's suggestion.

const ownSpan = (kind: 'ins' | 'del') => {
  const sp = document.createElement('span');
  sp.setAttribute(kind === 'ins' ? 'data-oi' : 'data-od', '');
  sp.className = kind === 'ins' ? OWN_INS : OWN_DEL;
  return sp;
};
/** The owner's own added words (new here, or already kept as their suggestion): taking them out removes them. */
const ownAdded = (el: Element | null) => {
  const h = el?.closest('[data-oi],[data-sug][data-kind="ins"]') as HTMLElement | null;
  return !!h && (h.hasAttribute('data-oi') || isOwnSuggestion(h.dataset.sug));
};
const struckHost = (el: Element | null) => el?.closest('[data-od],[data-sug][data-kind="del"]') as HTMLElement | null;
const leafOf = (root: HTMLElement, n: Node) => leaves(root).find(l => l === n || l.contains(n)) || null;

function textPieces(range: Range) {
  const out: { node: Text; s: number; e: number }[] = [];
  const top = range.commonAncestorContainer;
  if (top.nodeType === 3) {
    out.push({ node: top as Text, s: range.startOffset, e: range.endOffset });
    return out;
  }
  const w = document.createTreeWalker(top, NodeFilter.SHOW_TEXT);
  for (let t = w.nextNode() as Text | null; t; t = w.nextNode() as Text | null) {
    if (!range.intersectsNode(t)) continue;
    const s = t === range.startContainer ? range.startOffset : 0;
    const e = t === range.endContainer ? range.endOffset : t.data.length;
    if (e > s) out.push({ node: t, s, e });
  }
  return out;
}

/** Strike ``range`` the suggestion-mode way. Returns how many letters stayed (struck) or 'para' when it crosses the
 * end of a paragraph (suggestion mode keeps paragraphs as they are). */
function strike(root: HTMLElement, range: Range): number | 'para' {
  const a = leafOf(root, range.startContainer), b = leafOf(root, range.endContainer);
  if (!a || a !== b) return 'para';
  let kept = 0;
  for (const { node, s, e } of textPieces(range).reverse()) {
    const host = node.parentElement;
    if (ownAdded(host)) { node.deleteData(s, e - s); continue; }
    if (struckHost(host)) { kept += e - s; continue; }
    const mid = node.splitText(s);
    mid.splitText(e - s);
    const sp = ownSpan('del');
    mid.replaceWith(sp);
    sp.appendChild(mid);
    kept += e - s;
  }
  return kept;
}

/** Put ``text`` in at the caret as the owner's added words. */
function addOwn(root: HTMLElement, text: string) {
  const sel = window.getSelection();
  if (!sel?.rangeCount) return;
  const r = sel.getRangeAt(0);
  const at = r.startContainer;
  const el = at.nodeType === 1 ? (at as Element) : at.parentElement;
  let node: Text;
  if (at.nodeType === 3 && ownAdded(el)) {
    (at as Text).insertData(r.startOffset, text);
    node = at as Text;
    const c = document.createRange(); c.setStart(node, r.startOffset + text.length); c.collapse(true);
    sel.removeAllRanges(); sel.addRange(c);
    return;
  }
  const sp = ownSpan('ins');
  node = document.createTextNode(text);
  sp.appendChild(node);
  const host = struckHost(el);
  if (host && root.contains(host)) {
    // Not inside struck words: next to them (before when the caret is at their start).
    const atStart = at.nodeType === 3 && r.startOffset === 0 && host.firstChild === at;
    if (atStart) host.before(sp); else host.after(sp);
  } else {
    r.insertNode(sp);
  }
  const c = document.createRange(); c.setStart(node, text.length); c.collapse(true);
  sel.removeAllRanges(); sel.addRange(c);
}

/** The caret in a paragraph that changed from ``was`` to ``now`` (e.g. a suggestion's struck words went): it keeps to
 * the letters after it when the change was before it. */
function movedCaret(pos: Pos, was: string, now: string): Pos {
  if (was === now) return pos;
  let p = 0;
  while (p < was.length && p < now.length && was[p] === now[p]) p++;
  if (pos.off <= p) return pos;
  let s = 0;
  while (s < was.length - p && s < now.length - p && was[was.length - 1 - s] === now[now.length - 1 - s]) s++;
  if (pos.off >= was.length - s) return { line: pos.line, off: Math.max(0, now.length - (was.length - pos.off)) };
  return { line: pos.line, off: Math.min(pos.off, now.length - s) };
}

/** The words ``quote`` inside the elements of a unit, as a range (spaces ignored); the whole unit when not found. */
function quoteRange(root: HTMLElement, n: number, quote: string): Range | null {
  const els = Array.from(root.querySelectorAll<HTMLElement>(`[data-n="${n}"]`));
  if (!els.length) return null;
  const chars: { node: Text; off: number }[] = [];
  let flat = '';
  for (const el of els) {
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let t = w.nextNode() as Text | null; t; t = w.nextNode() as Text | null) {
      for (let k = 0; k < t.data.length; k++) if (!/\s/.test(t.data[k])) { chars.push({ node: t, off: k }); flat += t.data[k]; }
    }
  }
  const r = document.createRange();
  const q = quote.replace(/\s+/g, '');
  const i = q ? flat.indexOf(q) : -1;
  if (i >= 0 && q.length) {
    r.setStart(chars[i].node, chars[i].off);
    const last = chars[i + q.length - 1];
    r.setEnd(last.node, last.off + 1);
  } else {
    r.setStartBefore(els[0]);
    r.setEndAfter(els[els.length - 1]);
  }
  return r;
}

const FLASH_MS = 2400;
/** A soft yellow glow over words that fades away (11/20 本人「一瞬黄色くぼんやりと目立たせて、数秒したら消える」). */
function flashRange(r: Range | null) {
  const hl = (globalThis as { CSS?: { highlights?: Map<string, unknown> } }).CSS?.highlights;
  const H = (globalThis as { Highlight?: new (...r: Range[]) => unknown }).Highlight;
  if (!r || !hl || !H) return;
  let style = document.getElementById('cm-flash-style') as HTMLStyleElement | null;
  if (!style) { style = document.createElement('style'); style.id = 'cm-flash-style'; document.head.appendChild(style); }
  hl.set('cm-flash', new H(r));
  const t0 = performance.now();
  const me = Symbol('flash');
  (flashRange as unknown as { cur?: symbol }).cur = me;
  const step = (now: number) => {
    if ((flashRange as unknown as { cur?: symbol }).cur !== me) return;
    const k = Math.min(1, (now - t0) / FLASH_MS);
    // hold, then fade
    const a = k < 0.35 ? 0.85 : 0.85 * (1 - (k - 0.35) / 0.65);
    style!.textContent = `::highlight(cm-flash){background-color:rgb(253 224 71 / ${a.toFixed(3)})}`;
    if (k < 1) requestAnimationFrame(step); else { hl.delete('cm-flash'); style!.textContent = ''; }
  };
  requestAnimationFrame(step);
}

/** The same glow around a card. */
function flashCard(id: string) {
  const el = document.querySelector<HTMLElement>(`[data-card="${CSS.escape(id)}"]`);
  const card = (el?.firstElementChild as HTMLElement | null) || el;
  if (!el || !card) return;
  const box = el.closest('[data-scroller]') as HTMLElement | null;
  if (box) {
    const r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
    if (r.top < b.top + 24 || r.bottom > b.bottom - 24) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  } else {
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  card.animate?.([
    { boxShadow: '0 0 0 4px rgb(253 224 71 / 0.9), 0 0 22px 6px rgb(253 224 71 / 0.65)', backgroundColor: 'rgb(254 249 195)' },
    { boxShadow: '0 0 0 4px rgb(253 224 71 / 0.9), 0 0 22px 6px rgb(253 224 71 / 0.65)', backgroundColor: 'rgb(254 249 195)', offset: 0.35 },
    { boxShadow: '0 0 0 0 rgb(253 224 71 / 0), 0 0 0 0 rgb(253 224 71 / 0)', backgroundColor: 'rgb(255 255 255)' },
  ], { duration: FLASH_MS, easing: 'ease-out' });
}

export function ListenScreen({ docId }: { docId: string }) {
  const [doc, setDoc] = useState<ListenDoc | null>(null);
  const [loadError, setLoadError] = useState('');
  // The doc as it was last time, shown at once while the doc is read again (11/20 本人「速くできる余地があるなら早く」).
  // It can be read and played but not typed in: a change must be measured against the doc as it is now.
  const [stale, setStale] = useState(false);
  const staleRef = useRef(false);
  const [voice, setVoice] = useState<string>(() => (typeof window !== 'undefined' && localStorage.getItem(VOICE_KEY)) || 'aida-calm');
  const [rate, setRate] = useState<number>(() => Number((typeof window !== 'undefined' && localStorage.getItem(RATE_KEY)) || 1.5));
  const [cur, setCur] = useState(0);            // index into says
  const [playing, setPlaying] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [armed, setArmed] = useState(false);    // touch: the text takes typing (after a second tap on the sentence)
  const [threads, setThreads] = useState<Thread[]>([]);
  const [jobs, setJobs] = useState<DanJob[]>([]);           // Dan's answers to the comments, with their work log
  const [jobSel, setJobSel] = useState<string | null>(null);
  // The job whose log is open in its comment card.
  const [expanded, setExpanded] = useState<string | null>(null);
  const [canComment, setCanComment] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [active, setActive] = useState<string | null>(null);  // thread or suggestion id
  const [draft, setDraft] = useState<Draft | null>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [selBtn, setSelBtn] = useState<(Draft & { x: number; y: number }) | null>(null);
  const [screenWide, setWide] = useState(() => typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches);
  // 比べる: the scripts of the videos this one was modelled on, beside it (PC) or under it (phone). While comparing, the
  // reference takes the right margin, so comment and suggestion cards open in the sheet as on a phone.
  const [refs, setRefs] = useState<Reference[]>([]);
  const [compare, setCompare] = useState(() => typeof window !== 'undefined' && localStorage.getItem(COMPARE_KEY) === '1');
  const [hereHead, setHereHead] = useState<number | null>(null);
  const comparing = compare && refs.length > 0;
  const wide = screenWide && !comparing;
  const [touch, setTouch] = useState(() => typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches);
  const [build, setBuild] = useState(0);        // bumps to put the doc's text into the surface again
  // Edit (into the doc) or suggest (the owner's suggestion), like the mode switch in Google Docs.
  const [mode, setMode] = useState<EditMode>(() => (typeof window !== 'undefined' && localStorage.getItem(MODE_KEY) === 'suggest' ? 'suggest' : 'edit'));
  const modeRef = useRef<EditMode>(mode);
  const compStart = useRef<Pos | null>(null);
  const [allBusy, setAllBusy] = useState<'accept' | 'reject' | null>(null);
  // 右の「ダンと台本」（PC は横の欄、スマホは下から開く欄）と、上のサムネの編集（11/20 本人）
  const [chatOpen, setChatOpen] = useState(() => typeof window === 'undefined' || localStorage.getItem(CHAT_KEY) !== '0');
  const [phoneChat, setPhoneChat] = useState(false);
  const [thumb, setThumb] = useState<ThumbTarget | null>(null);
  const chatSide = screenWide && chatOpen;

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
  const contentRef = useRef<HTMLDivElement | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const tapTimer = useRef<number | null>(null);
  const lastTap = useRef<{ at: number; x: number; y: number } | null>(null);
  const marginRef = useRef<HTMLDivElement | null>(null);
  // The editing surface. React never renders inside it: its HTML is put in once per reading of the doc.
  const editorRef = useRef<HTMLDivElement | null>(null);
  const baseRef = useRef<Line[]>([]);          // the doc as last written, paragraph by paragraph
  const dirtyRef = useRef(false);               // typed since the doc was last read (sentences and voice are stale)
  const typedRef = useRef(false);               // typed since the last click (Space plays until then)
  const composingRef = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const saveChain = useRef<Promise<unknown>>(Promise.resolve());
  const settling = useRef<Promise<void> | null>(null);
  const undoRef = useRef<Snap[]>([]);
  const redoRef = useRef<Snap[]>([]);
  const lastSnap = useRef({ at: 0, kind: '' });
  const afterBuild = useRef<AfterBuild | null>(null);
  const tapAt = useRef<{ x: number; y: number } | null>(null);
  const lastInput = useRef(0);
  const ownRevisions = useRef(new Set<string>());   // revisions this screen wrote (not someone else's change)
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

  // ---------------------------------------------------------------- doc and comments
  const show = useCallback((d: ListenDoc, keepText?: { start: number; text: string }) => {
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
  }, [docId, sendAhead]);

  const load = useCallback(async (keepText?: { start: number; text: string }) => {
    try {
      const d = await listenApi.doc(docId, voiceRef.current);
      // Coming from last time's copy: stay on the sentence that is showing (or playing).
      const here = staleRef.current && !keepText ? saysRef.current[curRef.current] : undefined;
      show(d, keepText || (here ? { start: here.start, text: here.text } : undefined));
      staleRef.current = false;
      setStale(false);
      void idbSet(cacheKey(docId, d.voice || voiceRef.current), d).catch(() => undefined);
      return d;
    } catch (e) {
      setLoadError(errorText(e));
      return null;
    }
  }, [docId, show]);

  useEffect(() => {
    let fresh = false;
    void idbGet<ListenDoc>(cacheKey(docId, voiceRef.current)).then(d => {
      if (!d || fresh || saysRef.current.length) return;
      staleRef.current = true;
      setStale(true);
      show(d);
    }).catch(() => undefined);
    void load().then(() => { fresh = true; });
    return () => { fresh = true; };
  }, [load, show, voice, docId]);

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

  // What Dan is doing on the comments (11/20 本人「ダンがどこを編集してるか可視化」「プロセスモニターも」): read often
  // while he works, so his lines and his suggestions show as they come.
  const danLive = busy || jobs.some(isLive);
  const loadJobs = useCallback(async () => {
    try { setJobs((await listenApi.activity(docId)).jobs); } catch { /* next time */ }
  }, [docId]);
  useEffect(() => {
    const first = window.setTimeout(() => void loadJobs(), 0);
    const t = window.setInterval(() => { if (!document.hidden) void loadJobs(); }, danLive ? 2500 : 15000);
    return () => { window.clearTimeout(first); window.clearInterval(t); };
  }, [danLive, loadJobs]);
  // A job just ended: its reply is in the doc now.
  const liveIds = jobs.filter(isLive).map(j => j.id).join(',');
  const prevLive = useRef('');
  useEffect(() => {
    const was = prevLive.current.split(',').filter(Boolean);
    prevLive.current = liveIds;
    if (was.some(id => !liveIds.split(',').includes(id))) void loadComments();
  }, [liveIds, loadComments]);
  // The one picked in the monitor, else the one working now (the list comes working → waiting → ended).
  const shownJob = jobs.find(j => j.id === jobSel)?.id ?? jobs[0]?.id ?? null;

  const editing = () => dirtyRef.current || (!!editorRef.current && document.activeElement === editorRef.current && typedRef.current);

  // The doc changed elsewhere (Dan's fix, Google Docs): read it again. While the owner types, wait until they stop
  // for a moment, then read it again keeping the caret where it is (like the doc showing others' changes).
  const settleRef = useRef<(o: { focus: boolean; play: boolean }) => Promise<void>>(async () => {});
  useEffect(() => {
    const t = window.setInterval(async () => {
      if (!doc || saving || settling.current || document.hidden || composingRef.current) return;
      if (Date.now() - lastInput.current < 5000 || saveTimer.current != null) return;
      try {
        const { version } = await listenApi.version(docId);
        if (!version || !doc.version || version === doc.version || settling.current) return;
        if (Date.now() - lastInput.current < 5000 || composingRef.current) return;
        const theirs = !ownRevisions.current.has(version);
        // Someone else changed the doc: undo here would bring their change back too.
        if (theirs) { undoRef.current = []; redoRef.current = []; }
        const root = editorRef.current;
        if (dirtyRef.current) {
          if (!theirs) return;          // only our own writes: the text on the screen is already right
          await settleRef.current({ focus: !!root && document.activeElement === root, play: false });
          return;
        }
        const here = saysRef.current[curRef.current];
        const wasPlaying = playingRef.current;
        if (wasPlaying) stop();
        else if (root && document.activeElement === root) afterBuild.current = { pos: getPos(root), focus: true, play: false };
        const d = await load(here ? { start: here.start, text: here.text } : undefined);
        if (d && wasPlaying) void playFrom(curRef.current);
      } catch { /* next time */ }
    }, danLive ? 3000 : 8000);   // while Dan works his suggestions come in as he makes them
    return () => window.clearInterval(t);
  }, [doc, docId, saving, load, playFrom, stop, danLive]);

  // ---------------------------------------------------------------- speed, voice, keys
  useEffect(() => {
    try { localStorage.setItem(RATE_KEY, String(rate)); } catch { /* ignore */ }
    if (active_.current) { setPitchKeep(active_.current); active_.current.playbackRate = rate; }
  }, [rate]);

  useEffect(() => () => { token.current += 1; clearTick(); active_.current?.pause(); }, []);

  useEffect(() => { modeRef.current = mode; try { localStorage.setItem(MODE_KEY, mode); } catch { /* ignore */ } }, [mode]);

  // ---------------------------------------------------------------- comments and suggestions
  const units = useMemo(() => doc?.units || [], [doc]);
  const unitByN = useMemo(() => new Map(units.map(u => [u.n, u])), [units]);
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
  const suggestions = useMemo(() => doc?.suggestions || [], [doc]);
  // Comments written on a suggestion's card stay with that suggestion. When Dan has put in a new suggestion for it
  // (the old one is gone), the open talk moves on to the suggestion now at the same place.
  const { sugTalk, talkOf } = useMemo(() => {
    const ids = new Set(suggestions.map(x => x.id));
    const pairs: [string, Thread, boolean][] = [];
    for (const t of visibleThreads) if (t.suggestion && ids.has(t.suggestion)) pairs.push([t.suggestion, t, false]);
    const taken = new Set(pairs.map(x => x[0]));
    for (const t of visibleThreads) {
      if (!t.suggestion || ids.has(t.suggestion) || t.resolved) continue;
      const n = place.get(t.id);
      const next = followingSuggestion(suggestions.filter(x => x.n === n && !taken.has(x.id)), t.suggestion_words);
      if (next) { pairs.push([next.id, t, true]); taken.add(next.id); }
    }
    const talk = new Map<string, { threads: Thread[]; earlier: boolean }>();
    for (const sid of taken) {
      const mine = pairs.filter(x => x[0] === sid);
      talk.set(sid, { threads: mine.map(x => x[1]), earlier: mine.some(x => x[2]) });
    }
    return { sugTalk: talk, talkOf: new Map(pairs.map(x => [x[1].id, x[0]] as const)) };
  }, [suggestions, visibleThreads, place]);
  // Where Dan is lit (11/20 本人「今その瞬間実際に操作したり編集したりしている場所が光るべき。考えているだけで操作して
  // いない時は光るべきじゃない」): only the sentences his browser step is selecting or typing in right now (the words the
  // step carries, job.touch), and a suggestion of his for a moment when it comes in. Not the commented words, not the
  // turn's suggestions for the whole turn: those look like any suggestion (green / red).
  const seenSugs = useRef<Set<string> | null>(null);
  const [danFresh, setDanFresh] = useState<Map<string, { job: string; until: number }>>(() => new Map());   // briefly
  useEffect(() => {
    if (!doc) return;
    const ids = suggestions.filter(x => x.by !== 'owner').map(x => x.id);
    if (!seenSugs.current) { seenSugs.current = new Set(ids); return; }
    const fresh = ids.filter(id => !seenSugs.current!.has(id));
    fresh.forEach(id => seenSugs.current!.add(id));
    const working = jobs.find(j => j.status === 'running');
    if (!working || !fresh.length) return;
    const until = Date.now() + FRESH_MS;
    setDanFresh(m => { const n = new Map(m); fresh.forEach(id => n.set(id, { job: working.id, until })); return n; });
  }, [suggestions, jobs, doc]);
  useEffect(() => {
    if (!danFresh.size) return;
    const next = Math.min(...Array.from(danFresh.values()).map(v => v.until));
    const t = window.setTimeout(() => setDanFresh(m => {
      const now = Date.now(), n = new Map(m);
      n.forEach((v, k) => { if (v.until <= now) n.delete(k); });
      return n;
    }), Math.max(50, next - Date.now()));
    return () => window.clearTimeout(t);
  }, [danFresh]);
  const danUnits = useMemo(() => {
    const m = new Map<number, string>();
    const squash = (t: string) => t.replace(/\s+/g, '');
    const textOf = (u: ListenUnit) => squash(('segs' in u && u.segs?.length) ? u.segs.map(g => g.t).join('') : ('text' in u ? u.text : ''));
    for (const j of jobs) {
      const words = (j.status === 'running' && j.touch?.words || []).map(squash).filter(w => w.length >= 4);
      if (!words.length) continue;
      for (const u of units) {
        if (m.has(u.n) || u.kind === 'image' || u.kind === 'title') continue;
        const t = textOf(u);
        if (t.length >= 4 && words.some(w => t.includes(w) || (t.length >= 8 && w.includes(t)))) m.set(u.n, j.id);
      }
    }
    const sugN = new Map(suggestions.map(x => [x.id, x.n]));
    danFresh.forEach((v, sid) => { const n = sugN.get(sid); if (n != null && !m.has(n)) m.set(n, v.job); });
    return m;
  }, [jobs, units, suggestions, danFresh]);
  const unplaced = visibleThreads.filter(t => !place.has(t.id) && !talkOf.has(t.id));
  const openCount = threads.filter(t => !t.resolved).length;

  // ---------------------------------------------------------------- the editing surface
  const html = useMemo(() => buildHtml(units), [units]);
  const hasDoc = !!doc;

  // The words being commented on stay marked from the moment the comment button is pressed, while the comment is
  // written (11/20 本人「入力中にどこにコメントしてるのか見失う」). A CSS highlight: nothing is added to the text.
  const draftRef = useRef<Draft | null>(null);
  const paintDraft = useCallback(() => {
    const hl = (globalThis as { CSS?: { highlights?: Map<string, unknown> } }).CSS?.highlights;
    const H = (globalThis as { Highlight?: new (...r: Range[]) => unknown }).Highlight;
    if (!hl || !H) return;
    const root = editorRef.current;
    const d = draftRef.current;
    if (!root || !d?.from || !d.to) { hl.delete('cm-draft'); return; }
    const a = nodeAt(root, d.from), b = nodeAt(root, d.to);
    if (!a || !b) { hl.delete('cm-draft'); return; }
    try {
      const r = document.createRange();
      r.setStart(a.node, a.off);
      r.setEnd(b.node, b.off);
      hl.set('cm-draft', new H(r));
    } catch { hl.delete('cm-draft'); }
  }, []);
  useEffect(() => {
    draftRef.current = draft;
    paintDraft();
  }, [draft, paintDraft]);
  useEffect(() => () => { (globalThis as { CSS?: { highlights?: Map<string, unknown> } }).CSS?.highlights?.delete('cm-draft'); }, []);

  // Where the voice is and which words have comments: marks on the elements, so the text and the caret stay put.
  const applyMarks = useCallback(() => {
    const root = editorRef.current;
    if (!root) return;
    root.querySelectorAll('[data-on]').forEach(el => el.removeAttribute('data-on'));
    root.querySelectorAll('[data-cm]').forEach(el => el.removeAttribute('data-cm'));
    const u = says[cur];
    // While the owner types, the sentence they are in is not banded (11/19「黄色い枠…余計なものを付けるな」).
    if (u && (playing || !dirtyRef.current)) root.querySelectorAll(`[data-n="${u.n}"]`).forEach(el => el.setAttribute('data-on', ''));
    threadsAt.forEach((_, n) => root.querySelectorAll(`[data-n="${n}"]`).forEach(el => el.setAttribute('data-cm', '')));
    root.querySelectorAll('[data-dan]').forEach(el => el.removeAttribute('data-dan'));
    danUnits.forEach((_, n) => root.querySelectorAll(`[data-n="${n}"]`).forEach(el => el.setAttribute('data-dan', '')));
  }, [says, cur, threadsAt, playing, danUnits]);
  useEffect(() => { applyMarks(); }, [applyMarks]);

  const sayAtPos = useCallback((pos: Pos | null) => {
    const root = editorRef.current;
    if (!root || !pos) return -1;
    const at = nodeAt(root, pos);
    const n = at ? unitN(at.node) : null;
    if (n == null) return -1;
    const i = sayIndex.get(n);
    if (i != null) return i;
    // A heading, a note or an empty line: the first sentence after it.
    return saysRef.current.findIndex(s => s.n > n);
  }, [sayIndex]);

  useLayoutEffect(() => {
    const root = editorRef.current;
    if (!root || !doc) return;
    if (dirtyRef.current) return;   // never throw away what is being typed
    // Reading the doc again keeps the page where it is (11/20: approving a suggestion threw the page to the top).
    const scroller = scrollerRef.current;
    const keep = scroller?.scrollTop ?? 0;
    root.innerHTML = html;
    if (scroller && scroller.scrollTop !== keep) scroller.scrollTop = keep;
    baseRef.current = extract(root);
    applyMarks();
    paintDraft();
    const after = afterBuild.current;
    afterBuild.current = null;
    if (after?.pos && after.line != null) after.pos = movedCaret(after.pos, after.line, leaves(root)[after.pos.line]?.textContent ?? '');
    if (after?.pos) {
      const i = sayAtPos(after.pos);
      if (i >= 0) { curRef.current = i; setCur(i); }
      if (after.focus) { root.focus({ preventScroll: true }); setPos(root, after.pos); }
      if (after.play && i >= 0) void playFrom(i);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [html, build]);

  const doSave = useCallback(async () => {
    const root = editorRef.current;
    if (!root) return;
    const now = extract(root);
    const change = diffLines(baseRef.current, now);
    if (!change) return;
    if (change === 'gap') {
      toast.error('表などをまたいだ直しはここからは入れられないので、ドキュメントから読み直しました。');
      dirtyRef.current = false; undoRef.current = []; redoRef.current = [];
      await load();
      setBuild(b => b + 1);
      return;
    }
    setSaving(true);
    try {
      const { next, ...body } = change;
      const r = await listenApi.replace(docId, { ...body, mode: modeRef.current });
      // Put onto someone else's change: the screen is not the doc any more, so it is read again like their change.
      if (r.revision && !r.rebased) ownRevisions.current.add(r.revision);
      baseRef.current = next;
      const settledNow = r.settled && Object.keys(r.settled).length ? r.settled : null;
      if (r.reload || r.rebased || settledNow) {
        // Read the doc again now (keeping the caret), unless more is being typed: then the next pause does it.
        window.setTimeout(() => {
          if (saveTimer.current == null && !composingRef.current) void settleRef.current({ focus: document.activeElement === editorRef.current, play: false });
        }, 0);
      }
    } catch (e) {
      toast.error(errorText(e));
      // The doc did not take it: show the doc as it is (the undo steps no longer match it).
      dirtyRef.current = false; undoRef.current = []; redoRef.current = [];
      const here = saysRef.current[curRef.current];
      await load(here ? { start: here.start, text: here.text } : undefined);
      setBuild(b => b + 1);
    } finally {
      setSaving(false);
    }
  }, [docId, load]);

  const flush = useCallback(() => {
    if (saveTimer.current != null) { window.clearTimeout(saveTimer.current); saveTimer.current = null; }
    const run = () => doSave();
    saveChain.current = saveChain.current.then(run, run);
    return saveChain.current;
  }, [doSave]);

  const scheduleSave = useCallback(() => {
    if (saveTimer.current != null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      if (composingRef.current) return;   // the end of the composition saves
      void flush();
    }, SAVE_AFTER);
  }, [flush]);

  const changed = useCallback(() => {
    dirtyRef.current = true;
    typedRef.current = true;
    lastInput.current = Date.now();
    if (playingRef.current) stop();
    editorRef.current?.querySelectorAll('[data-on]').forEach(el => el.removeAttribute('data-on'));
    setSelBtn(null);
    scheduleSave();
  }, [scheduleSave, stop]);

  /** Write what is typed, then read the doc again so sentences and voice follow the new text. */
  const settle = useCallback((opts: { focus: boolean; play: boolean }) => {
    if (settling.current) return settling.current;
    const run = (async () => {
      await flush();
      if (!dirtyRef.current) return;
      // Keys typed while that was being written are not in the doc yet: reading it now would wipe them.
      if (saveTimer.current != null || composingRef.current) return;
      const root = editorRef.current;
      const pos = root ? getPos(root) : null;
      dirtyRef.current = false;
      typedRef.current = false;
      // The paragraph's text as the screen shows it now: the doc may read differently (a suggestion settled), and the
      // caret is moved by the difference.
      const line = root && pos ? leaves(root)[pos.line]?.textContent ?? undefined : undefined;
      afterBuild.current = { pos, focus: opts.focus && !!pos, play: opts.play, line };
      const here = saysRef.current[curRef.current];
      await load(here ? { start: here.start, text: here.text } : undefined);
      setBuild(b => b + 1);
    })().finally(() => { settling.current = null; });
    settling.current = run;
    return run;
  }, [flush, load]);

  useEffect(() => { settleRef.current = settle; }, [settle]);

  const toggle = useCallback(async () => {
    if (playingRef.current) { stop(); return; }
    if (dirtyRef.current || settling.current) {
      await settle({ focus: false, play: false });
    }
    void playFrom(curRef.current);
  }, [playFrom, settle, stop]);

  // ---- undo / redo: own history of the surface, so it reaches back past what was already written to the doc
  const snapshot = useCallback((): Snap => {
    const root = editorRef.current!;
    return { html: root.innerHTML, pos: getPos(root) };
  }, []);
  const remember = useCallback((kind: string, force = false) => {
    const now = Date.now();
    const last = lastSnap.current;
    if (force || now - last.at > 1000 || kind !== last.kind) {
      undoRef.current.push(snapshot());
      if (undoRef.current.length > 200) undoRef.current.shift();
      redoRef.current = [];
    }
    lastSnap.current = { at: now, kind };
  }, [snapshot]);
  const restore = useCallback((s: Snap) => {
    const root = editorRef.current;
    if (!root) return;
    root.innerHTML = s.html;
    if (s.pos) setPos(root, s.pos);
    applyMarks();
    lastSnap.current = { at: 0, kind: '' };
    changed();
  }, [applyMarks, changed]);
  const undo = useCallback(() => {
    const s = undoRef.current.pop();
    if (!s) return;
    redoRef.current.push(snapshot());
    restore(s);
  }, [restore, snapshot]);
  const redo = useCallback(() => {
    const s = redoRef.current.pop();
    if (!s) return;
    undoRef.current.push(snapshot());
    restore(s);
  }, [restore, snapshot]);

  const openDraft = useCallback((d: Draft) => {
    if (!canComment) { toast.error('お客さんも開けるドキュメントなので、ここからはコメントできません。作業用の台本で書いてください。'); return; }
    stop();
    draftRef.current = d;
    paintDraft();
    setDraft(d);
    setSelBtn(null);
    window.getSelection()?.removeAllRanges();
    if (!wide) setSheet({ kind: 'compose' });
  }, [canComment, paintDraft, stop, wide]);

  const selectionDraft = useCallback((): (Draft & { x: number; y: number }) | null => {
    const root = editorRef.current;
    const sel = window.getSelection();
    if (!root || !sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) return null;
    const text = sel.toString().replace(/\s+/g, ' ').trim();
    if (!text) return null;
    const n = unitN(range.startContainer) ?? unitN(range.startContainer.nextSibling);
    if (n == null) return null;
    const u = unitByN.get(n);
    const rect = range.getBoundingClientRect();
    const rects = range.getClientRects();
    const lastRect = rects.length ? rects[rects.length - 1] : rect;
    return {
      quote: text.slice(0, 400), n, start: u?.kind === 'say' ? u.start : null,
      from: getPos(root, range.startContainer, range.startOffset), to: getPos(root, range.endContainer, range.endOffset),
      x: wide ? (marginRef.current?.getBoundingClientRect().left ?? rect.right) : Math.min(lastRect.right, window.innerWidth - 56),
      y: wide ? rect.top : lastRect.bottom,
    };
  }, [unitByN, wide]);

  const suggestInputRef = useRef<(e: InputEvent) => void>(() => {});
  // Native listeners the surface needs (React has no onBeforeInput with inputType).
  useEffect(() => {
    const root = editorRef.current;
    if (!root) return;
    try { document.execCommand('defaultParagraphSeparator', false, 'p'); } catch { /* old browsers */ }
    const onBefore = (e: InputEvent) => {
      if (e.inputType === 'historyUndo') { e.preventDefault(); undo(); return; }
      if (e.inputType === 'historyRedo') { e.preventDefault(); redo(); return; }
      if (e.inputType.startsWith('format') && e.inputType !== 'formatBold') { e.preventDefault(); return; }
      if (composingRef.current || e.isComposing) return;
      remember(e.inputType.startsWith('delete') ? 'delete' : 'insert');
      if (modeRef.current === 'suggest') suggestInputRef.current(e);
    };
    root.addEventListener('beforeinput', onBefore);
    return () => root.removeEventListener('beforeinput', onBefore);
  }, [undo, redo, remember, hasDoc]);

  /** Suggestion mode: keys that would remove words strike them, typed words go in the owner's colour. */
  function suggestInput(e: InputEvent) {
    const root = editorRef.current;
    const sel = window.getSelection();
    if (!root || !sel?.rangeCount) return;
    const t = e.inputType;
    const refuse = () => { e.preventDefault(); toast('提案モードでは段落を分けたり、つなげたりできません。上の「編集」に切り替えてください。'); };
    if (t === 'insertParagraph' || t === 'insertLineBreak') { refuse(); return; }
    const strikeSel = (forward: boolean) => {
      const r = sel.getRangeAt(0);
      const start = getPos(root, r.startContainer, r.startOffset);
      const kept = strike(root, r);
      if (kept === 'para') return false;
      if (start) setPos(root, forward ? { line: start.line, off: start.off + kept } : start);
      return true;
    };
    if (t.startsWith('delete')) {
      e.preventDefault();
      const forward = /Forward$/.test(t);
      if (sel.isCollapsed) {
        const unit = t.includes('Word') ? 'word' : t.includes('Line') ? 'lineboundary' : 'character';
        (sel as Selection & { modify?: (a: string, d: string, g: string) => void }).modify?.('extend', forward ? 'forward' : 'backward', unit);
        if (sel.isCollapsed) return;
      }
      if (!strikeSel(forward || t === 'deleteByCut')) { refuse(); return; }
      changed();
      return;
    }
    if (t === 'insertText' || t === 'insertReplacementText') {
      const text = e.data ?? e.dataTransfer?.getData('text/plain') ?? '';
      if (!text) return;
      e.preventDefault();
      if (!sel.isCollapsed && !strikeSel(true)) { refuse(); return; }
      addOwn(root, text);
      changed();
    }
  }

  /** Suggestion mode, after Japanese input: the words just composed go in the owner's colour (the input itself cannot
   * be taken over while it is being composed). */
  function ownComposed() {
    const root = editorRef.current, sel = window.getSelection();
    const start = compStart.current;
    compStart.current = null;
    if (!root || !sel?.rangeCount || !start) return;
    const end = getPos(root);
    if (!end || end.line !== start.line || end.off <= start.off) return;
    const a = nodeAt(root, start), b = nodeAt(root, end);
    if (!a || !b) return;
    const inEl = b.node.nodeType === 1 ? (b.node as Element) : b.node.parentElement;
    if (ownAdded(inEl)) return;                      // typed inside the owner's own added words: already theirs
    const host = struckHost(inEl);
    const r = document.createRange();
    try { r.setStart(a.node, a.off); r.setEnd(b.node, b.off); } catch { return; }
    const sp = ownSpan('ins');
    sp.appendChild(r.extractContents());
    if (host && root.contains(host)) host.after(sp); else r.insertNode(sp);
    sp.normalize();
    const last = sp.lastChild;
    if (last && last.nodeType === 3) {
      const c = document.createRange(); c.setStart(last, (last as Text).data.length); c.collapse(true);
      sel.removeAllRanges(); sel.addRange(c);
    }
  }

  useEffect(() => { suggestInputRef.current = suggestInput; });

  const onEditorKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key.toLowerCase();
    if (e.nativeEvent.isComposing || composingRef.current) return;
    if (mod && !e.altKey && k === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (mod && !e.altKey && k === 'y') { e.preventDefault(); redo(); return; }
    if (mod && !e.altKey && k === 'b') {
      e.preventDefault();
      remember('format', true);
      document.execCommand('styleWithCSS', false, 'false');
      document.execCommand('bold');
      changed();
      return;
    }
    if (mod && !e.altKey && (k === 'i' || k === 'u')) { e.preventDefault(); return; }   // the doc copy keeps bold only
    if (mod && e.altKey && k === 'm') {
      e.preventDefault();
      const d = selectionDraft();
      if (d) openDraft(d);
      return;
    }
    if (e.key === 'Enter' && e.shiftKey) {
      e.preventDefault();
      if (modeRef.current === 'suggest') { toast('提案モードでは段落を分けられません。上の「編集」に切り替えてください。'); return; }
      remember('insert', true);
      document.execCommand('insertParagraph');
      return;
    }
    if (e.key === 'Escape') { e.currentTarget.blur(); return; }
    // Space types a space. Only while the voice plays (started by a double click) and nothing has been typed since,
    // it stops the voice instead.
    if (e.code === 'Space' && !mod && playingRef.current && !typedRef.current && !dirtyRef.current) { e.preventDefault(); stop(); }
  };

  /** The sentence to play for a place in the text (a heading or a note: the first sentence after it). */
  const sayForUnit = (n: number) => {
    const i = sayIndex.get(n);
    if (i != null) return i;
    return says.findIndex(s => s.n > n);
  };

  /** Double click (two taps on a phone): play from that sentence, or stop when it is the one being read. */
  const playAt = (n: number, x: number, y: number) => {
    const i = sayForUnit(n);
    if (i < 0) return;
    // The double click selected a word: put the caret back where it was clicked instead (no comment mark pops up).
    const root = editorRef.current;
    const doc_ = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null };
    const r = doc_.caretRangeFromPoint?.(x, y);
    const sel = window.getSelection();
    if (root && r && root.contains(r.startContainer)) { sel?.removeAllRanges(); sel?.addRange(r); }
    else sel?.collapseToEnd();
    setSelBtn(null);
    if (playingRef.current && curRef.current === i) { stop(); return; }
    typedRef.current = false;
    if (dirtyRef.current || settling.current) {
      // Typed before: write it, read the doc again, then play from the clicked place.
      afterBuild.current = null;
      void settle({ focus: !touch, play: true });
      return;
    }
    void playFrom(i);
  };

  // Pictures (11/20 本人「この読み上げページ（台本エディター）には画像も貼れるようにしたい」): pasted, dropped or picked
  // with the 画像 button, a picture goes into the doc as a new paragraph under the one the cursor is in.
  const lastParaRef = useRef<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [imageBusy, setImageBusy] = useState(false);
  const paraOf = useCallback((node: Node | null): number | null => {
    const root = editorRef.current;
    if (!root || !node || !root.contains(node)) return null;
    const el = (node.nodeType === 1 ? node as Element : node.parentElement);
    const img = el?.closest('[data-img-para]') as HTMLElement | null;
    if (img) return Number(img.dataset.imgPara);
    const p = el?.closest('[data-para]') as HTMLElement | null;
    if (p) return Number(p.dataset.para);
    // A line typed on the screen and not yet read back: the paragraph before it.
    for (let b = el?.closest('p,div') as Element | null; b && b !== root; b = b.previousElementSibling) {
      const at = (b as HTMLElement).dataset?.para ?? (b.querySelector('[data-para]') as HTMLElement | null)?.dataset.para;
      if (at != null) return Number(at);
    }
    return null;
  }, []);
  useEffect(() => {
    const keep = () => {
      const sel = window.getSelection();
      const at = sel?.rangeCount ? paraOf(sel.getRangeAt(0).startContainer) : null;
      if (at != null && !Number.isNaN(at)) lastParaRef.current = at;
    };
    document.addEventListener('selectionchange', keep);
    return () => document.removeEventListener('selectionchange', keep);
  }, [paraOf]);
  const putImage = useCallback(async (file: File, near?: Node | null) => {
    if (!doc || stale) { toast('ドキュメントを読み込んでから貼ってください。'); return; }
    if (!/^image\/(png|jpeg|gif|webp)$/.test(file.type)) { toast('貼れるのは PNG・JPEG・GIF・WebP の画像です。'); return; }
    let para = near ? paraOf(near) : null;
    if (para == null) para = lastParaRef.current;
    if (para == null) { toast('画像を入れたい所の文を押してから、もう一度貼ってください。'); return; }
    setImageBusy(true);
    const wait = toast.loading('画像をドキュメントに入れています…');
    try {
      if (dirtyRef.current) await settleRef.current({ focus: false, play: false });
      let blob: Blob = file, type = file.type;
      if (file.size > 4_000_000 && type !== 'image/gif') {
        // Big photos are made smaller here first (the doc shows them at most the page wide).
        const bmp = await createImageBitmap(file);
        const scale = Math.min(1, 2000 / bmp.width);
        const c = document.createElement('canvas');
        c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
        c.getContext('2d')?.drawImage(bmp, 0, 0, c.width, c.height);
        blob = await new Promise<Blob>((ok, no) => c.toBlob(b => (b ? ok(b) : no(new Error('画像を小さくできませんでした。'))), 'image/jpeg', 0.9));
        type = 'image/jpeg';
      }
      const data = await new Promise<string>((ok, no) => {
        const r = new FileReader();
        r.onload = () => ok(String(r.result));
        r.onerror = () => no(r.error || new Error('画像を読めませんでした。'));
        r.readAsDataURL(blob);
      });
      await listenApi.addImage(doc.doc_id, para, type, data);
      await load();
      toast.success('画像を入れました', { id: wait });
    } catch (e) {
      toast.error(errorText(e), { id: wait });
    } finally {
      setImageBusy(false);
    }
  }, [doc, stale, paraOf, load]);
  const dropImage = useCallback(async (objectId: string) => {
    if (!doc || !window.confirm('この画像をドキュメントから消しますか？')) return;
    try {
      if (dirtyRef.current) await settleRef.current({ focus: false, play: false });
      await listenApi.removeImage(doc.doc_id, objectId);
      await load();
      toast('画像を消しました');
    } catch (e) { toast.error(errorText(e)); }
  }, [doc, load]);

  const onEditorClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const t = e.target as HTMLElement;
    const del = (t.closest('[data-img-del]') as HTMLElement | null)?.dataset.imgDel;
    if (del) { e.preventDefault(); void dropImage(del); return; }
    // A thumbnail: open it in the thumbnail editor (its button, or the picture itself).
    const th = t.closest('[data-thumb-edit],[data-thumb-img]') as HTMLElement | null;
    if (th) {
      e.preventDefault();
      const order = Number(th.dataset.thumbEdit ?? th.dataset.thumbImg);
      const object = (th.closest('[data-img]') as HTMLElement | null)?.dataset.img || null;
      if (playingRef.current) stop();
      setThumb({ order, object });
      return;
    }
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed && e.detail < 2) return;     // selecting words
    // Words of a suggestion: the caret goes there (they can be typed in) and its card comes forward, glowing a
    // moment (11/20 本人「文章をクリックしてもカードの方に遷移するように」).
    const sug = (t.closest('[data-sug]') as HTMLElement | null)?.dataset.sug;
    if (sug && suggestions.some(x => x.id === sug)) {
      if (!touch) { if (e.detail < 2) showCard(sug); return; }
      if (!armed) { pickSuggestion(sug); flashLater(sug); return; }
      setActive(sug);
      return;
    }
    const n = unitAtPoint(e.clientX, e.clientY, t);
    if (n == null) return;
    if (!touch) {
      // A click only puts the caret there, like in a document. The comment on those words comes forward.
      if (e.detail >= 2) return;                        // the double click plays (onDoubleClick)
      const list = threadsAt.get(n);
      if (list?.length) showCard(talkOf.get(list[0].id) || list[0].id);
      return;
    }
    // Phone: two taps in a row play from there; one tap types there (or opens the comment on those words).
    const now = e.timeStamp;
    const prev = lastTap.current;
    lastTap.current = { at: now, x: e.clientX, y: e.clientY };
    if (prev && now - prev.at < DOUBLE_TAP && Math.hypot(prev.x - e.clientX, prev.y - e.clientY) < 40) {
      if (tapTimer.current != null) { window.clearTimeout(tapTimer.current); tapTimer.current = null; }
      lastTap.current = null;
      if (armed) { (document.activeElement as HTMLElement | null)?.blur(); setArmed(false); }
      playAt(n, e.clientX, e.clientY);
      return;
    }
    if (armed) return;                                  // typing: a tap only moves the caret
    const x = e.clientX, y = e.clientY;
    if (tapTimer.current != null) window.clearTimeout(tapTimer.current);
    tapTimer.current = window.setTimeout(() => {
      tapTimer.current = null;
      const list = threadsAt.get(n);
      if (list?.length) { pickThreads(list); flashLater(talkOf.get(list[0].id) || list[0].id); return; }
      if (playingRef.current) stop();
      tapAt.current = { x, y };
      setArmed(true);
    }, DOUBLE_TAP);
  };

  const onEditorDoubleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (touch) return;                                  // phones count their own taps (onEditorClick)
    const t = e.target as HTMLElement;
    const n = unitAtPoint(e.clientX, e.clientY, t);
    if (n == null) return;
    playAt(n, e.clientX, e.clientY);
  };

  // Touch: after the second tap, put the caret where the finger was and open the keyboard.
  useLayoutEffect(() => {
    const root = editorRef.current;
    if (!armed || !root) return;
    root.focus({ preventScroll: true });
    const p = tapAt.current;
    const doc_ = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null };
    const r = p && doc_.caretRangeFromPoint?.(p.x, p.y);
    if (r && root.contains(r.startContainer)) { const s = window.getSelection(); s?.removeAllRanges(); s?.addRange(r); }
  }, [armed]);

  // The comment mark next to selected words.
  useEffect(() => {
    const onSel = () => setSelBtn(selectionDraft());
    document.addEventListener('selectionchange', onSel);
    return () => document.removeEventListener('selectionchange', onSel);
  }, [selectionDraft]);

  // Arrow keys and Space outside the text.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.tagName === 'SELECT')) return;
      if (e.code === 'Space') { e.preventDefault(); void toggle(); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); void playFrom(curRef.current + 1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); void playFrom(Math.max(0, curRef.current - 1)); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && undoRef.current.length) {
        e.preventDefault();
        if (e.shiftKey) redo(); else undo();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [playFrom, toggle, undo, redo]);

  // Follow the voice only while it plays, and only when the sentence has gone off the screen. Reading the doc again
  // (approving a suggestion, Dan's fix) changes `says` and `cur` too, and that must not move the page (11/20).
  useEffect(() => {
    if (!playingRef.current || !says[cur] || Date.now() - lastUserScroll.current < 5000 || editing()) return;
    revealUnit(says[cur].n);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur]);

  const changeVoice = (v: string) => {
    stop();
    try { localStorage.setItem(VOICE_KEY, v); } catch { /* ignore */ }
    setVoice(v);
  };

  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    const ms = navigator.mediaSession;
    ms.setActionHandler('play', () => { if (!playingRef.current) void toggle(); });
    ms.setActionHandler('pause', () => stop());
    ms.setActionHandler('previoustrack', () => void playFrom(Math.max(0, curRef.current - 1)));
    ms.setActionHandler('nexttrack', () => void playFrom(curRef.current + 1));
    return () => { for (const a of ['play', 'pause', 'previoustrack', 'nexttrack'] as const) ms.setActionHandler(a, null); };
  }, [playFrom, stop, toggle]);

  const sendComment = async (text: string) => {
    if (!draft) return;
    try {
      const at = units.find(u => u.n === draft.n);
      const sentence = at && 'text' in at ? at.text : '';
      await listenApi.addComment(docId, { text, quote: draft.quote, start: draft.start, sentence });
      const list = await loadComments();   // the mark stays until the comment itself shows there
      setDraft(null);
      setSheet(null);
      const made = list?.slice().reverse().find(t => t.quote === draft.quote);
      if (made) setActive(made.id);
      toast('コメントしました。ダンが返事をします');
    } catch (e) { toast.error(errorText(e)); throw e; }
  };

  const sendReply = (t: Thread) => async (text: string) => {
    try { await listenApi.reply(docId, t.id, text); await loadComments(); } catch (e) { toast.error(errorText(e)); throw e; }
  };
  /** A comment on a suggestion's card: the thread already talking about it goes on, or a new one starts. */
  const commentOnSuggestion = (sg: Suggestion) => async (text: string) => {
    if (!canComment) { toast.error('お客さんも開けるドキュメントなので、ここからはコメントできません。作業用の台本で書いてください。'); throw new Error('no comment'); }
    try {
      const open = sugTalk.get(sg.id)?.threads.filter(t => !t.resolved) || [];
      const last = open[open.length - 1];
      if (last) await listenApi.reply(docId, last.id, text, sg);
      else {
        const at = unitByN.get(sg.n);
        await listenApi.addComment(docId, {
          text, quote: (sg.ins || sg.del).trim().slice(0, 400),
          start: at?.kind === 'say' ? at.start : null, sentence: at && 'text' in at ? at.text : '', suggestion: sg,
        });
      }
      await loadComments();
      setActive(sg.id);
      toast('コメントしました。ダンが返事をします');
    } catch (e) { toast.error(errorText(e)); throw e; }
  };
  const settleThread = (t: Thread) => async (reopen: boolean) => {
    try { await listenApi.settle(docId, t.id, reopen); await loadComments(); } catch (e) { toast.error(errorText(e)); }
  };
  const decide = useCallback(async (s: Suggestion, accept: boolean) => {
    try {
      await settle({ focus: false, play: false });
      await listenApi.decide(docId, s.id, accept);
      undoRef.current = []; redoRef.current = [];
      const here = saysRef.current[curRef.current];
      await load(here ? { start: here.start, text: here.text } : undefined);
      setSheet(null);
      setActive(null);
    } catch (e) {
      toast.error(errorText(e));
      await load();
    }
  }, [docId, load, settle]);

  /** Every suggestion at once (11/20 本人「全部眺めてまとめて承認できる選択肢があった方が楽」「全却下ボタンも作って」). */
  const decideAll = useCallback(async (accept: boolean) => {
    setAllBusy(accept ? 'accept' : 'reject');
    try {
      await settle({ focus: false, play: false });
      const r = accept ? await listenApi.acceptAll(docId) : await listenApi.rejectAll(docId);
      const n = 'accepted' in r ? r.accepted : r.rejected;
      const verb = accept ? '承認' : '却下';
      undoRef.current = []; redoRef.current = [];
      const here = saysRef.current[curRef.current];
      await load(here ? { start: here.start, text: here.text } : undefined);
      setSheet(null);
      setActive(null);
      toast(r.failed ? `${n}件を${verb}しました。${r.failed}件は別の提案と重なっていたので残しました。` : `${n}件の提案をすべて${verb}しました`);
    } catch (e) {
      toast.error(errorText(e));
      await load();
    } finally {
      setAllBusy(null);
    }
  }, [docId, load, settle]);

  const switchMode = useCallback(async (m: EditMode) => {
    if (m === modeRef.current) return;
    // What was typed so far goes in the way it was typed.
    await flush();
    modeRef.current = m;
    setMode(m);
  }, [flush]);

  const focusUnit = useCallback((n: number) => {
    lastUserScroll.current = Date.now();
    revealUnit(n);
  }, []);
  /** From a card to its words: they come into view and glow a moment (only when the card was not already the one). */
  const goText = (id: string, n: number, quote?: string) => {
    const again = active === id;
    setActive(id);
    focusUnit(n);
    if (again) return;
    const root = editorRef.current;
    if (!root) return;
    let r: Range | null = null;
    const spans = root.querySelectorAll(`[data-sug="${CSS.escape(id)}"]`);
    if (spans.length) { r = document.createRange(); r.setStartBefore(spans[0]); r.setEndAfter(spans[spans.length - 1]); }
    else r = quoteRange(root, n, quote || '');
    flashRange(r);
  };
  /** From words to their card (PC: the card beside the text). */
  const showCard = (id: string) => {
    if (active === id) return;
    setActive(id);
    flashLater(id);
  };
  const flashLater = (id: string) => window.setTimeout(() => flashCard(id), 60);
  function pickSuggestion(id: string) {
    setActive(id);
    if (!wide) setSheet({ kind: 'suggestion', id });
  }
  function pickThreads(list: Thread[]) {
    const sid = list.map(t => talkOf.get(t.id)).find(Boolean);
    if (sid && list.every(t => talkOf.has(t.id))) { pickSuggestion(sid); return; }
    setActive(list[0]?.id || null);
    if (!wide) setSheet({ kind: 'threads', ids: list.map(t => t.id) });
  }

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

  // ---------------------------------------------------------------- where Dan is (11/20)
  // A blue line beside the words Dan works on, outside the text (nothing in the text moves; the owner's screen is never
  // scrolled for it). When those words are out of sight, the edge of the text toward them glows softly instead.
  const [bars, setBars] = useState<{ n: number; job: string; top: number; height: number }[]>([]);
  const [gutter, setGutter] = useState(0);
  const layoutBars = useCallback(() => {
    const box = contentRef.current, root = editorRef.current, sc = scrollerRef.current;
    if (!box || !root) return;
    const top0 = box.getBoundingClientRect().top;
    const next: { n: number; job: string; top: number; height: number }[] = [];
    danUnits.forEach((job, n) => {
      let a = Infinity, b = -Infinity;
      root.querySelectorAll(`[data-n="${n}"]`).forEach(el => {
        for (const r of Array.from(el.getClientRects())) { if (r.height) { a = Math.min(a, r.top); b = Math.max(b, r.bottom); } }
      });
      if (a < b) next.push({ n, job, top: Math.round(a - top0), height: Math.round(b - a) });
    });
    setBars(was => JSON.stringify(was) === JSON.stringify(next) ? was : next);
    if (sc) setGutter(Math.round(box.getBoundingClientRect().left - sc.getBoundingClientRect().left));
  }, [danUnits]);
  useLayoutEffect(() => { layoutBars(); }, [layoutBars, html, build, doc, threads]);
  useEffect(() => {
    if (!contentRef.current || !danUnits.size) return;
    const ro = new ResizeObserver(() => layoutBars());
    ro.observe(contentRef.current);
    return () => ro.disconnect();
  }, [layoutBars, danUnits.size, doc]);
  const [glow, setGlow] = useState<{ dir: 'up' | 'down'; left: number; width: number; y: number; n: number } | null>(null);
  useEffect(() => {
    const sc = scrollerRef.current;
    const target = bars.find(b => b.job === shownJob) || bars[0];
    if (!sc || !target) { setGlow(null); return; }
    let raf = 0;
    const look = () => {
      raf = 0;
      const el = document.querySelector(`[data-testid="script-editor"] [data-n="${target.n}"]`) as HTMLElement | null;
      const box = sc.getBoundingClientRect();
      const r = el?.getBoundingClientRect();
      if (!r) { setGlow(null); return; }
      const dir = r.bottom < box.top + 4 ? 'up' : r.top > box.bottom - 4 ? 'down' : null;
      setGlow(was => {
        if (!dir) return null;
        const y = dir === 'up' ? box.top : box.bottom;
        if (was && was.dir === dir && was.y === y && was.n === target.n && was.left === box.left) return was;
        return { dir, left: box.left, width: box.width, y, n: target.n };
      });
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(look); };
    look();
    sc.addEventListener('scroll', on, { passive: true });
    window.addEventListener('resize', on);
    return () => { sc.removeEventListener('scroll', on); window.removeEventListener('resize', on); if (raf) cancelAnimationFrame(raf); };
  }, [bars, shownJob]);
  /** From Dan's mark beside the words to the card of the comment his job is about, with its log open. */
  const openJob = (id: string) => {
    setJobSel(id);
    setExpanded(id);
    const j = jobs.find(x => x.id === id);
    for (const cid of j?.comment_ids || []) {
      const sid = talkOf.get(cid);
      if (sid && suggestions.some(x => x.id === sid)) { pickSuggestion(sid); flashLater(sid); return; }
      const t = threads.find(x => x.id === cid);
      if (t) { pickThreads([t]); flashLater(t.id); return; }
    }
  };
  const danLiveValue = useMemo(() => ({
    // The job working on it, else the one that ended a little while ago (the list keeps ended ones for 15 minutes).
    jobFor: (tid: string) => jobs.find(x => isLive(x) && x.comment_ids.includes(tid)) || jobs.find(x => x.comment_ids.includes(tid)) || null,
    expanded,
    toggle: (id: string) => { setJobSel(id); setExpanded(e => (e === id ? null : id)); },
  }), [jobs, expanded]);

  // ---------------------------------------------------------------- 見本の台本と比べる (11/20)
  useEffect(() => {
    let live = true;
    listenApi.references(docId).then(r => { if (live) setRefs(r.refs || []); }).catch(() => {});
    return () => { live = false; };
  }, [docId]);
  useEffect(() => { localStorage.setItem(COMPARE_KEY, compare ? '1' : '0'); }, [compare]);
  /** The headings of the spoken part: every read heading under ◎台本 (【】 and the ▼ inside them), in order. */
  const heads = useMemo<SectionHead[]>(() => {
    const hs = units.filter(u => u.kind === 'heading' && u.read) as Extract<ListenUnit, { kind: 'heading' }>[];
    const i = hs.findIndex(h => h.text.replace(/\s/g, '') === '◎台本');
    return (i >= 0 ? hs.slice(i + 1) : hs).map(h => ({ n: h.n, text: h.text, level: h.level }));
  }, [units]);
  // Where the owner is in the script: the last section heading above a third of the way down the script's box.
  useEffect(() => {
    const box = scrollerRef.current;
    if (!comparing || !box || !heads.length) return;
    let raf = 0;
    const find = () => {
      raf = 0;
      const line = box.getBoundingClientRect().top + box.clientHeight * 0.33;
      let at: number | null = heads[0].n;
      for (const h of heads) {
        const el = document.getElementById(`u-${h.n}`);
        if (el && el.getBoundingClientRect().top <= line) at = h.n;
      }
      setHereHead(at);
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(find); };
    find();
    box.addEventListener('scroll', on, { passive: true });
    window.addEventListener('resize', on);
    return () => { box.removeEventListener('scroll', on); window.removeEventListener('resize', on); if (raf) cancelAnimationFrame(raf); };
  }, [comparing, heads, doc]);
  const goHead = useCallback((n: number) => {
    const el = document.getElementById(`u-${n}`), box = scrollerRef.current;
    if (!el || !box) return;
    lastUserScroll.current = Date.now();
    box.scrollTo({ top: el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 12, behavior: 'smooth' });
  }, []);

  const remaining = useMemo(() => {
    let sec = 0;
    for (let i = cur; i < says.length; i++) sec += Math.max(0.1, (says[i].seconds ?? says[i].speak.length * 0.14 + 0.25) - LEAD);
    return sec / rate;
  }, [cur, rate, says]);

  // Where the owner is, for the chat's 「ここ」 (app/services/script_rooms.py): the sentence at the caret, the words
  // picked, whether it plays, whether a thumbnail is open. Sent a moment after it changes.
  const stateTimer = useRef<number | null>(null);
  const lastState = useRef('');
  const tellState = useCallback(() => {
    if (stateTimer.current) window.clearTimeout(stateTimer.current);
    stateTimer.current = window.setTimeout(() => {
      const root = editorRef.current, sel = window.getSelection();
      let para: number | null = null, sentence = '', selection = '';
      if (root && sel?.rangeCount && root.contains(sel.anchorNode)) {
        const n = unitN(sel.anchorNode);
        const u = n != null ? units.find(x => x.n === n) : undefined;
        if (u && 'text' in u) { sentence = u.text; para = (u as { para?: number }).para ?? null; }
        selection = sel.toString().slice(0, 4000);
      } else if (playingRef.current && says[curRef.current]) {
        sentence = says[curRef.current].text; para = says[curRef.current].para;
      }
      const body = { para, sentence, selection, playing: playingRef.current, thumb: thumb ? `${thumb.order + 1}枚目` : '' };
      const key = JSON.stringify(body);
      if (key === lastState.current) return;
      lastState.current = key;
      void listenApi.state(docId, body).catch(() => {});
    }, 1200);
  }, [docId, units, says, thumb]);
  useEffect(() => {
    document.addEventListener('selectionchange', tellState);
    return () => document.removeEventListener('selectionchange', tellState);
  }, [tellState]);
  useEffect(() => { tellState(); }, [playing, cur, thumb, tellState]);

  // A thumbnail work Dan (or another screen) changed goes into the doc's picture: the server does it when asked.
  useEffect(() => {
    if (thumb) return;
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') void listenApi.thumbs(docId).catch(() => {}); }, 15000);
    return () => window.clearInterval(t);
  }, [docId, thumb]);

  if (loadError && !doc) {
    return <div className="p-6 text-[15px] text-red-700">{loadError}</div>;
  }
  if (!doc) {
    return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" />台本を読んでいます…</div>;
  }

  const sheetThreads = sheet?.kind === 'threads' ? threads.filter(t => sheet.ids.includes(t.id)) : sheet?.kind === 'all' ? visibleThreads.filter(t => !talkOf.has(t.id)) : [];
  const sheetSuggestion = sheet?.kind === 'suggestion' ? suggestions.find(s => s.id === sheet.id) : undefined;

  const toggleChat = () => {
    if (!screenWide) { setPhoneChat(v => !v); return; }
    setChatOpen(v => { localStorage.setItem(CHAT_KEY, v ? '0' : '1'); return !v; });
  };
  const thumbTitle = thumb ? `${doc.title.replace(/\s*台本.*$/, '')} サムネ${thumb.order + 1}` : '';

  return (
    <DanLiveContext.Provider value={danLiveValue}>
    <div className="flex h-dvh flex-col bg-[#faf8f4] text-stone-900">
      <style>{'::highlight(cm-draft){background-color:rgb(252 211 77 / 0.75)}'}</style>
      <header className="shrink-0 border-b border-stone-200 bg-white/90 px-3 py-2 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-6xl items-center gap-2">
          <Volume2 className="h-4 w-4 shrink-0 text-amber-700" />
          <div className="min-w-0 flex-1 truncate text-[14px] font-semibold">{doc.title}</div>
          <div role="radiogroup" aria-label="書き方" className="flex shrink-0 overflow-hidden rounded-md border border-stone-300 text-[12px]">
            {([['edit', '編集', Pencil], ['suggest', '提案', PenLine]] as const).map(([m, label, Icon]) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                title={m === 'edit' ? '打った直しがそのままドキュメントに入ります' : '打った直しが自分の提案になります（消した所は線で残ります）'}
                onClick={() => void switchMode(m)}
                className={cn('flex items-center gap-1 px-1.5 py-1 sm:px-2', mode === m
                  ? (m === 'suggest' ? 'bg-violet-600 text-white' : 'bg-stone-800 text-white')
                  : 'bg-white text-stone-700')}
              >
                <Icon className="hidden h-3.5 w-3.5 sm:block" /><span>{label}</span>
              </button>
            ))}
          </div>
          <button
            type="button"
            data-testid="chat-toggle"
            aria-pressed={screenWide ? chatOpen : phoneChat}
            title="ダンと話す（台本の相談・作り直し・サムネ）"
            onMouseDown={e => e.preventDefault()}
            onClick={toggleChat}
            className={cn('flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[12px]', (screenWide ? chatOpen : phoneChat)
              ? 'border-sky-700 bg-sky-700 text-white' : 'border-stone-300 bg-white text-stone-700')}
          >
            <Bot className="h-3.5 w-3.5" /><span>ダン</span>
          </button>
          {refs.length > 0 && (
            <button
              type="button"
              data-testid="compare-toggle"
              aria-pressed={compare}
              title="参考にした動画の台本を横に並べて比べます"
              onClick={() => setCompare(v => !v)}
              className={cn('flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[12px]', compare
                ? 'border-sky-700 bg-sky-700 text-white' : 'border-stone-300 bg-white text-stone-700')}
            >
              <Columns2 className="h-3.5 w-3.5" /><span>見本<span className="hidden sm:inline">と比べる</span></span>
            </button>
          )}
          <button
            type="button"
            onClick={() => (wide ? setShowResolved(v => !v) : setSheet({ kind: 'all' }))}
            className="flex shrink-0 items-center gap-1 rounded-md border border-stone-300 px-2 py-1 text-[12px] text-stone-700"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            {wide ? (showResolved ? '解決済みを隠す' : `コメント ${openCount}`) : openCount}
          </button>
          <button
            type="button"
            data-testid="image-add"
            aria-label="画像を入れる"
            title="押した文の下に画像を入れます（本文に貼り付け・ドラッグでも入ります）"
            disabled={imageBusy || stale}
            onMouseDown={e => e.preventDefault()}
            onClick={() => fileRef.current?.click()}
            className="flex shrink-0 items-center gap-1 rounded-md border border-stone-300 bg-white px-2 py-1 text-[12px] text-stone-700 disabled:opacity-40"
          >
            {imageBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">画像</span>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            className="hidden"
            onChange={e => {
              const f = e.target.files?.[0];
              e.target.value = '';
              if (f) void putImage(f);
            }}
          />
          <select
            aria-label="声"
            value={voice}
            onChange={e => changeVoice(e.target.value)}
            className="max-w-[4.5rem] shrink rounded-md border border-stone-300 bg-white px-1 py-1 text-[12px] sm:max-w-[8rem] sm:px-1.5"
          >
            {doc.voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          {(
            <a
              href={`https://docs.google.com/document/d/${doc.doc_id}/edit`}
              target="_blank"
              rel="noreferrer"
              aria-label="ドキュメント"
              className="flex shrink-0 items-center gap-1 rounded-md border border-stone-300 px-2 py-1 text-[12px] text-stone-700"
            >
              <ExternalLink className="h-3.5 w-3.5" /><span className="hidden sm:inline">ドキュメント</span>
            </a>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
      <div className={cn('flex min-h-0 flex-1', screenWide ? 'flex-row' : 'flex-col')}>
      <div
        ref={scrollerRef}
        data-scroller
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
        onWheel={() => { lastUserScroll.current = Date.now(); }}
        onTouchMove={() => { lastUserScroll.current = Date.now(); }}
      >
        <div className="mx-auto flex max-w-6xl gap-6 px-3 pb-44 pt-4 sm:px-6">
          <div ref={contentRef} className="relative min-w-0 max-w-3xl flex-1">
            <div
              ref={editorRef}
              data-testid="script-editor"
              contentEditable={(!touch || armed) && !stale}
              suppressContentEditableWarning
              spellCheck={false}
              onInput={() => changed()}
              onKeyDown={onEditorKey}
              onClick={onEditorClick}
              onDoubleClick={onEditorDoubleClick}
              onCompositionStart={() => {
                composingRef.current = true;
                remember('compose');
                const root = editorRef.current, sel = window.getSelection();
                compStart.current = root && sel?.rangeCount ? getPos(root, sel.getRangeAt(0).startContainer, sel.getRangeAt(0).startOffset) : null;
              }}
              onCompositionEnd={() => {
                composingRef.current = false;
                if (modeRef.current === 'suggest') ownComposed();
                changed();
              }}
              onPaste={e => {
                e.preventDefault();
                const pic = Array.from(e.clipboardData.files || []).find(f => f.type.startsWith('image/'));
                if (pic) {
                  const sel = window.getSelection();
                  void putImage(pic, sel?.rangeCount ? sel.getRangeAt(0).startContainer : null);
                  return;
                }
                const text = e.clipboardData.getData('text/plain');
                if (!text) return;
                remember('paste', true);
                if (modeRef.current === 'suggest') {
                  const root = editorRef.current, sel = window.getSelection();
                  if (!root || !sel?.rangeCount) return;
                  if (!sel.isCollapsed) {
                    const r = sel.getRangeAt(0);
                    const start = getPos(root, r.startContainer, r.startOffset);
                    const kept = strike(root, r);
                    if (kept === 'para') { toast('提案モードでは段落をまたいで置き換えられません。'); return; }
                    if (start) setPos(root, { line: start.line, off: start.off + kept });
                  }
                  addOwn(root, text.replace(/\r\n?|\n/g, ' '));
                  changed();
                  return;
                }
                document.execCommand('insertText', false, text.replace(/\r\n?/g, '\n'));
              }}
              onDragOver={e => { if (Array.from(e.dataTransfer.items || []).some(i => i.kind === 'file')) e.preventDefault(); }}
              onDrop={e => {
                const pic = Array.from(e.dataTransfer.files || []).find(f => f.type.startsWith('image/'));
                if (!pic) return;
                e.preventDefault();
                const at = (document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }).caretRangeFromPoint?.(e.clientX, e.clientY);
                void putImage(pic, at?.startContainer || (e.target as Node));
              }}
              onBlur={() => {
                if (touch) setArmed(false);
                if (dirtyRef.current) void settle({ focus: false, play: false });
              }}
              className={cn(
                'whitespace-pre-wrap break-words outline-none caret-stone-900',
                '[&_[data-on]]:rounded-[3px] [&_[data-on]]:bg-amber-200/70 [&_[data-on]]:[box-decoration-break:clone]',
                '[&_[data-cm]]:bg-yellow-100 [&_[data-on][data-cm]]:bg-amber-200/70',
                // The words Dan is on (11/20): a pale blue, under the voice's band.
                '[&_[data-dan]]:bg-sky-100 [&_[data-cm][data-dan]]:bg-sky-100 [&_[data-on][data-dan]]:bg-amber-200/70',
              )}
            />
            {bars.map((b, i) => (
              <button
                key={b.n}
                type="button"
                data-testid="dan-bar"
                aria-label="ダンの作業の様子を見る"
                title="ダンがここを直しています（押すと作業の様子）"
                onMouseDown={e => e.preventDefault()}
                onClick={() => openJob(b.job)}
                style={{ top: b.top, height: Math.max(b.height, 14) }}
                className="absolute -left-2 w-1.5 rounded-full bg-sky-500 shadow-[0_0_8px_rgb(14_165_233/0.7)] motion-safe:animate-pulse sm:-left-3.5"
              >
                {i === 0 && gutter >= 64 && (
                  <span className="pointer-events-none absolute right-3 top-0 whitespace-nowrap rounded-full bg-sky-600 px-1.5 py-0.5 text-[10.5px] font-semibold text-white shadow">ダン</span>
                )}
              </button>
            ))}
            {unplaced.length > 0 && (
              <div className="mt-10 border-t border-stone-300 pt-3">
                <div className="mb-2 text-[13px] font-semibold text-stone-600">本文の場所が分からないコメント</div>
                <div className="space-y-2">
                  {unplaced.map(t => (
                    <ThreadCard key={t.id} thread={t} active={active === t.id} onFocus={() => setActive(t.id)}
                      onReply={sendReply(t)} onSettle={settleThread(t)} canWrite={canComment} />
                  ))}
                </div>
              </div>
            )}
            {(
              <div className="mt-8 text-center text-[12px] text-stone-400">
                {touch ? '文を2回続けて押すと、そこから聞けます（もう一度2回押すと止まります）。1回押すとそこで直せます。' : '文をダブルクリックすると、そこから聞けます（鳴っている文をもう一度ダブルクリックすると止まります）。Google ドキュメントと同じように直せて、打つのを止めると自動でドキュメントに入ります。'}
                文字を選ぶとコメントできます。提案にもコメントでき、提案の文字もそのまま直せます。上の「提案」にすると、打った直しが自分の提案になります。
              </div>
            )}
          </div>

          {wide && (
            <div ref={marginRef} className="relative w-72 shrink-0">
              {draft && (
                <div ref={el => { if (el) cardRefs.current.set('draft', el); else cardRefs.current.delete('draft'); }}
                  data-anchor={draft.n} className="absolute inset-x-0 z-10">
                  <Composer quote={draft.quote} onSend={sendComment} onCancel={() => setDraft(null)} />
                </div>
              )}
              {visibleThreads.filter(t => place.has(t.id) && !talkOf.has(t.id)).map(t => (
                <div key={t.id} ref={el => { if (el) cardRefs.current.set(t.id, el); else cardRefs.current.delete(t.id); }}
                  data-card={t.id} data-anchor={place.get(t.id)} className={cn('absolute inset-x-0', active === t.id && 'z-10')}>
                  <ThreadCard thread={t} active={active === t.id} onFocus={() => goText(t.id, place.get(t.id)!, t.quote)}
                    onReply={sendReply(t)} onSettle={settleThread(t)} canWrite={canComment} />
                </div>
              ))}
              {suggestions.map(s => (
                <div key={s.id} ref={el => { if (el) cardRefs.current.set(s.id, el); else cardRefs.current.delete(s.id); }}
                  data-card={s.id} data-anchor={s.n} className={cn('absolute inset-x-0', active === s.id && 'z-10')}>
                  <SuggestionCard s={s} active={active === s.id} onFocus={() => goText(s.id, s.n)} onDecide={a => decide(s, a)}
                    threads={sugTalk.get(s.id)?.threads} earlier={sugTalk.get(s.id)?.earlier} canComment={canComment} onComment={commentOnSuggestion(s)} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {comparing && (
        <div data-testid="ref-panel" className={cn('flex shrink-0', screenWide ? 'w-[46%] max-w-[760px]' : 'h-[42dvh]')}>
          <RefsPanel refs={refs} heads={heads} here={hereHead} onGo={goHead} side={screenWide} />
        </div>
      )}
      </div>
      <div className="shrink-0 border-t border-stone-200 bg-white/95 px-3 pb-[max(env(safe-area-inset-bottom),0.5rem)] pt-2 backdrop-blur sm:px-6">
        <div className="mx-auto max-w-3xl">
          {/* One row: where it is on the left, the player in the middle, 提案をすべて承認 on the right — nothing stacked
              above the player, so the script keeps its height (11/20 本人「上下に重ねるんじゃなくて右側に」). */}
          <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-1">
            <div className="min-w-0 text-[11.5px] leading-tight text-stone-500 sm:text-[12px]">
              <div className="tabular-nums">{says.length ? `${cur + 1} / ${says.length}文` : '読む文がありません'}</div>
              <div className="flex items-center gap-1">
                {saving && <><Loader2 className="h-3 w-3 shrink-0 animate-spin" /><span className="truncate">ドキュメントに入れています</span></>}
                {!saving && waiting && <><Loader2 className="h-3 w-3 shrink-0 animate-spin" /><span className="truncate">声を作っています</span></>}
                {!saving && !waiting && says.length > 0 && `残り約${fmtMinutes(remaining)}`}
              </div>
            </div>
            <div className="flex items-center justify-center gap-1 sm:gap-3">
              <button type="button" aria-label="前の文" onClick={() => void playFrom(Math.max(0, cur - 1))} className="rounded-full p-2 text-stone-700 active:bg-stone-200 sm:p-2.5">
                <SkipBack className="h-6 w-6" />
              </button>
              <button
                type="button"
                aria-label={playing ? '止める' : '聞く'}
                onClick={() => void toggle()}
                disabled={!says.length}
                className="flex h-14 w-14 items-center justify-center rounded-full bg-amber-600 text-white shadow active:bg-amber-700 disabled:opacity-40"
              >
                {playing ? <Pause className="h-7 w-7" /> : <Play className="ml-0.5 h-7 w-7" />}
              </button>
              <button type="button" aria-label="次の文" onClick={() => void playFrom(cur + 1)} className="rounded-full p-2 text-stone-700 active:bg-stone-200 sm:p-2.5">
                <SkipForward className="h-6 w-6" />
              </button>
            </div>
            <div className="flex justify-end">
              {/* Both only while there is something to decide (11/20 本人「無ければボタン自体見ないように」). On a phone the two
                  sit one above the other in the player's height; wider, side by side. */}
              {suggestions.length > 0 && (
                <div className="flex flex-col items-end gap-1 sm:flex-row sm:items-center sm:gap-1.5">
                  <button
                    type="button"
                    disabled={!!allBusy}
                    onClick={() => void decideAll(true)}
                    aria-label={`提案をすべて承認（${suggestions.length}）`}
                    className="flex items-center gap-1 rounded-full bg-emerald-600 px-2.5 py-1 text-[12px] font-semibold text-white shadow-sm active:bg-emerald-700 disabled:opacity-50"
                  >
                    {allBusy === 'accept' ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" /> : <CheckCheck className="h-3.5 w-3.5 shrink-0" />}
                    <span className="whitespace-nowrap">すべて承認（{suggestions.length}）</span>
                  </button>
                  <button
                    type="button"
                    disabled={!!allBusy}
                    onClick={() => void decideAll(false)}
                    aria-label={`提案をすべて却下（${suggestions.length}）`}
                    className="flex items-center gap-1 rounded-full border border-stone-300 bg-white px-2.5 py-1 text-[12px] font-semibold text-stone-700 shadow-sm active:bg-stone-100 disabled:opacity-50"
                  >
                    {allBusy === 'reject' ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" /> : <X className="h-3.5 w-3.5 shrink-0" />}
                    <span className="whitespace-nowrap">すべて却下</span>
                  </button>
                </div>
              )}
            </div>
          </div>
          {/* All speeds on one screen: on a phone they wrap to a second line instead of hiding off the side (11/20 4倍). */}
          <div className="mt-2 flex flex-wrap items-center justify-center gap-1">
            {RATES.map(r => (
              <button
                key={r}
                type="button"
                onClick={() => setRate(r)}
                className={cn(
                  'shrink-0 rounded-full border px-2 py-1 text-[13px] tabular-nums sm:px-2.5',
                  r === rate ? 'border-amber-600 bg-amber-600 text-white' : 'border-stone-300 bg-white text-stone-700',
                )}
              >
                {r}倍
              </button>
            ))}
          </div>
        </div>
      </div>
      {thumb && (
        <div data-testid="listen-thumb" className={cn('z-40 bg-background text-foreground', screenWide ? 'absolute inset-0' : 'fixed inset-0')}>
          <ListenThumb
            docId={docId}
            target={thumb}
            title={thumbTitle}
            compact={!screenWide}
            phoneChat={screenWide ? null : (lead => <ListenChat docId={docId} lead={lead} />)}
            onClose={() => setThumb(null)}
          />
        </div>
      )}
      </div>
      {chatSide && (
        <aside aria-label="ダンと台本" className="w-[400px] shrink-0 border-l border-stone-200 bg-background text-foreground">
          <ListenChat docId={docId} />
        </aside>
      )}
      </div>
      {!screenWide && phoneChat && (
        <div className="fixed inset-x-0 bottom-0 top-12 z-40 flex flex-col overflow-hidden rounded-t-2xl border-t border-stone-200 bg-background text-foreground shadow-2xl">
          <ListenChat docId={docId} lead={
            <button type="button" aria-label="閉じる" onClick={() => setPhoneChat(false)} className="rounded-full p-1 text-stone-500 active:bg-stone-200">
              <X className="h-5 w-5" />
            </button>} />
        </div>
      )}

      {glow && (
        <button
          type="button"
          data-testid="dan-glow"
          aria-label="ダンが直している所へ"
          onClick={() => focusUnit(glow.n)}
          style={{ left: glow.left, width: glow.width, top: glow.dir === 'up' ? glow.y : glow.y - 28 }}
          className={cn('fixed z-20 h-7 motion-safe:animate-pulse', glow.dir === 'up'
            ? 'bg-gradient-to-b from-sky-400/45 to-transparent' : 'bg-gradient-to-t from-sky-400/45 to-transparent')}
        />
      )}

      {selBtn && (
        <button
          type="button"
          aria-label="コメントを追加"
          title="コメントを追加（Ctrl+Alt+M）"
          onMouseDown={e => e.preventDefault()}
          onClick={() => openDraft({ quote: selBtn.quote, n: selBtn.n, start: selBtn.start, from: selBtn.from, to: selBtn.to })}
          style={wide
            ? { left: selBtn.x - 28, top: Math.max(selBtn.y - 4, 56) }
            : { left: Math.max(8, selBtn.x - 40), top: Math.min(selBtn.y + 10, window.innerHeight - 190) }}
          className="fixed z-30 flex h-8 w-8 items-center justify-center rounded-full border border-stone-200 bg-white text-stone-700 shadow-md hover:bg-stone-50"
        >
          <MessageSquarePlus className="h-[18px] w-[18px]" />
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
          {sheetSuggestion && <div data-card={sheetSuggestion.id}><SuggestionCard s={sheetSuggestion} active onDecide={a => decide(sheetSuggestion, a)}
            threads={sugTalk.get(sheetSuggestion.id)?.threads} earlier={sugTalk.get(sheetSuggestion.id)?.earlier}
            canComment={canComment} onComment={commentOnSuggestion(sheetSuggestion)} /></div>}
          {sheet.kind === 'all' && (
            <label className="mb-2 flex items-center gap-1.5 text-[12px] text-stone-600">
              <input type="checkbox" checked={showResolved} onChange={e => setShowResolved(e.target.checked)} />解決済みも見る
            </label>
          )}
          {sheet.kind === 'all' && suggestions.length > 0 && (
            <div className="mb-3 space-y-2">
              {suggestions.map(s => <SuggestionCard key={s.id} s={s} onFocus={() => { setSheet(null); goText(s.id, s.n); }} onDecide={a => decide(s, a)}
                threads={sugTalk.get(s.id)?.threads} earlier={sugTalk.get(s.id)?.earlier} canComment={canComment} onComment={commentOnSuggestion(s)} />)}
            </div>
          )}
          <div className="space-y-2">
            {sheetThreads.map(t => (
              <div key={t.id} data-card={t.id}><ThreadCard thread={t} active={active === t.id || sheet.kind === 'threads'}
                onFocus={() => { const n = place.get(t.id); if (n != null) { if (sheet.kind === 'all') setSheet(null); goText(t.id, n, t.quote); } else setActive(t.id); }}
                onReply={sendReply(t)} onSettle={settleThread(t)} canWrite={canComment} /></div>
            ))}
            {sheet.kind === 'all' && !sheetThreads.length && !suggestions.length && <div className="py-4 text-center text-[13px] text-stone-500">コメントはありません</div>}
          </div>
        </div>
      )}

    </div>
    </DanLiveContext.Provider>
  );
}
