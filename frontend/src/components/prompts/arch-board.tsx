'use client';

// 構成図のボード（2026-11-24 本人「表示領域を最大限でかく」「フリーボードに」「ホイールは寄る・引く」「どこまでも寄れる」
// 「要素や札のサイズ・位置、線の伸び方も調整したい」「線を裏側に通して見えなくするのはダメ」）。
// - 画面いっぱいの枠の中で、図そのものを動かす（上下左右に端は無い）。ホイール＝寄る・引く、押したまま動かす＝移動。
//   スマホは指1本で移動、2本でつまんで寄る・引く。
// - 箱・枠は押したまま動かすと位置が、右下の角を引くと大きさが変わる。線はどこでも押したまま動かすと、そこを通る点ができる
//   （点を2回押すと消える）。並べ方は /api/v1/prompts/board-layout に保存し、PC とスマホで同じ物を見る。
// - 線は箱より手前に描く（箱の裏を通って見えなくならない）。決まった並べ方と線の通り道は architecture.ts。
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { BookOpen, ChevronRight, Clapperboard, Maximize, Minus, Plus, RotateCcw } from 'lucide-react';

import { READER_EXAMPLES, readerGroups } from './reader-skills';
import { promptRequest, type PromptSummary } from '@/lib/prompts-api';
import { cn } from '@/lib/utils';
import { BOARD_EDGES, BOARD_NODES, BOX_H, VIDEO_FRAME, VIDEO_NODES, WORK_FRAME, type ArchEdge, type ArchNode } from './architecture';
import type { Trace } from './architecture-trace';
import type { PlanMark } from '@/lib/map-focus';

type Box = { x: number; y: number; w: number; h: number };
type Pt = [number, number];
type Side = 't' | 'b' | 'l' | 'r';
export type BoardLayout = { nodes: Record<string, Box>; frames: Record<string, Box>; edges: Record<string, Pt[]> };
const EMPTY: BoardLayout = { nodes: {}, frames: {}, edges: {} };
const STRIP = 84;            // 箱の下に付く「スキル」の札の高さ
const MIN_S = 0.04, MAX_S = 60;
const VIDEO_IDS = new Set(VIDEO_NODES.map(n => n.id));
const FRAMES: Record<string, Box & { name: string; line?: string }> = { work: WORK_FRAME, video: VIDEO_FRAME };
const BY_ID = new Map(BOARD_NODES.map(n => [n.id, n]));
const VIEW_KEY = 'dan-arch-board-view';
export const edgeKey = (e: Pick<ArchEdge, 'from' | 'to'>) => e.from + '/' + e.to;
const hasStrip = (id: string) => !VIDEO_IDS.has(id) && (id in READER_EXAMPLES || id === 'voice');

// ---- 線の形 ----
function anchor(b: Box, extra: number, side: Side, off?: number): Pt {
  const along = (len: number) => Math.min(len, Math.max(0, off ?? len / 2));
  if (side === 't') return [b.x + along(b.w), b.y];
  if (side === 'b') return [b.x + along(b.w), b.y + b.h + extra];
  if (side === 'l') return [b.x, b.y + along(b.h)];
  return [b.x + b.w, b.y + along(b.h)];
}
const horiz = (s: Side) => s === 'l' || s === 'r';

/** 通る点が無い線は、箱の辺から直角に曲がって結ぶ */
function autoVia(p: Pt, s1: Side, q: Pt, s2: Side): Pt[] {
  const G = 28;
  if (horiz(s1) && horiz(s2)) {
    if (Math.abs(p[1] - q[1]) < 0.5 && ((s1 === 'r' && q[0] > p[0]) || (s1 === 'l' && q[0] < p[0]))) return [];
    if (s1 === 'r' && s2 === 'l' && q[0] > p[0] + 8) { const m = (p[0] + q[0]) / 2; return [[m, p[1]], [m, q[1]]]; }
    if (s1 === 'l' && s2 === 'r' && q[0] < p[0] - 8) { const m = (p[0] + q[0]) / 2; return [[m, p[1]], [m, q[1]]]; }
    if (s1 === s2) { const X = s1 === 'r' ? Math.max(p[0], q[0]) + G : Math.min(p[0], q[0]) - G; return [[X, p[1]], [X, q[1]]]; }
    const a = p[0] + (s1 === 'r' ? G : -G), b = q[0] + (s2 === 'r' ? G : -G), m = (p[1] + q[1]) / 2;
    return [[a, p[1]], [a, m], [b, m], [b, q[1]]];
  }
  if (!horiz(s1) && !horiz(s2)) {
    if (Math.abs(p[0] - q[0]) < 0.5 && ((s1 === 'b' && q[1] > p[1]) || (s1 === 't' && q[1] < p[1]))) return [];
    if (s1 === 'b' && s2 === 't' && q[1] > p[1] + 8) { const m = (p[1] + q[1]) / 2; return [[p[0], m], [q[0], m]]; }
    if (s1 === 't' && s2 === 'b' && q[1] < p[1] - 8) { const m = (p[1] + q[1]) / 2; return [[p[0], m], [q[0], m]]; }
    if (s1 === s2) { const Y = s1 === 'b' ? Math.max(p[1], q[1]) + G : Math.min(p[1], q[1]) - G; return [[p[0], Y], [q[0], Y]]; }
    const a = p[1] + (s1 === 'b' ? G : -G), b = q[1] + (s2 === 'b' ? G : -G), m = (p[0] + q[0]) / 2;
    return [[p[0], a], [m, a], [m, b], [q[0], b]];
  }
  return horiz(s1) ? [[q[0], p[1]]] : [[p[0], q[1]]];
}

/** 角を丸めた折れ線 */
function pathOf(pts: Pt[], r = 14): string {
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i - 1], [bx, by] = pts[i], [cx, cy] = pts[i + 1];
    const d1 = Math.hypot(bx - ax, by - ay), d2 = Math.hypot(cx - bx, cy - by);
    if (!d1 || !d2) continue;
    const rr = Math.min(r, d1 / 2, d2 / 2);
    d += ` L${bx - (bx - ax) / d1 * rr},${by - (by - ay) / d1 * rr} Q${bx},${by} ${bx + (cx - bx) / d2 * rr},${by + (cy - by) / d2 * rr}`;
  }
  const last = pts[pts.length - 1];
  return d + ` L${last[0]},${last[1]}`;
}

function pointAt(pts: Pt[], t: number): Pt {
  const lens = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  let left = lens.reduce((a, b) => a + b, 0) * t;
  for (let i = 0; i < lens.length; i++) {
    if (left <= lens[i] || i === lens.length - 1) {
      const k = lens[i] ? Math.min(1, left / lens[i]) : 0;
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k];
    }
    left -= lens[i];
  }
  return pts[0];
}

/** 点 p に一番近い区間の番号 */
function nearestSegment(pts: Pt[], p: Pt): number {
  let best = 0, dist = Infinity;
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1];
    const L = (bx - ax) ** 2 + (by - ay) ** 2;
    const k = L ? Math.max(0, Math.min(1, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / L)) : 0;
    const d = Math.hypot(p[0] - (ax + (bx - ax) * k), p[1] - (ay + (by - ay) * k));
    if (d < dist) { dist = d; best = i; }
  }
  return best;
}

type View = { s: number; tx: number; ty: number };
type Gesture =
  | { kind: 'pan'; x: number; y: number; tx: number; ty: number; moved: boolean }
  | { kind: 'node'; id: string; x: number; y: number; box: Box; moved: boolean }
  | { kind: 'resize'; id: string; frame: boolean; x: number; y: number; box: Box; moved: boolean }
  | { kind: 'frame'; id: string; x: number; y: number; box: Box; inside: Record<string, Box>; via: Record<string, Pt[]>; moved: boolean }
  | { kind: 'point'; key: string; index: number; x: number; y: number; start: Pt; via: Pt[] | null; seg: number; moved: boolean };

export function ArchBoard({ trace, skills, onSkills, counts, active, glow, onPick, toolbar, annotation, marks }: {
  trace?: Trace; skills: PromptSummary[]; onSkills: (reader: string, id?: string) => void;
  counts: Record<string, number>; active: string; glow?: string; onPick: (id: string) => void;
  /** 右上の操作の帯の左に足す物（スキルを探す など） */
  toolbar?: ReactNode;
  annotation?: { node: string; title: string; body: ReactNode; open: () => void; close: () => void };
  /** チャットの直す案（部品 MapPlan）の番号。箱の左上に紫の丸で出す（lib/map-focus.ts） */
  marks?: PlanMark[];
}) {
  const port = useRef<HTMLDivElement>(null);
  const marker = useId().replace(/:/g, '');
  const [layout, setLayout] = useState<BoardLayout>(EMPTY);
  const [view, setView] = useState<View | null>(null);
  const [hover, setHover] = useState('');
  const viewRef = useRef<View | null>(null);
  useLayoutEffect(() => { viewRef.current = view; }, [view]);
  const gesture = useRef<Gesture | null>(null);
  const touches = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ d: number; s: number; cx: number; cy: number; tx: number; ty: number } | null>(null);
  const swallowClick = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const loaded = useRef(false);

  // 並べ方を読む・保存する（動かし終わってから少し待って1回）
  useEffect(() => {
    let live = true;
    promptRequest<BoardLayout>('/board-layout').then(got => { if (live) { setLayout({ ...EMPTY, ...got }); loaded.current = true; } })
      .catch(() => { loaded.current = true; });
    return () => { live = false; };
  }, []);
  const commit = useCallback((next: BoardLayout) => {
    setLayout(next);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => { void promptRequest('/board-layout', next as unknown as Record<string, unknown>).catch(() => undefined); }, 500);
  }, []);
  const layoutRef = useRef(layout);
  useLayoutEffect(() => { layoutRef.current = layout; }, [layout]);

  const boxOf = useCallback((n: ArchNode): Box => layout.nodes[n.id] || { x: n.x, y: n.y, w: n.w, h: n.height ?? BOX_H }, [layout]);
  const frameOf = useCallback((id: string): Box => {
    const f = layout.frames[id] || FRAMES[id];
    return { x: f.x, y: f.y, w: f.w, h: f.h };
  }, [layout]);

  const edges = useMemo(() => BOARD_EDGES.flatMap(e => {
    const a = BY_ID.get(e.from), b = BY_ID.get(e.to);
    if (!a || !b) return [];
    const sa = e.a || 'b', sb = e.b || 't';
    const p = anchor(boxOf(a), sa === 'b' && hasStrip(a.id) ? STRIP : 0, sa, e.ax);
    const q = anchor(boxOf(b), sb === 'b' && hasStrip(b.id) ? STRIP : 0, sb, e.bx);
    const key = edgeKey(e);
    const custom = layout.edges[key];
    const via = custom || e.via || autoVia(p, sa, q, sb);
    const pts = [p, ...via, q];
    return [{ e, key, pts, custom: !!custom || !!e.via, d: pathOf(pts), label: e.label ? pointAt(pts, e.at ?? 0.5) : null, via: custom || e.via || null }];
  }), [boxOf, layout.edges]);

  // 図全体の広さ（全体を表示の時に使う）
  const bounds = useMemo(() => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const add = (x: number, y: number) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); };
    for (const n of BOARD_NODES) { const b = boxOf(n); add(b.x, b.y); add(b.x + b.w, b.y + b.h + (hasStrip(n.id) ? STRIP : 0) + (n.id === 'reply' ? 220 : 0)); }
    for (const id of Object.keys(FRAMES)) { const f = frameOf(id); add(f.x, f.y); add(f.x + f.w, f.y + f.h); }
    for (const { pts } of edges) for (const [x, y] of pts) add(x, y);
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }, [boxOf, frameOf, edges]);

  const fit = useCallback(() => {
    const el = port.current;
    if (!el || !el.clientWidth) return;
    const m = 24, s = Math.min((el.clientWidth - m * 2) / bounds.w, (el.clientHeight - m * 2) / bounds.h);
    setView({ s, tx: (el.clientWidth - bounds.w * s) / 2 - bounds.x * s, ty: (el.clientHeight - bounds.h * s) / 2 - bounds.y * s });
  }, [bounds]);

  useEffect(() => {
    if (!view) return;
    const t = setTimeout(() => { try { localStorage.setItem(VIEW_KEY, JSON.stringify(view)); } catch { /* 保存できなくても見るのは困らない */ } }, 300);
    return () => clearTimeout(t);
  }, [view]);
  // 最初は前に見ていた所、無ければ全体。枠の大きさが 0 の間に開いた時（隠れたタブなど）は、見えた時に決める
  useEffect(() => {
    const el = port.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (viewRef.current || !el.clientWidth) return;
      try {
        const saved = JSON.parse(localStorage.getItem(VIEW_KEY) || 'null') as View | null;
        if (saved && saved.s > 0 && Number.isFinite(saved.tx) && Number.isFinite(saved.ty)) { viewRef.current = saved; setView(saved); return; }
      } catch { /* 読めなければ全体を表示 */ }
      fit();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  const zoomAt = useCallback((cx: number, cy: number, factor: number) => {
    setView(v => {
      if (!v) return v;
      const s = Math.min(MAX_S, Math.max(MIN_S, v.s * factor));
      const k = s / v.s;
      return { s, tx: cx - (cx - v.tx) * k, ty: cy - (cy - v.ty) * k };
    });
  }, []);

  // ホイール＝寄る・引く（ずらす役目は持たせない）。トラックパッドのつまむ動きも同じ
  useEffect(() => {
    const el = port.current;
    if (!el) return;
    const wheel = (ev: WheelEvent) => {
      const box = (ev.target as Element).closest<HTMLElement>('[data-reply]');   // 返事の本文が長い時は、その中を読み進める
      if (box && box.scrollHeight > box.clientHeight && !ev.ctrlKey) return;
      ev.preventDefault();
      const r = el.getBoundingClientRect();
      const dy = ev.deltaY * (ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? 400 : 1);
      zoomAt(ev.clientX - r.left, ev.clientY - r.top, Math.exp(-dy * (ev.ctrlKey ? 0.01 : 0.0018)));
    };
    el.addEventListener('wheel', wheel, { passive: false });
    return () => el.removeEventListener('wheel', wheel);
  }, [zoomAt]);

  // 選んだ箱・今の段階の箱が見えていなければ、その箱を真ん中へ
  useEffect(() => {
    const id = active || trace?.current || annotation?.node;
    const n = id ? BY_ID.get(id) : undefined;
    const el = port.current, v = viewRef.current;
    if (!n || !el || !v) return;
    const b = boxOf(n);
    const L = b.x * v.s + v.tx, T = b.y * v.s + v.ty, R = (b.x + b.w) * v.s + v.tx, B = (b.y + b.h) * v.s + v.ty;
    if (L >= 0 && T >= 0 && R <= el.clientWidth && B <= el.clientHeight) return;
    setView({ ...v, tx: el.clientWidth / 2 - (b.x + b.w / 2) * v.s, ty: el.clientHeight / 2 - (b.y + b.h / 2) * v.s });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, trace?.current, annotation?.node]);

  const toBoard = (clientX: number, clientY: number): Pt => {
    const el = port.current!, v = viewRef.current!, r = el.getBoundingClientRect();
    return [(clientX - r.left - v.tx) / v.s, (clientY - r.top - v.ty) / v.s];
  };

  // ---- 押す・動かす ----
  const onPointerDown = (ev: React.PointerEvent<HTMLDivElement>) => {
    const v = viewRef.current;
    if (!v) return;
    if (ev.pointerType === 'touch') {
      touches.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (touches.current.size === 2) {
        const [a, b] = [...touches.current.values()], r = port.current!.getBoundingClientRect();
        pinch.current = { d: Math.hypot(a.x - b.x, a.y - b.y), s: v.s, cx: (a.x + b.x) / 2 - r.left, cy: (a.y + b.y) / 2 - r.top, tx: v.tx, ty: v.ty };
        gesture.current = null;
        return;
      }
    }
    if (ev.button === 1 || ev.button === 2) {   // 真ん中・右のボタンはどこでも移動
      gesture.current = { kind: 'pan', x: ev.clientX, y: ev.clientY, tx: v.tx, ty: v.ty, moved: false };
      return;
    }
    if (ev.button !== 0) return;
    const t = ev.target as Element;
    const mouse = ev.pointerType === 'mouse' || ev.pointerType === 'pen';
    const resize = t.closest<HTMLElement>('[data-resize]');
    const point = t.closest<SVGElement>('[data-waypoint]');
    const hit = t.closest<SVGElement>('[data-edge-hit]');
    const frame = t.closest<HTMLElement>('[data-frame-grip]');
    const node = t.closest<HTMLElement>('[data-node-wrap]');
    if (mouse && resize) {
      const id = resize.dataset.resize!, isFrame = id.startsWith('frame:');
      const box = isFrame ? frameOf(id.slice(6)) : boxOf(BY_ID.get(id)!);
      gesture.current = { kind: 'resize', id: isFrame ? id.slice(6) : id, frame: isFrame, x: ev.clientX, y: ev.clientY, box, moved: false };
    } else if (mouse && point) {
      const key = point.dataset.waypoint!, index = Number(point.dataset.index);
      const via = edges.find(x => x.key === key)?.via || [];
      gesture.current = { kind: 'point', key, index, x: ev.clientX, y: ev.clientY, start: via[index], via: [...via], seg: -1, moved: false };
    } else if (mouse && hit) {
      const key = hit.dataset.edgeHit!, line = edges.find(x => x.key === key)!;
      const at = toBoard(ev.clientX, ev.clientY);
      gesture.current = { kind: 'point', key, index: -1, x: ev.clientX, y: ev.clientY, start: at, via: null, seg: nearestSegment(line.pts, at), moved: false };
    } else if (mouse && frame) {
      const id = frame.dataset.frameGrip!, box = frameOf(id);
      const inside: Record<string, Box> = {};
      for (const n of BOARD_NODES) {
        const b = boxOf(n);
        if (b.x >= box.x && b.y >= box.y && b.x + b.w <= box.x + box.w && b.y + b.h <= box.y + box.h) inside[n.id] = b;
      }
      const via: Record<string, Pt[]> = {};
      for (const x of edges) if (x.via && inside[x.e.from] && inside[x.e.to]) via[x.key] = x.via;
      gesture.current = { kind: 'frame', id, x: ev.clientX, y: ev.clientY, box, inside, via, moved: false };
    } else if (mouse && node) {
      const id = node.dataset.nodeWrap!;
      gesture.current = { kind: 'node', id, x: ev.clientX, y: ev.clientY, box: boxOf(BY_ID.get(id)!), moved: false };
    } else {
      if (!mouse && t.closest('button, a, input, textarea, select, [data-reply]') && !node) return;
      gesture.current = { kind: 'pan', x: ev.clientX, y: ev.clientY, tx: v.tx, ty: v.ty, moved: false };
    }
  };

  const onPointerMove = (ev: React.PointerEvent<HTMLDivElement>) => {
    const v = viewRef.current;
    if (!v) return;
    if (ev.pointerType === 'touch' && touches.current.has(ev.pointerId)) {
      touches.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      const p = pinch.current;
      if (p && touches.current.size >= 2) {
        const [a, b] = [...touches.current.values()], r = port.current!.getBoundingClientRect();
        const s = Math.min(MAX_S, Math.max(MIN_S, p.s * Math.hypot(a.x - b.x, a.y - b.y) / (p.d || 1)));
        const cx = (a.x + b.x) / 2 - r.left, cy = (a.y + b.y) / 2 - r.top;
        setView({ s, tx: cx - (p.cx - p.tx) * s / p.s, ty: cy - (p.cy - p.ty) * s / p.s });
        swallowClick.current = true;
        return;
      }
    }
    const g = gesture.current;
    if (!g) return;
    const dx = ev.clientX - g.x, dy = ev.clientY - g.y;
    if (!g.moved) {
      if (Math.hypot(dx, dy) < 4) return;
      g.moved = true;
      port.current?.setPointerCapture(ev.pointerId);
    }
    const bx = dx / v.s, by = dy / v.s;
    const L = layoutRef.current;
    if (g.kind === 'pan') setView({ ...v, tx: g.tx + dx, ty: g.ty + dy });
    else if (g.kind === 'node') setLayout({ ...L, nodes: { ...L.nodes, [g.id]: { ...g.box, x: g.box.x + bx, y: g.box.y + by } } });
    else if (g.kind === 'resize') {
      const box = { ...g.box, w: Math.max(40, g.box.w + bx), h: Math.max(30, g.box.h + by) };
      setLayout(g.frame ? { ...L, frames: { ...L.frames, [g.id]: box } } : { ...L, nodes: { ...L.nodes, [g.id]: box } });
    } else if (g.kind === 'frame') {
      const nodes = { ...L.nodes };
      for (const [id, b] of Object.entries(g.inside)) nodes[id] = { ...b, x: b.x + bx, y: b.y + by };
      const lines = { ...L.edges };
      for (const [key, via] of Object.entries(g.via)) lines[key] = via.map(([x, y]) => [x + bx, y + by] as Pt);
      setLayout({ nodes, edges: lines, frames: { ...L.frames, [g.id]: { ...g.box, x: g.box.x + bx, y: g.box.y + by } } });
    } else if (g.kind === 'point') {
      if (!g.via) {   // 線の途中を押して動かし始めた: そこに点を足す
        const line = edges.find(x => x.key === g.key)!;
        const via = line.pts.slice(1, -1);
        via.splice(g.seg, 0, g.start);
        g.via = via; g.index = g.seg;
      }
      const via = g.via.map((p, i) => (i === g.index ? [g.start[0] + bx, g.start[1] + by] as Pt : p));
      setLayout({ ...L, edges: { ...L.edges, [g.key]: via } });
    }
  };

  const end = (ev: React.PointerEvent<HTMLDivElement>) => {
    touches.current.delete(ev.pointerId);
    if (touches.current.size < 2) pinch.current = null;
    const g = gesture.current;
    gesture.current = null;
    if (!g?.moved) return;
    swallowClick.current = true;
    if (g.kind !== 'pan') commit(layoutRef.current);
  };

  const removePoint = (key: string, index: number) => {
    const line = edges.find(x => x.key === key);
    if (!line?.via) return;
    commit({ ...layout, edges: { ...layout.edges, [key]: line.via.filter((_, i) => i !== index) } });
  };

  const customized = Object.keys(layout.nodes).length + Object.keys(layout.frames).length + Object.keys(layout.edges).length > 0;
  const previews = useMemo(() => Object.fromEntries(Object.entries(READER_EXAMPLES).map(([reader, example]) => {
    const entries = readerGroups(reader, skills).flatMap(g => g.entries);
    return [reader, { example: entries.find(e => e.page.id === 'skill/' + example), count: entries.length }];
  })), [skills]);

  const s = view?.s ?? 1;
  let grid = 18 * s;
  while (grid < 12) grid *= 4;
  while (grid > 72) grid /= 4;
  const annotated = annotation && BY_ID.get(annotation.node);
  const anchorBox = annotated && boxOf(annotated);
  const panelWidth = Math.min(320, (port.current?.clientWidth || 336) - 16);
  let panelLeft = 8, panelTop = 52;
  if (anchorBox && view && port.current) {
    const left = view.tx + anchorBox.x * s, right = left + anchorBox.w * s;
    panelTop = view.ty + anchorBox.y * s;
    if (right + 8 + panelWidth <= port.current.clientWidth) panelLeft = right + 8;
    else if (left >= panelWidth + 8) panelLeft = left - panelWidth - 8;
    else panelTop += anchorBox.h * s + 8;
  }
  const hitWidth = Math.max(8, 14 / s);
  const handle = Math.max(8, 14 / s);
  const tool = 'inline-flex h-8 min-w-8 items-center justify-center gap-1 rounded-md border border-stone-300 bg-white/95 px-2 text-xs font-semibold text-stone-800 shadow-sm hover:bg-stone-100';

  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden bg-[#fcfbf8]" data-freeboard>
      <div ref={port} className="absolute inset-0 touch-none select-none"
        style={{ backgroundImage: 'radial-gradient(#cecac2 1px,transparent 1px)', backgroundSize: `${grid}px ${grid}px`, backgroundPosition: `${view?.tx ?? 0}px ${view?.ty ?? 0}px`, cursor: 'grab' }}
        onContextMenu={e => e.preventDefault()}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={end} onPointerCancel={end}
        onClickCapture={e => { if (swallowClick.current) { swallowClick.current = false; e.stopPropagation(); e.preventDefault(); } }}>
        {view && <div className="absolute left-0 top-0" style={{ transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.s})`, transformOrigin: '0 0' }}>
          {/* 枠（作業の部屋・動画を作る・直す時）。題を押したまま動かすと中の箱ごと動く */}
          {Object.entries(FRAMES).map(([id, f]) => {
            const b = frameOf(id);
            return <div key={id} className="group absolute rounded-2xl border-2 border-dashed border-stone-300 bg-stone-50/80" style={{ left: b.x, top: b.y, width: b.w, height: b.h }}>
              <span data-frame-grip={id} className="absolute left-3 top-1.5 cursor-move text-[13px] font-bold text-stone-600">{f.name}</span>
              {f.line && <p className="absolute bottom-2 left-3.5 right-3.5 text-[12px] text-stone-500">{f.line}</p>}
              <span data-resize={'frame:' + id} className="absolute bottom-0 right-0 hidden cursor-nwse-resize rounded-sm border border-stone-400 bg-white group-hover:block"
                style={{ width: handle, height: handle, transform: 'translate(50%,50%)' }} />
            </div>;
          })}

          {BOARD_NODES.map(n => {
            const b = boxOf(n), on = n.id === active, count = counts[n.id] || 0;
            const pick = () => { const visit = trace?.visits.get(n.id); if (visit != null) trace?.inspect?.(n.id, visit); onPick(n.id); };
            const state = trace?.current === n.id ? 'current' : trace?.visits.has(n.id) ? 'visited' : undefined;
            return (
              <div key={n.id} data-annotated={annotation?.node === n.id || undefined} data-node-wrap={n.id} className="group absolute data-[annotated=true]:rounded-lg data-[annotated=true]:ring-4 data-[annotated=true]:ring-indigo-500" style={{ left: b.x, top: b.y, width: b.w, height: b.h }}>
                {marks?.some(m => m.node === n.id) && <span className="pointer-events-none absolute -inset-2 z-10 rounded-2xl border-4 border-violet-500/80" data-plan-mark={n.id}>
                  <span className="absolute -left-5 -top-6 flex gap-1">
                  {marks.filter(m => m.node === n.id).map(m => <span key={m.n} title={m.title}
                    className="flex h-11 min-w-11 items-center justify-center rounded-full border-[3px] border-white bg-violet-600 px-1 text-2xl font-extrabold text-white shadow-lg">{m.n}</span>)}
                </span></span>}
                {n.height ? <button type="button" data-arch-node={n.id} aria-label={n.name} data-trace-state={state} onClick={pick}
                  className={cn('flex h-full w-full flex-col items-center justify-end gap-1 rounded-lg text-stone-900 hover:bg-stone-100/70 focus-visible:outline-2', (on || trace?.current === n.id) && 'ring-2 ring-emerald-600')}>
                  {n.id === 'pc' ? <span className="flex min-h-0 w-full flex-1 flex-col items-center">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src="/prompts/arch/chat-pc.webp" alt="PCのチャット画面" draggable={false} className="min-h-0 w-[94%] flex-1 rounded-t-[3px] border-[3px] border-stone-800 bg-black object-contain" />
                    <span className="block h-[8px] w-full shrink-0 rounded-b-xl border-b-[3px] border-stone-500 bg-stone-300" />
                  </span> : n.id === 'phone'
                    // eslint-disable-next-line @next/next/no-img-element
                    ? <img src="/prompts/arch/chat-phone.webp" alt="スマホのチャット画面" draggable={false} className="min-h-0 max-w-full flex-1 rounded-[8px] border-[3px] border-stone-700 bg-black object-contain shadow-md" />
                    : n.cutout
                    // eslint-disable-next-line @next/next/no-img-element
                    ? <img src={`/prompts/arch/${n.icon}.webp`} alt="" draggable={false} className="min-h-0 w-full flex-1 object-contain drop-shadow-md" />
                    // eslint-disable-next-line @next/next/no-img-element
                    : <img src={`/prompts/arch/${n.icon}.webp`} alt="エディターの画面" draggable={false} className="min-h-0 w-full flex-1 rounded-md border-[3px] border-stone-700 bg-black object-contain" />}
                  <span className="shrink-0 text-sm font-bold leading-tight">{n.name}</span>
                </button> : <button type="button" data-arch-node={n.id} data-trace-state={state} onClick={pick}
                  className={cn('relative flex h-full w-full items-center gap-2 rounded-xl border-2 bg-white p-1.5 text-left shadow-sm transition hover:border-amber-400 hover:bg-amber-50',
                    on ? 'border-amber-500 bg-amber-50 ring-4 ring-amber-200' : 'border-stone-300',
                    trace?.visits.has(n.id) && 'border-emerald-600',
                    trace?.current === n.id && (trace.failed ? 'border-rose-700 ring-4 ring-rose-300' : 'ring-4 ring-emerald-300'),
                    n.id === glow && 'dan-working-glow border-violet-500')} data-dan-working={n.id === glow ? '' : undefined}>
                  {trace?.visits.has(n.id) && <span className={cn('absolute -right-1.5 -top-2.5 rounded-full px-2 py-0.5 text-[11px] font-bold text-white', trace.current === n.id && trace.failed ? 'bg-rose-800' : 'bg-emerald-800')}>
                    {trace.current === n.id ? (trace.failed ? '失敗 ' : '現在 ') : ''}{trace.visits.get(n.id)! + 1}</span>}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={`/prompts/arch/${n.icon}.webp`} alt="" draggable={false} className="aspect-square h-full max-h-[60px] shrink-0 rounded-lg object-cover" />
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 block text-[14px] font-bold leading-tight text-stone-900">{n.name}</span>
                    <span className="mt-0.5 block truncate text-[11px] leading-tight text-stone-500">{n.model}</span>
                    {count ? <span className="mt-1 inline-block rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-900">指示文 {count}</span>
                      : n.same ? <span className="mt-1 inline-block text-[11px] text-stone-400">{BY_ID.get(n.same)?.name}と同じ文</span>
                      : n.programs?.length ? <span className="mt-1 inline-block rounded-full bg-sky-100 px-1.5 text-[11px] font-semibold text-sky-900">プログラム {n.programs.length}</span> : null}
                  </span>
                </button>}
                {hasStrip(n.id) && <div style={{ top: b.h, height: STRIP }}
                  className="absolute inset-x-[3px] flex flex-col justify-center rounded-b-xl border border-t-0 border-teal-300 bg-teal-50 px-2 text-teal-950">
                  {n.id === 'voice' ? <button type="button" className="text-left hover:underline" onClick={() => onSkills('parallel')}>
                    <span className="block text-[12px]">通話で制作を頼んだ時</span><span className="text-[14px] font-bold">並行作業でスキルを読む →</span>
                  </button> : <>
                    <button type="button" aria-label={n.name + 'が読むスキル'} onClick={() => onSkills(n.id)}
                      className="flex min-h-7 items-center gap-1 text-[13px] font-bold hover:underline"><BookOpen size={14} />スキル {previews[n.id]?.count || ''}<span className="ml-auto">すべて ›</span></button>
                    {n.video ? <button type="button" data-video-branch={n.id} onClick={() => onPick('v-owner')}
                      className="flex items-center gap-1 rounded border border-violet-300 bg-violet-50 px-2 py-1 text-left text-violet-950 hover:border-violet-600">
                      <Clapperboard size={14} className="shrink-0" /><span className="min-w-0 flex-1 truncate text-[13px] font-bold">動画制作の手順</span><ChevronRight size={14} className="shrink-0" />
                    </button> : previews[n.id]?.example && <button type="button" onClick={() => onSkills(n.id, previews[n.id].example!.page.id)}
                      className="rounded border border-teal-200 bg-white px-2 py-1 text-left hover:border-teal-600">
                      <span className="block truncate text-[13px] font-semibold">{previews[n.id].example!.request}</span>
                      <span className="block truncate text-[11px] text-teal-800">{previews[n.id].example!.page.title}</span>
                    </button>}
                  </>}
                </div>}
                {n.id === 'reply' && <div data-reply className="absolute inset-x-0 max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-[15px] leading-relaxed" style={{ top: b.h + 8 }}
                >
                  {trace?.reply || '返事の記録がある依頼を選ぶと、ここに本文が出ます。'}
                </div>}
                {trace?.current === n.id && trace.activity && <span data-flow-bubble title={trace.activity}
                  className="pointer-events-none absolute z-10 max-w-[260px] truncate rounded-lg bg-emerald-950 px-3 py-1.5 text-xs font-semibold text-white shadow"
                  style={b.x + b.w / 2 < bounds.x + bounds.w / 2 ? { left: b.w + 7, top: 16 } : { right: b.w + 7, top: 16 }}>{trace.activity}</span>}
                <span data-resize={n.id} title="引いて大きさを変える" className="absolute bottom-0 right-0 z-20 hidden cursor-nwse-resize rounded-sm border border-stone-500 bg-white shadow group-hover:block"
                  style={{ width: handle, height: handle, transform: 'translate(50%,50%)' }} />
              </div>
            );
          })}

          {/* 線は箱より手前（裏を通って見えなくならない）。太い透明の線で押しやすく */}
          <svg className="pointer-events-none absolute overflow-visible" aria-hidden="true"
            style={{ left: bounds.x - 200, top: bounds.y - 200, width: bounds.w + 400, height: bounds.h + 400 }}>
            <g transform={`translate(${200 - bounds.x},${200 - bounds.y})`}>
            <defs>
              <marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#78716c" />
              </marker>
              <marker id={marker + '-on'} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#b45309" />
              </marker>
              <marker id={marker + '-trace'} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#047857" />
              </marker>
            </defs>
            {edges.map(({ e, key, d, via }) => {
              const line = trace?.lines.get(key), hot = hover === key;
              const arrow = 'url(#' + marker + (line ? '-trace' : hot ? '-on' : '') + ')';
              return <g key={key} onPointerEnter={() => setHover(key)} onPointerLeave={() => setHover(h => (h === key ? '' : h))}>
                <path d={d} data-edge-hit={key} fill="none" stroke="transparent" strokeWidth={hitWidth} style={{ pointerEvents: 'stroke', cursor: 'move' }} />
                <path d={d} data-flow-path={key} data-trace-edge={line ? key : undefined}
                  fill="none" stroke={line ? '#68a891' : hot ? '#d97706' : '#a8a29e'} strokeWidth={line ? 4 : hot ? 3 : 2}
                  strokeDasharray={line ? (line.inferred ? '6 5' : undefined) : e.dashed ? '6 5' : undefined}
                  markerStart={line?.reverse ? arrow : undefined} markerEnd={line?.reverse ? undefined : arrow} />
                {hot && via?.map(([x, y], i) => <circle key={i} data-waypoint={key} data-index={i} cx={x} cy={y} r={handle / 2}
                  fill="#fff" stroke="#d97706" strokeWidth={Math.max(1.5, 2 / s)} style={{ pointerEvents: 'all', cursor: 'move' }}
                  onDoubleClick={ev => { ev.stopPropagation(); removePoint(key, i); }}><title>動かす・2回押すと消す</title></circle>)}
              </g>;
            })}
            {trace && <circle data-flow-particle r={7} fill="#10b981" stroke="#034b37" strokeWidth={2} visibility="hidden" />}
            </g>
          </svg>
          {edges.filter(x => x.label).map(({ e, key, label }) => (
            <span key={'l-' + key} className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded bg-white/95 px-1 text-[11px] leading-tight text-stone-600 shadow-[0_0_0_1px_rgba(0,0,0,0.04)]"
              style={{ left: label![0], top: label![1] }}>{e.label}</span>
          ))}
        </div>}
      </div>

      {view && annotation && anchorBox && <aside data-board-annotation={annotation.node} aria-label={annotation.title}
        className="absolute z-10 max-h-[46%] overflow-auto overscroll-contain rounded-lg border border-indigo-300 bg-white p-3 text-xs leading-relaxed shadow-md"
        style={{width:'min(320px, calc(100% - 16px))',
          left: panelLeft, top: 'clamp(52px, '+panelTop+'px, 51%)'}}>
        <div className="mb-2 flex items-center justify-between gap-2">
          <button type="button" className="font-semibold text-indigo-900 hover:underline" onClick={annotation.open}>{annotation.title} ›</button>
          <button type="button" onClick={annotation.close} aria-label="図の説明を閉じる" className="px-2 text-base">×</button>
        </div>{annotation.body}
      </aside>}
      {/* 操作の帯（ボードの上に浮かせる） */}
      <div className="pointer-events-none absolute right-2 top-2 z-10 flex flex-wrap items-center justify-end gap-1">
        <span className="pointer-events-auto flex flex-wrap items-center gap-1">
          {toolbar}
          <button type="button" aria-label="引く" className={tool} onClick={() => { const el = port.current; if (el) zoomAt(el.clientWidth / 2, el.clientHeight / 2, 0.8); }}><Minus size={14} /></button>
          <span className="w-12 rounded-md bg-white/90 py-1 text-center text-xs tabular-nums text-stone-700">{Math.round(s * 100)}%</span>
          <button type="button" aria-label="寄る" className={tool} onClick={() => { const el = port.current; if (el) zoomAt(el.clientWidth / 2, el.clientHeight / 2, 1.25); }}><Plus size={14} /></button>
          <button type="button" className={tool} onClick={fit}><Maximize size={13} />全体を表示</button>
          {customized && <button type="button" className={tool} onClick={() => { if (window.confirm('動かした箱・枠・線を、元の並べ方に戻しますか？')) commit(EMPTY); }}><RotateCcw size={13} />元の並べ方</button>}
        </span>
      </div>
    </div>
  );
}
