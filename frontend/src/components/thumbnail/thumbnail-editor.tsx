'use client';

// エディターの中のサムネの画面（2026-11-18 本人「サムネの微調整の往復に時間がかかりすぎる」→「部品に分けたサムネ」
// 「描き込んで直す」）。背景・人物・文字・矢印を別々の部品で持ち、
// - 選ぶ: 部品をつかんで動かす・角で大きさ・上の丸で回す・右の欄で文字を打ち直す／色・縁・書体を変える
// - 書き込む: ペンで丸や矢印を描いて一言添えて送ると、ダンが直す（結果はこの欄にだけ出し、チャットには出さない）
// - 一覧で見る: YouTube の一覧と同じ小さい大きさで、ほかのサムネと並べて見る
// 保存は手を離した時に自動。ダンが直した形は1.5秒ごとに読み直して、目の前で変わる。

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ArrowLeft, ArrowDown, ArrowUp, Check, Copy, Download, Eye, EyeOff, LayoutGrid, Loader2, Lock, MessageSquare,
  MousePointer2, PenLine, Redo2, RotateCcw, Send, Sparkles, Trash2, Type, Undo2, Unlock, X,
} from 'lucide-react';
import { toast } from 'sonner';

import { ThumbCanvas, partCenter, type PartBox } from './thumb-canvas';
import {
  THUMB_FONTS, applyFinish, asThumbDoc, finishPart, loadThumbFonts, newPartId, removeFinish,
  type ThumbDoc, type ThumbFinishJob, type ThumbFontId, type ThumbInstruction, type ThumbMark, type ThumbPart, type ThumbTextPart,
} from './thumb-doc';

type Props = {
  roomId: string;
  contentId: string;
  title: string;
  compact?: boolean;
  phoneChat?: ((lead: ReactNode) => ReactNode) | null;
  onBack: () => void;
};

type JobState = { job_id: string; state: string; label: string; active: boolean; progress?: string | null; result?: string | null };

type Drag =
  | { kind: 'move'; id: string; start: [number, number]; orig: ThumbPart; before: ThumbDoc }
  | { kind: 'scale'; id: string; anchor: [number, number]; startDist: number; orig: ThumbPart; before: ThumbDoc }
  | { kind: 'rotate'; id: string; center: [number, number]; startAngle: number; orig: ThumbPart; before: ThumbDoc }
  | { kind: 'pen' };

const PEN_COLOR = '#ff2a2a';

function api(path: string, roomId: string) {
  return `/api/v1/production-assets/contents/${path}${path.includes('?') ? '&' : '?'}room_id=${encodeURIComponent(roomId)}`;
}

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function rotatePoint([x, y]: [number, number], [cx, cy]: [number, number], deg: number): [number, number] {
  const r = (deg * Math.PI) / 180;
  const c = Math.cos(r), s = Math.sin(r);
  return [cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c];
}

function scalePart(p: ThumbPart, [ax, ay]: [number, number], k: number): ThumbPart {
  if (p.type === 'image') {
    return { ...p, x: ax + (p.x - ax) * k, y: ay + (p.y - ay) * k, w: p.w * k, h: p.h * k };
  }
  const r = (v: number | undefined) => (v == null ? v : Math.round(v * k * 100) / 100);
  return {
    ...p,
    x: ax + (p.x - ax) * k,
    y: ay + (p.y - ay) * k,
    size: Math.max(4, Math.round(p.size * k * 10) / 10),
    stroke_width: r(p.stroke_width),
    letter_spacing: r(p.letter_spacing),
    line_height: r(p.line_height),
    bg: p.bg ? { ...p.bg, top: p.bg.top * k, bottom: p.bg.bottom * k, left: p.bg.left * k, right: p.bg.right * k, radius: (p.bg.radius || 0) * k } : p.bg,
    shadow: p.shadow ? { ...p.shadow, blur: (p.shadow.blur ?? 12) * Math.sqrt(k) } : p.shadow,
  };
}

function partLabel(p: ThumbPart) {
  if (p.name) return p.name;
  if (p.type === 'text') return `文字「${p.text.replace(/\n/g, ' ').slice(0, 12)}」`;
  return '絵';
}

export function ThumbnailEditor({ roomId, contentId, title, compact = false, phoneChat, onBack }: Props) {
  const [doc, setDoc] = useState<ThumbDoc | null>(null);
  const docRef = useRef<ThumbDoc | null>(null);
  docRef.current = doc;
  const baseRev = useRef<number>(-1);
  const dirty = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const [saving, setSaving] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<'select' | 'pen'>('select');
  const [boxes, setBoxes] = useState<Record<string, PartBox>>({});
  const undoStack = useRef<ThumbDoc[]>([]);
  const redoStack = useRef<ThumbDoc[]>([]);
  const [, bump] = useState(0);
  const drag = useRef<Drag | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [marks, setMarks] = useState<ThumbMark[]>([]);
  const [note, setNote] = useState('');
  const [resendOf, setResendOf] = useState<ThumbInstruction | null>(null);
  const [sending, setSending] = useState(false);
  const [jobs, setJobs] = useState<Record<string, JobState>>({});
  const [showInstr, setShowInstr] = useState<string | null>(null);
  const [listView, setListView] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [phoneChatOpen, setPhoneChatOpen] = useState(false);
  const [stageW, setStageW] = useState(800);
  const textRef = useRef<HTMLTextAreaElement | null>(null);
  const [finishJob, setFinishJob] = useState<ThumbFinishJob | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);

  // ── 読み込み・ダンの直しを読み直す・保存 ──
  const load = useCallback(async (force = false) => {
    try {
      const res = await fetch(api(`${encodeURIComponent(contentId)}/thumbnail`, roomId), { credentials: 'include', cache: 'no-store' });
      if (!res.ok) return;
      const j = (await res.json()) as { doc: unknown };
      const next = asThumbDoc(j.doc);
      const rev = next.rev ?? 0;
      if (force || (rev !== baseRev.current && !dirty.current && !drag.current)) {
        baseRev.current = rev;
        setDoc(next);
      }
    } catch { /* 次に読み直す */ }
  }, [roomId, contentId]);

  useEffect(() => {
    void load(true);
    const t = window.setInterval(() => void load(false), 1500);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => { void loadThumbFonts(doc); }, [doc]);

  const flush = useCallback(async () => {
    const d = docRef.current;
    if (!d || !dirty.current) return;
    dirty.current = false;
    setSaving('saving');
    try {
      const res = await fetch(api(`${encodeURIComponent(contentId)}/thumbnail`, roomId), {
        method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc: d }),
      });
      if (!res.ok) throw new Error(await res.text());
      const j = (await res.json()) as { rev: number };
      baseRev.current = j.rev;
      setDoc((cur) => (cur ? { ...cur, rev: j.rev } : cur));
      setSaving('saved');
    } catch {
      dirty.current = true;
      setSaving('error');
    }
  }, [roomId, contentId]);

  const scheduleSave = useCallback(() => {
    dirty.current = true;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => void flush(), 400);
  }, [flush]);

  useEffect(() => () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); void flush(); }, [flush]);

  // 1手の直し（元に戻すに積む）
  const commit = useCallback((next: ThumbDoc, before?: ThumbDoc) => {
    const prev = before || docRef.current;
    if (prev) {
      undoStack.current.push(clone(prev));
      if (undoStack.current.length > 100) undoStack.current.shift();
      redoStack.current = [];
    }
    setDoc(next);
    docRef.current = next;
    scheduleSave();
    bump((n) => n + 1);
  }, [scheduleSave]);

  const updatePart = useCallback((id: string, patch: Partial<ThumbPart> | ((p: ThumbPart) => ThumbPart)) => {
    const d = docRef.current;
    if (!d) return;
    commit({ ...d, parts: d.parts.map((p) => (p.id === id ? (typeof patch === 'function' ? patch(p) : ({ ...p, ...patch } as ThumbPart)) : p)) });
  }, [commit]);

  const undo = useCallback(() => {
    const prev = undoStack.current.pop();
    if (!prev || !docRef.current) return;
    redoStack.current.push(clone(docRef.current));
    setDoc(prev); docRef.current = prev; scheduleSave(); bump((n) => n + 1);
  }, [scheduleSave]);
  const redo = useCallback(() => {
    const next = redoStack.current.pop();
    if (!next || !docRef.current) return;
    undoStack.current.push(clone(docRef.current));
    setDoc(next); docRef.current = next; scheduleSave(); bump((n) => n + 1);
  }, [scheduleSave]);

  // ── 画面の大きさ ──
  const stageWrap = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = stageWrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      const ratio = doc ? doc.width / doc.height : 16 / 9;
      setStageW(Math.max(200, Math.floor(Math.min(r.width, (compact ? r.width / ratio : r.height) * ratio))));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [doc, compact]);
  const scale = doc ? stageW / doc.width : 1;

  const boxOf = useCallback((p: ThumbPart): PartBox => {
    if (p.type === 'image') return { x: p.x, y: p.y, w: p.w, h: p.h };
    return boxes[p.id] || { x: p.x, y: p.y - p.size, w: p.size * Math.max(1, p.text.length), h: p.size * 1.2 };
  }, [boxes]);

  const toSvg = (ev: { clientX: number; clientY: number }): [number, number] => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const m = svg.getScreenCTM();
    if (!m) return [0, 0];
    const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(m.inverse());
    return [pt.x, pt.y];
  };

  // ── 指・マウスの操作 ──
  const onPointerDown = (ev: React.PointerEvent<SVGSVGElement>) => {
    if (!doc) return;
    if (ev.button !== 0 && ev.pointerType === 'mouse') return;
    const pt = toSvg(ev);
    if (mode === 'pen') {
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      drag.current = { kind: 'pen' };
      setMarks((m) => [...m, { color: PEN_COLOR, width: Math.max(6, 3 / scale), points: [pt] }]);
      return;
    }
    const target = ev.target as Element;
    const handle = target.closest('[data-handle]')?.getAttribute('data-handle');
    const sel = selected ? doc.parts.find((p) => p.id === selected) : undefined;
    if (handle && sel) {
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      const b = boxOf(sel);
      const center = partCenter(sel, boxes[sel.id]);
      if (handle === 'rotate') {
        drag.current = { kind: 'rotate', id: sel.id, center, startAngle: Math.atan2(pt[1] - center[1], pt[0] - center[0]), orig: clone(sel), before: clone(doc) };
      } else {
        // つかんだ角の向かいの角を止めて、大きさを変える（回してある時は回した角）
        const corners: Record<string, [number, number]> = { nw: [b.x + b.w, b.y + b.h], ne: [b.x, b.y + b.h], sw: [b.x + b.w, b.y], se: [b.x, b.y] };
        const anchorLocal = corners[handle] || [b.x, b.y];
        const anchor = sel.rotation ? rotatePoint(anchorLocal, center, sel.rotation) : anchorLocal;
        drag.current = { kind: 'scale', id: sel.id, anchor, startDist: Math.hypot(pt[0] - anchor[0], pt[1] - anchor[1]) || 1, orig: clone(sel), before: clone(doc) };
      }
      return;
    }
    const id = target.closest('[data-part-id]')?.getAttribute('data-part-id');
    const part = id ? doc.parts.find((p) => p.id === id) : undefined;
    if (part && !part.locked) {
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      setSelected(part.id);
      drag.current = { kind: 'move', id: part.id, start: pt, orig: clone(part), before: clone(doc) };
    } else {
      setSelected(null);
    }
  };

  const onPointerMove = (ev: React.PointerEvent<SVGSVGElement>) => {
    const dr = drag.current;
    if (!dr || !docRef.current) return;
    const pt = toSvg(ev);
    if (dr.kind === 'pen') {
      setMarks((ms) => {
        if (!ms.length) return ms;
        const last = ms[ms.length - 1];
        const lp = last.points[last.points.length - 1];
        if (lp && Math.hypot(lp[0] - pt[0], lp[1] - pt[1]) < 2 / scale) return ms;
        return [...ms.slice(0, -1), { ...last, points: [...last.points, pt] }];
      });
      return;
    }
    const d = docRef.current;
    let np: ThumbPart;
    if (dr.kind === 'move') {
      const dx = pt[0] - dr.start[0], dy = pt[1] - dr.start[1];
      np = { ...dr.orig, x: dr.orig.x + dx, y: dr.orig.y + dy } as ThumbPart;
    } else if (dr.kind === 'scale') {
      const k = Math.max(0.05, Math.hypot(pt[0] - dr.anchor[0], pt[1] - dr.anchor[1]) / dr.startDist);
      np = scalePart(dr.orig, dr.anchor, k);
    } else {
      const a = Math.atan2(pt[1] - dr.center[1], pt[0] - dr.center[0]);
      let deg = (dr.orig.rotation || 0) + ((a - dr.startAngle) * 180) / Math.PI;
      deg = Math.round(deg * 10) / 10;
      if (!ev.shiftKey) for (const snap of [-180, -90, 0, 90, 180]) if (Math.abs(deg - snap) < 3) deg = snap;
      np = { ...dr.orig, rotation: deg };
    }
    const next = { ...d, parts: d.parts.map((p) => (p.id === np.id ? np : p)) };
    docRef.current = next;
    setDoc(next);
  };

  const onPointerUp = () => {
    const dr = drag.current;
    drag.current = null;
    if (!dr || dr.kind === 'pen' || !docRef.current) return;
    const now = docRef.current.parts.find((p) => p.id === dr.id);
    if (now && JSON.stringify(now) !== JSON.stringify(dr.orig)) commit(docRef.current, dr.before);
  };

  // ── キー ──
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const el = ev.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
      const mod = ev.ctrlKey || ev.metaKey;
      if (mod && ev.key.toLowerCase() === 'z') { ev.preventDefault(); if (ev.shiftKey) redo(); else undo(); return; }
      if (mod && ev.key.toLowerCase() === 'y') { ev.preventDefault(); redo(); return; }
      const d = docRef.current;
      const sel = selected && d ? d.parts.find((p) => p.id === selected) : undefined;
      if (!sel || !d) return;
      if (mod && ev.key.toLowerCase() === 'd') { ev.preventDefault(); duplicate(sel); return; }
      if (ev.key === 'Delete' || ev.key === 'Backspace') { ev.preventDefault(); remove(sel.id); return; }
      if (ev.key === 'Escape') { setSelected(null); return; }
      const step = ev.shiftKey ? 10 : 1;
      const mv: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (mv[ev.key]) {
        ev.preventDefault();
        updatePart(sel.id, (p) => ({ ...p, x: p.x + mv[ev.key][0], y: p.y + mv[ev.key][1] } as ThumbPart));
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const remove = (id: string) => {
    const d = docRef.current;
    if (!d) return;
    commit({ ...d, parts: d.parts.filter((p) => p.id !== id) });
    setSelected(null);
  };
  const duplicate = (p: ThumbPart) => {
    const d = docRef.current;
    if (!d) return;
    const copy = { ...clone(p), id: newPartId(p.type === 'text' ? 't' : 'i'), name: p.name ? `${p.name}（写し）` : undefined, x: p.x + 30, y: p.y + 30, locked: false } as ThumbPart;
    const i = d.parts.findIndex((q) => q.id === p.id);
    const parts = [...d.parts];
    parts.splice(i + 1, 0, copy);
    commit({ ...d, parts });
    setSelected(copy.id);
  };
  const move = (id: string, dir: 'up' | 'down' | 'front' | 'back') => {
    const d = docRef.current;
    if (!d) return;
    const parts = [...d.parts];
    const i = parts.findIndex((p) => p.id === id);
    if (i < 0) return;
    const [p] = parts.splice(i, 1);
    const j = dir === 'front' ? parts.length : dir === 'back' ? 0 : dir === 'up' ? Math.min(parts.length, i + 1) : Math.max(0, i - 1);
    parts.splice(j, 0, p);
    commit({ ...d, parts });
  };
  const addText = () => {
    const d = docRef.current;
    if (!d) return;
    const p: ThumbTextPart = {
      id: newPartId('t'), type: 'text', text: '文字', x: d.width * 0.38, y: d.height * 0.55, font: 'hiragino-w9', size: 180,
      fill: '#ffffff', stroke: '#000000', stroke_width: 18, letter_spacing: -4, shadow: { blur: 12, opacity: 0.75 },
    };
    commit({ ...d, parts: [...d.parts, p] });
    setSelected(p.id);
    setMode('select');
    window.setTimeout(() => { textRef.current?.focus(); textRef.current?.select(); }, 50);
  };

  // ── 書き込んで送る ──
  const sendMarks = async () => {
    const d = docRef.current;
    if (!d || (!marks.length && !note.trim())) return;
    setSending(true);
    try {
      const xs = marks.flatMap((m) => m.points.map((p) => p[0]));
      const ys = marks.flatMap((m) => m.points.map((p) => p[1]));
      const pad = 12;
      const box = xs.length ? [Math.max(0, Math.min(...xs) - pad), Math.max(0, Math.min(...ys) - pad), 0, 0] : [];
      if (xs.length) { box[2] = Math.min(d.width, Math.max(...xs) + pad) - box[0]; box[3] = Math.min(d.height, Math.max(...ys) + pad) - box[1]; }
      const hit = (b: PartBox) => box.length === 4 && b.x < box[0] + box[2] && b.x + b.w > box[0] && b.y < box[1] + box[3] && b.y + b.h > box[1];
      const under = [...d.parts].reverse().filter((p) => !p.hidden && hit(boxOf(p))).map((p) => `${p.id}（${partLabel(p)}）`);
      const id = `ti_${Date.now().toString(36)}`;
      const selPart = selected ? d.parts.find((p) => p.id === selected) : undefined;
      const res = await fetch(`/api/v1/production-assets/contents/${encodeURIComponent(contentId)}/instructions`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room_id: roomId,
          annotation: {
            id, kind: 'thumb_marks', note: note.trim(),
            data: { marks, box, parts_under: under, selected: selPart ? `${selPart.id}（${partLabel(selPart)}）` : null, job_id: resendOf?.job_id },
          },
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const j = (await res.json()) as { job_id: string };
      const instr: ThumbInstruction = { id, note: note.trim(), marks, job_id: j.job_id, created_at: new Date().toISOString() };
      const cur = docRef.current || d;
      const list = (cur.instructions || []).filter((x) => x.id !== resendOf?.id);
      commit({ ...cur, instructions: [...list, instr] });
      setJobs((s) => ({ ...s, [j.job_id]: { job_id: j.job_id, state: 'queued', label: '順番待ち', active: true } }));
      setMarks([]); setNote(''); setResendOf(null); setMode('select');
    } catch (e) {
      toast.error('ダンに送れませんでした', { description: String(e).slice(0, 160) });
    } finally {
      setSending(false);
    }
  };

  // ── 仕上げ（荒く並べた絵を、構図のまま光と影を整えた1枚に。前後を見比べて採用する） ──
  const finishUrl = (extra = '') => api(`${encodeURIComponent(contentId)}/thumbnail/finish${extra}`, roomId);
  // 開いた時と、その後も5秒ごと: ほかの所（ダンへの頼み・別の端末）で始まった仕上げも拾う。
  // 仕上げ中なら続きを待ち、仕上がったのにまだ選んでいなければ見比べを出す
  const seenFinish = useRef<Set<string>>(new Set());
  useEffect(() => {
    let stop = false;
    const look = async () => {
      try {
        const res = await fetch(finishUrl(), { credentials: 'include', cache: 'no-store' });
        if (!res.ok || stop) return;
        const j = (await res.json()) as { job: ThumbFinishJob | null };
        const job = j.job;
        if (!job || stop || job.decided || seenFinish.current.has(`${job.job_id}:${job.state}`)) return;
        seenFinish.current.add(`${job.job_id}:${job.state}`);
        if (job.state === 'running') setFinishJob((cur) => (cur?.job_id === job.job_id ? cur : job));
        if (job.state === 'done') { setFinishJob(job); setCompareOpen(true); }
      } catch { /* 次に */ }
    };
    void look();
    const t = window.setInterval(() => void look(), 5000);
    return () => { stop = true; window.clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, contentId]);

  const finishRunning = finishJob?.state === 'running';
  useEffect(() => {
    if (!finishRunning || !finishJob) return;
    let stop = false;
    const t = window.setInterval(async () => {
      try {
        const res = await fetch(finishUrl(`?job_id=${encodeURIComponent(finishJob.job_id)}`), { credentials: 'include', cache: 'no-store' });
        if (!res.ok || stop) return;
        const j = (await res.json()) as { job: ThumbFinishJob | null };
        if (!j.job || stop) return;
        setFinishJob(j.job);
        seenFinish.current.add(`${j.job.job_id}:${j.job.state}`);
        if (j.job.state === 'done') setCompareOpen(true);
      } catch { /* 次に */ }
    }, 2000);
    return () => { stop = true; window.clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finishRunning, finishJob?.job_id]);

  const startFinish = async (note = '') => {
    if (finishRunning) return;
    setCompareOpen(false);
    try {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      await flush();
      const res = await fetch(finishUrl(), {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }),
      });
      if (!res.ok) {
        let msg = await res.text();
        try { msg = (JSON.parse(msg) as { detail?: string }).detail || msg; } catch { /* そのまま */ }
        throw new Error(msg);
      }
      const job = (await res.json()) as ThumbFinishJob;
      seenFinish.current.add(`${job.job_id}:${job.state}`);
      setFinishJob(job);
    } catch (e) {
      toast.error('仕上げを始められませんでした', { description: String((e as Error).message || e).slice(0, 160) });
    }
  };

  const decideFinish = async (adopted: boolean) => {
    const job = finishJob;
    const d = docRef.current;
    if (!job) return;
    if (adopted && d) {
      const next = applyFinish(d, job);
      commit(next);
      setSelected(null);
    }
    setCompareOpen(false);
    setFinishJob(null);
    try {
      await fetch(finishUrl(`/${encodeURIComponent(job.job_id)}/decide`), {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ adopted }),
      });
    } catch { /* 選んだ記録だけなので、届かなくても画面はそのまま */ }
  };

  const unfinish = () => {
    const d = docRef.current;
    if (!d) return;
    commit(removeFinish(d));
    setSelected(null);
  };

  const instructions = doc?.instructions || [];
  const activeIds = instructions.map((i) => i.job_id).filter((x): x is string => !!x);
  const activeKey = activeIds.join(',');
  useEffect(() => {
    if (!activeKey) return;
    let stop = false;
    const tick = async () => {
      try {
        const res = await fetch(`/api/v1/production-assets/instructions/status?job_ids=${encodeURIComponent(activeKey)}`, { credentials: 'include', cache: 'no-store' });
        if (!res.ok) return;
        const j = (await res.json()) as { jobs: JobState[] };
        if (!stop) setJobs(Object.fromEntries(j.jobs.map((x) => [x.job_id, x])));
      } catch { /* 次に */ }
    };
    void tick();
    const t = window.setInterval(() => void tick(), 3000);
    return () => { stop = true; window.clearInterval(t); };
  }, [activeKey]);

  const removeInstruction = (id: string) => {
    const d = docRef.current;
    if (!d) return;
    commit({ ...d, instructions: (d.instructions || []).filter((x) => x.id !== id) });
    if (showInstr === id) setShowInstr(null);
  };

  const exportPng = async () => {
    setExporting(true);
    try {
      await flush();
      const res = await fetch(api(`${encodeURIComponent(contentId)}/thumbnail/export`, roomId), { method: 'POST', credentials: 'include' });
      if (!res.ok) throw new Error(await res.text());
      const file = await fetch(api(`${encodeURIComponent(contentId)}/thumbnail/export.png`, roomId), { credentials: 'include', cache: 'no-store' });
      const blob = await file.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${title || 'thumbnail'}.png`; a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      toast.error('書き出せませんでした', { description: String(e).slice(0, 160) });
    } finally {
      setExporting(false);
    }
  };

  const sel = doc && selected ? doc.parts.find((p) => p.id === selected) : undefined;
  const shownMarks = mode === 'pen' ? marks : showInstr ? instructions.find((i) => i.id === showInstr)?.marks : undefined;

  // ── 選んだ部品の枠と角 ──
  const handleR = (compact ? 13 : 7) / scale;
  const overlay = sel && mode === 'select' && !sel.hidden ? (() => {
    const b = boxOf(sel);
    const [cx, cy] = partCenter(sel, boxes[sel.id]);
    const sw = 1.5 / scale;
    return (
      <g transform={sel.rotation ? `rotate(${sel.rotation} ${cx} ${cy})` : undefined}>
        <rect x={b.x} y={b.y} width={b.w} height={b.h} fill="none" stroke="#38bdf8" strokeWidth={sw * 1.5} strokeDasharray={`${6 / scale} ${4 / scale}`} pointerEvents="none" />
        {!sel.locked ? (
          <>
            <line x1={b.x + b.w / 2} y1={b.y} x2={b.x + b.w / 2} y2={b.y - 28 / scale} stroke="#38bdf8" strokeWidth={sw} pointerEvents="none" />
            <circle data-handle="rotate" cx={b.x + b.w / 2} cy={b.y - 28 / scale} r={handleR} fill="#fff" stroke="#38bdf8" strokeWidth={sw} style={{ cursor: 'grab' }} />
            {([['nw', b.x, b.y], ['ne', b.x + b.w, b.y], ['sw', b.x, b.y + b.h], ['se', b.x + b.w, b.y + b.h]] as const).map(([k, x, y]) => (
              <rect key={k} data-handle={k} x={x - handleR} y={y - handleR} width={handleR * 2} height={handleR * 2} fill="#fff" stroke="#38bdf8" strokeWidth={sw}
                style={{ cursor: k === 'nw' || k === 'se' ? 'nwse-resize' : 'nesw-resize' }} />
            ))}
          </>
        ) : null}
      </g>
    );
  })() : null;

  const partProps = useCallback((p: ThumbPart) => ({
    style: { cursor: mode === 'pen' ? 'crosshair' : p.locked ? 'default' : 'move', pointerEvents: mode === 'pen' || p.locked ? 'none' : 'auto' },
  }), [mode]);

  if (!doc) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />サムネを開いています…
      </div>
    );
  }

  const toolBtn = (active: boolean) =>
    `flex items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium ${compact ? 'h-9' : 'h-8'} ${active ? 'border-sky-500 bg-sky-500/15 text-sky-600 dark:text-sky-300' : 'border-border bg-background hover:bg-muted'}`;

  const tools = (
    <div className="flex flex-wrap items-center gap-1.5" data-thumb-tools>
      <button type="button" className={toolBtn(mode === 'select')} onClick={() => { setMode('select'); setMarks([]); setResendOf(null); }} title="部品を選んで動かす">
        <MousePointer2 className="h-3.5 w-3.5" />選ぶ
      </button>
      <button type="button" className={toolBtn(mode === 'pen')} onClick={() => { setMode('pen'); setSelected(null); }} title="ペンで書き込んでダンに直してもらう" data-thumb-pen>
        <PenLine className="h-3.5 w-3.5" />書き込む
      </button>
      <button type="button" className={toolBtn(false)} onClick={addText} title="文字を足す"><Type className="h-3.5 w-3.5" />文字</button>
      <button type="button" className={toolBtn(finishRunning)} onClick={() => void startFinish()} disabled={finishRunning}
        title="文字より奥の絵（背景・人物）を、並べた形のまま光と影を整えた1枚にする" data-thumb-finish>
        {finishRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}{finishRunning ? '仕上げ中' : '仕上げ'}
      </button>
      <button type="button" className={toolBtn(listView)} onClick={() => setListView((v) => !v)} title="YouTube の一覧の大きさで見る" data-thumb-list>
        <LayoutGrid className="h-3.5 w-3.5" />{compact ? '一覧' : '一覧で見る'}
      </button>
      <span className="mx-1 h-5 w-px bg-border" />
      <button type="button" className={toolBtn(false)} onClick={undo} disabled={!undoStack.current.length} title="元に戻す（Ctrl+Z）"><Undo2 className="h-3.5 w-3.5" /></button>
      <button type="button" className={toolBtn(false)} onClick={redo} disabled={!redoStack.current.length} title="やり直す（Ctrl+Shift+Z）"><Redo2 className="h-3.5 w-3.5" /></button>
      <button type="button" className={toolBtn(false)} onClick={() => void exportPng()} disabled={exporting} title="1280×720 の PNG に書き出す">
        {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}{compact ? null : '書き出す'}
      </button>
    </div>
  );

  // 選んだ部品の欄
  const field = 'h-8 w-full rounded border border-border bg-background px-2 text-sm';
  const label = 'mb-1 block text-[11px] font-medium text-muted-foreground';
  const props = sel ? (
    <div className="space-y-3" data-thumb-props>
      <div className="flex items-center gap-1">
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{partLabel(sel)}</span>
        <button type="button" title="前へ" className="rounded p-1 hover:bg-muted" onClick={() => move(sel.id, 'up')}><ArrowUp className="h-4 w-4" /></button>
        <button type="button" title="後ろへ" className="rounded p-1 hover:bg-muted" onClick={() => move(sel.id, 'down')}><ArrowDown className="h-4 w-4" /></button>
        <button type="button" title="複製（Ctrl+D）" className="rounded p-1 hover:bg-muted" onClick={() => duplicate(sel)}><Copy className="h-4 w-4" /></button>
        <button type="button" title="消す（Delete）" className="rounded p-1 hover:bg-muted hover:text-destructive" onClick={() => remove(sel.id)}><Trash2 className="h-4 w-4" /></button>
      </div>
      {sel.type === 'text' ? (
        <>
          <div>
            <span className={label}>文字</span>
            <textarea
              ref={textRef}
              value={sel.text}
              rows={Math.min(4, sel.text.split('\n').length + 1)}
              onChange={(e) => {
                const d = docRef.current;
                if (!d) return;
                // 打っている間は1文字ずつ元に戻すに積まない（打ち始めの形だけ積む）
                const next = { ...d, parts: d.parts.map((p) => (p.id === sel.id ? { ...p, text: e.target.value } as ThumbPart : p)) };
                if (!(textRef.current as unknown as { __editing?: boolean })?.__editing) {
                  (textRef.current as unknown as { __editing?: boolean }).__editing = true;
                  commit(next);
                } else { setDoc(next); docRef.current = next; scheduleSave(); }
              }}
              onBlur={() => { if (textRef.current) (textRef.current as unknown as { __editing?: boolean }).__editing = false; }}
              className="w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
              data-thumb-text
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label><span className={label}>大きさ</span>
              <input type="number" className={field} value={Math.round(sel.size)} onChange={(e) => {
                const v = Number(e.target.value); if (v > 3) updatePart(sel.id, (p) => scalePart(p, [p.x, p.y], v / (p as ThumbTextPart).size));
              }} data-thumb-size />
            </label>
            <label><span className={label}>書体</span>
              <select className={field} value={sel.font} onChange={(e) => updatePart(sel.id, { font: e.target.value as ThumbFontId })}>
                {Object.entries(THUMB_FONTS).map(([k, f]) => <option key={k} value={k}>{f.label}</option>)}
              </select>
            </label>
            <label><span className={label}>文字の色</span>
              <input type="color" className="h-8 w-full rounded border border-border" value={sel.fill.slice(0, 7)} onChange={(e) => updatePart(sel.id, { fill: e.target.value })} data-thumb-fill />
            </label>
            <label><span className={label}>縁の色</span>
              <input type="color" className="h-8 w-full rounded border border-border" value={(sel.stroke || '#000000').slice(0, 7)} onChange={(e) => updatePart(sel.id, { stroke: e.target.value })} />
            </label>
            <label><span className={label}>縁の太さ</span>
              <input type="number" className={field} value={Math.round(sel.stroke_width || 0)} min={0} onChange={(e) => updatePart(sel.id, { stroke_width: Math.max(0, Number(e.target.value)) })} />
            </label>
            <label><span className={label}>字の間</span>
              <input type="number" className={field} value={Math.round(sel.letter_spacing || 0)} onChange={(e) => updatePart(sel.id, { letter_spacing: Number(e.target.value) })} />
            </label>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {['#ffffff', '#ffe400', '#ff2a2a', '#b05cff', '#00d0ff', '#111111'].map((c) => (
              <button key={c} type="button" title={c} onClick={() => updatePart(sel.id, { fill: c })} className="h-6 w-6 rounded-full border border-border" style={{ background: c }} />
            ))}
            <button type="button" className="ml-auto rounded border border-border px-2 text-[11px] hover:bg-muted" onClick={() => updatePart(sel.id, { shadow: sel.shadow ? null : { blur: 12, opacity: 0.75 } })}>
              影 {sel.shadow ? 'あり' : 'なし'}
            </button>
          </div>
        </>
      ) : sel.finish ? (
        <div className="space-y-2" data-thumb-finish-part>
          <button type="button" className="h-8 w-full rounded border border-border text-xs hover:bg-muted" onClick={unfinish} data-thumb-unfinish>
            仕上げを外して、元の絵に戻す
          </button>
          <button type="button" className="h-8 w-full rounded border border-border text-xs hover:bg-muted disabled:opacity-40" disabled={finishRunning} onClick={() => void startFinish()}>
            <Sparkles className="mr-1 inline h-3 w-3" />もう一度仕上げる
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <label className="col-span-2"><span className={label}>不透明度</span>
            <input type="range" min={0} max={1} step={0.01} value={sel.opacity ?? 1} onChange={(e) => updatePart(sel.id, { opacity: Number(e.target.value) })} className="w-full" />
          </label>
          <button type="button" className="h-8 rounded border border-border text-xs hover:bg-muted" onClick={() => updatePart(sel.id, (p) => ({ ...p, flip_x: !(p as { flip_x?: boolean }).flip_x } as ThumbPart))}>左右に反転</button>
          <button type="button" className="h-8 rounded border border-border text-xs hover:bg-muted" onClick={() => updatePart(sel.id, { rotation: 0 })}><RotateCcw className="mr-1 inline h-3 w-3" />回転を0に</button>
        </div>
      )}
    </div>
  ) : null;

  const layers = (
    <div data-thumb-layers>
      <div className="mb-1 text-[11px] font-semibold text-muted-foreground">部品（上が手前）</div>
      <ul className="space-y-0.5">
        {[...doc.parts].reverse().map((p) => (
          <li key={p.id} className={`group flex items-center gap-1 rounded px-1.5 py-1 text-xs ${p.id === selected ? 'bg-sky-500/15' : 'hover:bg-muted'}`}>
            <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => { setSelected(p.id); setMode('select'); }}>
              {p.type === 'text' ? <Type className="mr-1 inline h-3 w-3" /> : null}{partLabel(p)}
            </button>
            <button type="button" title={p.hidden ? '出す' : '隠す'} className="rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => updatePart(p.id, { hidden: !p.hidden })}>
              {p.hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
            <button type="button" title={p.locked ? '動かせるようにする' : '動かないようにする'} className="rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => updatePart(p.id, { locked: !p.locked })}>
              {p.locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5 opacity-40" />}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );

  const instrList = instructions.length ? (
    <div data-thumb-instructions>
      <div className="mb-1 text-[11px] font-semibold text-muted-foreground">ダンへの書き込み</div>
      <ul className="space-y-1.5">
        {[...instructions].reverse().map((ins) => {
          const st = ins.job_id ? jobs[ins.job_id] : undefined;
          const active = st ? st.active : true;
          return (
            <li key={ins.id} className={`rounded border p-2 text-xs ${showInstr === ins.id ? 'border-red-400' : 'border-border'}`}
              onMouseEnter={() => setShowInstr(ins.id)} onMouseLeave={() => setShowInstr(null)}>
              <div className="flex items-start gap-1.5">
                {active ? <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-sky-500" /> : <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />}
                <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setShowInstr((v) => (v === ins.id ? null : ins.id))}>
                  <div className="font-medium">{ins.note || '（書き込みだけ）'}</div>
                  <div className="mt-0.5 text-muted-foreground">{st ? (st.active ? (st.progress || st.label) : (st.result || st.label)) : '順番待ち'}</div>
                </button>
                <button type="button" title="消す" className="rounded p-0.5 text-muted-foreground hover:text-destructive" onClick={() => removeInstruction(ins.id)}><X className="h-3.5 w-3.5" /></button>
              </div>
              {!active ? (
                <button type="button" className="mt-1.5 text-[11px] text-sky-600 hover:underline dark:text-sky-300"
                  onClick={() => { setResendOf(ins); setMarks(ins.marks); setNote(ins.note); setMode('pen'); setSelected(null); }}>
                  書き直して、もう一度送る
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  ) : null;

  const finishCard = finishJob && (finishJob.state === 'running' || finishJob.state === 'error') ? (
    <div className={`rounded-md border p-2 text-xs ${finishJob.state === 'error' ? 'border-red-300 bg-red-50/60 dark:bg-red-950/30' : 'border-sky-300 bg-sky-50/60 dark:bg-sky-950/30'}`} data-thumb-finish-status>
      {finishJob.state === 'running' ? (
        <div className="flex items-start gap-1.5"><Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-sky-500" /><span>仕上げ中: {finishJob.step || '始めています'}</span></div>
      ) : (
        <div className="space-y-1.5">
          <div>{finishJob.message || '仕上げられませんでした'}</div>
          <div className="flex gap-1.5">
            <button type="button" className="rounded border border-border px-2 py-1 hover:bg-muted" onClick={() => void startFinish()}>もう一度</button>
            <button type="button" className="rounded border border-border px-2 py-1 hover:bg-muted" onClick={() => setFinishJob(null)}>閉じる</button>
          </div>
        </div>
      )}
    </div>
  ) : null;

  const comparePanel = compareOpen && finishJob?.state === 'done' && finishJob.src ? (
    <FinishCompare doc={doc} job={finishJob} compact={compact}
      onAdopt={() => void decideFinish(true)} onDiscard={() => void decideFinish(false)} onRetry={(note) => void startFinish(note)} />
  ) : null;

  const penBar = mode === 'pen' ? (
    <div className="rounded-md border border-red-300 bg-red-50/60 p-2 dark:bg-red-950/30" data-thumb-penbar>
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void sendMarks(); }}
        rows={2}
        placeholder="ダンへの一言"
        className="w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
        data-thumb-note
      />
      <div className="mt-1.5 flex gap-1.5">
        <button type="button" disabled={sending || (!marks.length && !note.trim())} onClick={() => void sendMarks()}
          className="flex h-8 flex-1 items-center justify-center gap-1 rounded-md bg-red-600 text-xs font-semibold text-white disabled:opacity-40" data-thumb-send>
          {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}送る
        </button>
        <button type="button" onClick={() => setMarks((m) => m.slice(0, -1))} disabled={!marks.length} className="h-8 rounded-md border border-border px-2 text-xs disabled:opacity-40">1本消す</button>
        <button type="button" onClick={() => { setMarks([]); setNote(''); setResendOf(null); setMode('select'); }} className="h-8 rounded-md border border-border px-2 text-xs">やめる</button>
      </div>
    </div>
  ) : null;

  const stage = (
    <div ref={stageWrap} className={`relative flex min-h-0 min-w-0 items-center justify-center ${compact ? 'w-full' : 'h-full w-full'}`}>
      <div style={{ width: stageW }} className="relative shadow-lg" data-thumb-stage>
        <ThumbCanvas
          ref={svgRef}
          doc={doc}
          width={stageW}
          boxes={boxes}
          marks={shownMarks}
          onMeasure={(id, box) => setBoxes((b) => (b[id] && Math.abs(b[id].x - box.x) < 0.5 && Math.abs(b[id].y - box.y) < 0.5 && Math.abs(b[id].w - box.w) < 0.5 && Math.abs(b[id].h - box.h) < 0.5 ? b : { ...b, [id]: box }))}
          partProps={partProps}
          overlay={overlay}
          style={{ touchAction: 'none', cursor: mode === 'pen' ? 'crosshair' : undefined }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        />
      </div>
    </div>
  );

  const listPanel = listView ? <ThumbListView doc={doc} title={title} onClose={() => setListView(false)} compact={compact} /> : null;

  const savingText = saving === 'saving' ? '保存中…' : saving === 'error' ? '保存できていません' : '';

  if (compact) {
    return (
      <div className="relative flex h-full min-h-0 flex-col bg-background" data-thumb-editor="phone">
        <div className="flex shrink-0 items-center gap-2 px-2 py-1.5">
          <button type="button" onClick={onBack} className="rounded p-1.5 hover:bg-muted" title="戻る"><ArrowLeft className="h-5 w-5" /></button>
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</span>
          <span className="text-[11px] text-muted-foreground">{savingText}</span>
        </div>
        <div className="shrink-0">{stage}</div>
        {phoneChatOpen && phoneChat ? (
          <div className="min-h-0 flex-1 border-t border-border">
            {phoneChat(<button type="button" onClick={() => setPhoneChatOpen(false)} className="rounded p-1 hover:bg-muted" title="サムネの道具に戻る"><X className="h-4 w-4" /></button>)}
          </div>
        ) : (
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overflow-x-hidden p-3">
            {tools}
            {finishCard}
            {penBar}
            {mode === 'select' ? props : null}
            {instrList}
            {layers}
          </div>
        )}
        {!phoneChatOpen && phoneChat ? (
          <button type="button" onClick={() => setPhoneChatOpen(true)} title="ダンと話す"
            className="absolute bottom-4 right-4 flex h-12 w-12 items-center justify-center rounded-full bg-sky-600 text-white shadow-lg" data-thumb-chat>
            <MessageSquare className="h-5 w-5" />
          </button>
        ) : null}
        {listPanel}
        {comparePanel}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background" data-thumb-editor="pc">
      <header className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <button type="button" onClick={onBack} className="rounded p-1.5 hover:bg-muted" title="ライブラリへ戻る"><ArrowLeft className="h-4 w-4" /></button>
        <h1 className="min-w-0 max-w-[30%] truncate text-sm font-semibold">{title}</h1>
        <div className="ml-2 min-w-0 flex-1">{tools}</div>
        <span className="text-[11px] text-muted-foreground">{savingText}</span>
      </header>
      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 min-w-0 flex-1 bg-muted/40 p-6">{stage}</div>
        <aside className="w-72 shrink-0 space-y-4 overflow-y-auto border-l border-border p-3">
          {finishCard}
          {penBar}
          {mode === 'select' ? props : null}
          {instrList}
          {layers}
        </aside>
      </div>
      {listPanel}
      {comparePanel}
    </div>
  );
}

// 仕上げの前後を見比べて、採用する・やめる・一言を添えてもう一度を選ぶ（文字は前後とも同じ部品を重ねて見せる）
function FinishCompare({ doc, job, compact, onAdopt, onDiscard, onRetry }: {
  doc: ThumbDoc; job: ThumbFinishJob; compact: boolean; onAdopt: () => void; onDiscard: () => void; onRetry: (note: string) => void;
}) {
  const after = useMemo(() => applyFinish(doc, job), [doc, job]);
  const [note, setNote] = useState('');
  const [retrying, setRetrying] = useState(false);
  const fin = finishPart(doc);
  // 前: 今の形（もう仕上げてあれば、その仕上げの前の元の絵）
  const before = useMemo(() => (fin ? removeFinish(doc) : doc), [doc, fin]);
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0b0b0b] text-white" data-thumb-compare>
      <div className="flex shrink-0 items-center gap-2 px-4 py-3">
        <Sparkles className="h-4 w-4 text-sky-300" />
        <span className="flex-1 text-sm font-semibold">仕上げの前と後</span>
        <button type="button" onClick={onDiscard} className="rounded-full p-2 hover:bg-white/10" title="やめる"><X className="h-5 w-5" /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4">
        {compact ? (
          // スマホ: 前と後を上下に、どちらも画面の幅いっぱいで
          <div className="space-y-3">
            <div><div className="mb-1 text-xs text-white/70">前</div><div className="overflow-hidden rounded-lg" data-thumb-compare-before><ThumbCanvas doc={before} width="100%" /></div></div>
            <div><div className="mb-1 text-xs text-white/70">仕上げた後</div><div className="overflow-hidden rounded-lg ring-2 ring-sky-400" data-thumb-compare-after><ThumbCanvas doc={after} width="100%" /></div></div>
          </div>
        ) : (
          <div className="mx-auto grid max-w-[1600px] grid-cols-2 gap-4">
            <div><div className="mb-1.5 text-xs text-white/70">前</div><div className="overflow-hidden rounded-lg" data-thumb-compare-before><ThumbCanvas doc={before} width="100%" /></div></div>
            <div><div className="mb-1.5 text-xs text-white/70">仕上げた後</div><div className="overflow-hidden rounded-lg ring-2 ring-sky-400" data-thumb-compare-after><ThumbCanvas doc={after} width="100%" /></div></div>
          </div>
        )}
      </div>
      <div className="shrink-0 space-y-2 px-4 pb-4 pt-3">
        {retrying ? (
          <div className="mx-auto flex max-w-xl gap-2">
            <input value={note} onChange={(e) => setNote(e.target.value)} autoFocus placeholder="どう変えたいか（例: もっと明るく・影を弱く）"
              onKeyDown={(e) => { if (e.key === 'Enter') onRetry(note.trim()); }}
              className="h-10 min-w-0 flex-1 rounded-md border border-white/20 bg-white/10 px-3 text-sm text-white placeholder:text-white/40" data-thumb-compare-note />
            <button type="button" onClick={() => onRetry(note.trim())} className="h-10 rounded-md bg-sky-500 px-4 text-sm font-semibold">送る</button>
          </div>
        ) : null}
        <div className="mx-auto flex max-w-xl gap-2">
          <button type="button" onClick={onAdopt} className="flex h-11 flex-1 items-center justify-center gap-1.5 rounded-md bg-sky-500 text-sm font-semibold" data-thumb-adopt>
            <Check className="h-4 w-4" />採用する
          </button>
          <button type="button" onClick={() => setRetrying((v) => !v)} className="h-11 rounded-md border border-white/25 px-3 text-sm hover:bg-white/10" data-thumb-retry>もう一度</button>
          <button type="button" onClick={onDiscard} className="h-11 rounded-md border border-white/25 px-3 text-sm hover:bg-white/10" data-thumb-discard>やめる</button>
        </div>
      </div>
    </div>
  );
}

// YouTube の一覧と同じ大きさで並べて見る（PC のホームは幅360前後、横の「次の動画」は幅168、スマホの一覧は画面の幅）
function ThumbListView({ doc, title, onClose, compact }: { doc: ThumbDoc; title: string; onClose: () => void; compact: boolean }) {
  const refs = doc.references || [];
  const name = doc.title || title;
  const cards = useMemo(() => {
    const own = { own: true as const };
    const others = refs.map((r) => ({ own: false as const, ...r }));
    const out: Array<typeof own | (typeof others)[number]> = [...others];
    out.splice(Math.min(1, out.length), 0, own);
    return out;
  }, [refs]);
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-[#0f0f0f] p-4 text-white" data-thumb-listview>
      <div className="mb-4 flex items-center gap-2">
        <span className="flex-1 text-sm font-semibold">YouTube の一覧の大きさ</span>
        <button type="button" onClick={onClose} className="rounded-full p-2 hover:bg-white/10" title="閉じる"><X className="h-5 w-5" /></button>
      </div>
      <div className={`grid gap-x-4 gap-y-8 ${compact ? 'grid-cols-1' : 'grid-cols-[repeat(auto-fill,360px)]'}`}>
        {cards.map((c, i) => (
          <div key={i} className={compact ? 'w-full' : 'w-[360px]'}>
            <div className={`overflow-hidden rounded-xl ${c.own ? 'ring-2 ring-sky-400' : ''}`}>
              {c.own ? <ThumbCanvas doc={doc} width="100%" /> : <img src={c.src} alt="" className="aspect-video w-full object-cover" />}
            </div>
            <div className="mt-3 line-clamp-2 text-[15px] font-medium leading-snug">{c.own ? name : (c.title || '')}</div>
            <div className="mt-1 text-[13px] text-[#aaa]">{c.own ? 'このサムネ' : (c.channel || '')}</div>
          </div>
        ))}
      </div>
      {!compact ? (
        <>
          <div className="mb-3 mt-10 text-sm font-semibold">横の「次の動画」の大きさ</div>
          <div className="space-y-2">
            {cards.map((c, i) => (
              <div key={i} className="flex w-[402px] gap-2">
                <div className={`w-[168px] shrink-0 overflow-hidden rounded-lg ${c.own ? 'ring-2 ring-sky-400' : ''}`}>
                  {c.own ? <ThumbCanvas doc={doc} width="100%" /> : <img src={c.src} alt="" className="aspect-video w-full object-cover" />}
                </div>
                <div className="min-w-0 text-[14px] font-medium leading-snug"><span className="line-clamp-2">{c.own ? name : (c.title || '')}</span></div>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
