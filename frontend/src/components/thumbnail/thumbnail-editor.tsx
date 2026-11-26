'use client';

// エディターの中のサムネの画面（2026-11-18 本人「サムネの微調整の往復に時間がかかりすぎる」→「部品に分けたサムネ」
// 「描き込んで直す」）。背景・人物・文字・矢印を別々の部品で持ち、
// - 選ぶ: 部品をつかんで動かす・角で大きさ・上の丸で回す・右の欄で文字を打ち直す／色・縁・書体を変える
// - 書き込む: ペンで丸や矢印を描いて一言添えて送ると、ダンが直す（結果はこの欄にだけ出し、チャットには出さない）。
//   会話の横で開いた時（chatLink、台本を聞く画面）は、選んだ部品とペンの書き込みを会話の入力欄に添え、ダンとはその会話で話す
//   （2026-11-21 本人「要素クリックしてもそれがチャットに添付されない」「このサムネとかって言っても通じるのか？」）
// - 一覧で見る: YouTube の一覧と同じ小さい大きさで、ほかのサムネと並べて見る
// 保存は手を離した時に自動。ダンが直した形は1.5秒ごとに読み直して、目の前で変わる。

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  AlignCenterHorizontal, AlignCenterVertical, AlignEndHorizontal, AlignEndVertical, AlignStartHorizontal, AlignStartVertical,
  AlignHorizontalSpaceAround, AlignVerticalSpaceAround,
  ArrowLeft, ArrowDown, ArrowUp, Check, Copy, Download, Eye, EyeOff, ImagePlus, LayoutGrid, Columns3, Loader2, Lock, MessageSquare,
  Frame, GripVertical, MousePointer2, PenLine, Redo2, RefreshCw, RotateCcw, Send, Sparkles, Trash2, Type, Undo2, Unlock, X,
} from 'lucide-react';
import { toast } from 'sonner';

import { PartPreview, ThumbCanvas, partBounds, partCenter, type PartBox } from './thumb-canvas';
import { ThumbPatterns, cachedThumbDoc, rememberThumbDoc, type ThumbPatternActions, type ThumbPatternLink } from './thumb-patterns';
import { ThumbLineup } from './thumb-lineup';
import { useChatAttachStore, useChatAttachments } from '@/stores/chat-attach-store';
import {
  THUMB_FONTS, applyFinish, asThumbDoc, finishPart, loadThumbFonts, mergeThumbDocs, newPartId, removeFinish, reorderParts, stepParts,
  type ThumbDoc, type ThumbFinishJob, type ThumbFontId, type ThumbInstruction, type ThumbMark, type ThumbPart, type ThumbTextPart,
} from './thumb-doc';

type Props = {
  roomId: string;
  contentId: string;
  title: string;
  compact?: boolean;
  phoneChat?: ((lead: ReactNode) => ReactNode) | null;
  onBack: () => void;
  /** 戻るボタンの説明（既定はエディターのライブラリへ。台本を聞く画面では「台本に戻る」） */
  backLabel?: string;
  /** 横の会話につなぐ（台本を聞く画面）。選んだ部品・ペンの書き込みをその会話の入力欄に添える */
  chatLink?: ChatLink | null;
  /** 「読み直す」の前に、開くべき作品が変わっていないか確かめる（台本を聞く画面）。別の作品へ移ったら true */
  onReload?: () => Promise<boolean>;
  /** 同じ動画のサムネの案を下に並べて増やす（エディターの制作の窓）。無ければ帯を出さない */
  patterns?: ThumbPatternLink | null;
};

export type ChatLink = {
  /** 会話の部屋（ProjectChatPanel の projectId） */
  projectId: string;
  /** 今の形にペンの線・部品の枠を重ねた絵を作り、会話に添えられる URL を返す */
  snapshot: (body: { marks?: ThumbMark[]; box?: number[] | null }) => Promise<string | null>;
  /** 選んでいる部品が変わった時（ダンの「この文字」のため。選んでいなければ空） */
  onContext?: (part: string) => void;
};

const r0 = (v: number) => Math.round(v);

type JobState = { job_id: string; state: string; label: string; active: boolean; progress?: string | null; result?: string | null };

// つかんで動かす・大きさを変えるのは、選んでいる部品の全部（1つでも複数でも同じ形）。回すのは1つの時だけ
// 元に戻す・やり直すの1手（本人の1手の前後）。この窓の間は sessionStorage に控え、読み直しても消さない
type UndoStep = { before: ThumbDoc; after: ThumbDoc };
const UNDO_MAX = 60;
function readUndo(key: string): { undo: UndoStep[]; redo: UndoStep[] } {
  try {
    const raw = typeof window !== 'undefined' ? window.sessionStorage.getItem(key) : null;
    const j = raw ? JSON.parse(raw) : null;
    if (j && Array.isArray(j.undo) && Array.isArray(j.redo)) return { undo: j.undo, redo: j.redo };
  } catch { /* 控えが壊れていれば空から */ }
  return { undo: [], redo: [] };
}
function writeUndo(key: string, undo: UndoStep[], redo: UndoStep[]) {
  // 入りきらなければ古い手から落とす
  for (let n = undo.length; n >= 0; n = n > 10 ? Math.floor(n / 2) : n - 1) {
    try { window.sessionStorage.setItem(key, JSON.stringify({ undo: undo.slice(undo.length - n), redo: redo.slice(-n) })); return; } catch { /* 次は少なく */ }
  }
}
// 部品のコピー・貼り付け（Ctrl+C / X / V）。同じ動画のほかの案へも貼れるよう、この端末に控え、OS のクリップボードにも載せる
const CLIP_MARK = 'dan-thumb-parts:';
const CLIP_KEY = 'thumb-clipboard';
function readClip(text?: string | null): ThumbPart[] | null {
  try {
    const raw = text && text.startsWith(CLIP_MARK) ? text.slice(CLIP_MARK.length) : (!text ? window.localStorage.getItem(CLIP_KEY) : null);
    const j = raw ? JSON.parse(raw) : null;
    return Array.isArray(j) && j.length ? (j as ThumbPart[]) : null;
  } catch { return null; }
}

// 字を打つ欄（ここでは Ctrl+Z などをその欄に任せる）。つまみ・色・チェック・ボタンは字を打つ欄ではない
const TEXT_INPUTS = new Set(['', 'text', 'search', 'email', 'url', 'tel', 'password', 'number']);
function isTextField(el: Element | null | undefined): boolean {
  if (!el || !(el instanceof HTMLElement)) return false;
  if (el.isContentEditable || el.tagName === 'TEXTAREA') return true;
  return el.tagName === 'INPUT' && TEXT_INPUTS.has(((el as HTMLInputElement).getAttribute('type') || '').toLowerCase());
}

type Drag =
  | { kind: 'move'; ids: string[]; start: [number, number]; origs: Record<string, ThumbPart>; before: ThumbDoc; box0: PartBox | null; tx: number[]; ty: number[] }
  | { kind: 'scale'; ids: string[]; anchor: [number, number]; startDist: number; origs: Record<string, ThumbPart>; before: ThumbDoc }
  | { kind: 'rotate'; ids: string[]; center: [number, number]; startAngle: number; origs: Record<string, ThumbPart>; before: ThumbDoc; group?: Record<string, [number, number]> }
  | { kind: 'marquee'; start: [number, number]; base: string[]; moved: boolean; clickPick: string | null }
  | { kind: 'pen' };

function unionBox(bs: PartBox[]): PartBox | null {
  if (!bs.length) return null;
  const x0 = Math.min(...bs.map((b) => b.x)), y0 = Math.min(...bs.map((b) => b.y));
  const x1 = Math.max(...bs.map((b) => b.x + b.w)), y1 = Math.max(...bs.map((b) => b.y + b.h));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

const PEN_COLOR = '#ff2a2a';
// ダンの直しを見せる長さ（前の形から今の形へ動く0.7秒＋光と「ダン」の印が残る間）
const DAN_MOVE_MS = 700;
const DAN_FX_MS = 3200;
type DanActivity = { parts: string[]; label: string; at: number; until: number };
type DanFx = { t0: number; from: Record<string, ThumbPart>; ghosts: Array<{ part: ThumbPart; after: string | null }>; touched: string[]; gone: ThumbPart[] };
const LERP_KEYS = ['x', 'y', 'w', 'h', 'size', 'rotation', 'opacity', 'stroke_width', 'outline_width', 'letter_spacing'] as const;
// コメントを付けた部品を、ダンに渡す絵の上で囲む色
const TARGET_COLOR = '#38bdf8';
// 作業台（サムネの枠の外）の余白。枠の周りに少しと、はみ出た部品の周り
const BOARD_PAD = 0.06;
const BOARD_PART_PAD = 40;
// サムネの周りの余白（角のつまみと回すつまみが出る所）
const STAGE_MARGIN = 28;
// 絵の透けた所を押しても、その絵は選ばない（下の部品を選ぶ）。この濃さより薄い所は透けている扱い
const HIT_ALPHA = 24;

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
    outline_width: r(p.outline_width),
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

/** ダンに渡す部品の中身（種類・名前・位置・文字・色） */
function partDetail(p: ThumbPart, b: PartBox): string {
  const where = `位置 x=${r0(b.x)} y=${r0(b.y)} 幅${r0(b.w)} 高さ${r0(b.h)}`;
  const hid = p.hidden ? '・今は隠してある' : '';
  if (p.type === 'text') {
    return `部品 ${p.id}（文字「${p.text.replace(/\n/g, ' / ')}」・名前「${p.name || ''}」・${where}・大きさ${r0(p.size)}・書体 ${p.font}・色 ${p.fill}${p.stroke ? `・縁 ${p.stroke}/${p.stroke_width ?? ''}` : ''}${p.rotation ? `・回転${p.rotation}` : ''}${hid}）`;
  }
  return `部品 ${p.id}（絵「${p.name || ''}」・${where}${p.rotation ? `・回転${p.rotation}` : ''}${hid}）`;
}

let lastStageW = 800;

export function ThumbnailEditor({ roomId, contentId, title, compact = false, phoneChat, onBack, backLabel, chatLink, onReload, patterns }: Props) {
  // 案を移った時は、下の帯が持っていた形から始める（読み込み中の表示を出さずにすぐ切り替わる。2026-11-26 本人「シームレスに」）
  const [startDoc] = useState(() => cachedThumbDoc(contentId));
  const [doc, setDoc] = useState<ThumbDoc | null>(startDoc);
  const docRef = useRef<ThumbDoc | null>(null);
  docRef.current = doc;
  const baseRev = useRef<number>(startDoc ? startDoc.rev ?? 0 : -1);
  // 手元の形の元にした保存の形（ほかの所＝ダン・別の画面の直しを、手元の直しと重ね合わせる時の基準）
  const baseDoc = useRef<ThumbDoc | null>(startDoc);
  const dirty = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const [saving, setSaving] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  // 選んでいる部品（複数可。2026-11-24 本人「要素複数選択できるようにして。エディター直操作でもパーツ一覧でも」）。
  // 並びは選んだ順。selected は1つだけ選んでいる時のその部品（右の欄の細かい直しは1つの時だけ）
  const [selection, setSelection] = useState<string[]>([]);
  const selected = selection.length === 1 ? selection[0] : null;
  const setSelected = useCallback((id: string | null) => setSelection(id ? [id] : []), []);
  const listAnchor = useRef<string | null>(null);
  const [marquee, setMarquee] = useState<PartBox | null>(null);
  // 動かしている間、揃った線（ほかの部品・サムネの端や真ん中）
  const [guides, setGuides] = useState<Array<{ x?: number; y?: number }>>([]);
  const [mode, setMode] = useState<'select' | 'pen'>('select');
  const [boxes, setBoxes] = useState<Record<string, PartBox>>({});
  // 元に戻す・やり直すは「本人の1手の前後」。今の形にその1手だけを当てる（あとから入ったダンの直しは巻き戻さない）
  // 読み直しても・案を行き来しても消えないよう、この窓の間は sessionStorage に控える（2026-11-24 本人「control＋zで操作取り消せるようにして」）
  const undoKey = `thumb-undo:${contentId}`;
  const [savedUndo] = useState(() => readUndo(undoKey));
  const undoStack = useRef<UndoStep[]>(savedUndo.undo);
  const redoStack = useRef<UndoStep[]>(savedUndo.redo);
  const keepUndoTimer = useRef<number | null>(null);
  const keepUndo = useCallback(() => {
    if (keepUndoTimer.current) window.clearTimeout(keepUndoTimer.current);
    keepUndoTimer.current = window.setTimeout(() => writeUndo(undoKey, undoStack.current, redoStack.current), 300);
  }, [undoKey]);
  const [, bump] = useState(0);
  const drag = useRef<Drag | null>(null);
  const press = useRef<{ at: [number, number]; pick: string | null } | null>(null);
  const lastPointerType = useRef<string>('mouse');
  const [pickMenu, setPickMenu] = useState<{ x: number; y: number; ids: string[] } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [marks, setMarks] = useState<ThumbMark[]>([]);
  const [note, setNote] = useState('');
  const [resendOf, setResendOf] = useState<ThumbInstruction | null>(null);
  const [sending, setSending] = useState(false);
  const [jobs, setJobs] = useState<Record<string, JobState>>({});
  const [showInstr, setShowInstr] = useState<string | null>(null);
  const [listView, setListView] = useState(false);
  // 案を大きく並べて題とメモを書く表示（動画ごとに開いたままを覚える。2026-11-25 本人「同時に並べてサムネとタイトルを決めたい」）
  const lineupKey = patterns ? `thumb-lineup:${patterns.videoId}` : null;
  const [lineup, setLineupState] = useState(() => {
    if (!lineupKey || typeof window === 'undefined') return false;
    try { return window.localStorage.getItem(lineupKey) === '1'; } catch { return false; }
  });
  const setLineup = useCallback((on: boolean) => {
    setLineupState(on);
    if (!lineupKey) return;
    try { if (on) window.localStorage.setItem(lineupKey, '1'); else window.localStorage.removeItem(lineupKey); } catch { /* 覚えられないだけ */ }
  }, [lineupKey]);
  const [exporting, setExporting] = useState(false);
  const [phoneChatOpen, setPhoneChatOpen] = useState(false);
  // 画面の大きさは案を移っても前の大きさから始める（測り直すまでの一瞬に絵が跳ねない）
  const [stageW, setStageW] = useState(() => lastStageW);
  useEffect(() => { lastStageW = stageW; }, [stageW]);
  // 寄る・引く（1 = 枠に収まる大きさ）。Ctrl（Mac は ⌘）＋スクロール、トラックパッドのつまむ動き（11/21 本人）
  const [zoom, setZoom] = useState(1);
  const zoomAnchor = useRef<{ fx: number; fy: number; cx: number; cy: number } | null>(null);
  // 読み直した回数。絵の住所に付けて、手元に控えた前の絵を使わずに取り直す
  const [bust, setBust] = useState(0);
  const [reloading, setReloading] = useState(false);
  const textRef = useRef<HTMLTextAreaElement | null>(null);
  const [finishJob, setFinishJob] = useState<ThumbFinishJob | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  // 出力の形だけを見る（枠の外を切る）。既定は枠の外にはみ出た部品も見えて、つかめる作業台
  const [outputView, setOutputView] = useState(false);
  // 部品・書き込みに付けるコメントの欄（台本の画面と同じく、その場に出る）。part_id が無ければペンの書き込みへのコメント
  const [composer, setComposer] = useState<{ partIds: string[] } | null>(null);
  const patternActions = useRef<ThumbPatternActions | null>(null);
  const setPatternActions = useCallback((a: ThumbPatternActions | null) => { patternActions.current = a; }, []);
  // つかんでいる・描いている間（その間は作業台の広さを止め、コメントのボタンを隠す）
  const [gesture, setGesture] = useState<{ kind: 'pen' | 'part'; board: PartBox | null } | null>(null);
  // 部品の一覧で引っぱって前後を入れ替えている間（下の onLayerPointer*）
  const layerPress = useRef<{ id: string; x: number; y: number; grip: boolean; started: boolean } | null>(null);
  const layerClickBlock = useRef(false);
  const [layerDrag, setLayerDrag] = useState<{ ids: string[]; slot: number } | null>(null);

  // ── ダンの手を見せる（2026-11-24 本人「ダンが何かやる時は必ずその操作を見える化しなさい。動画タイムラインや台本ページと
  //    同じように」）。保存された形が前と違えば、変わった部品を前の形から今の形へ動かし、光と「ダン」の印を出す。
  //    動画のエディターと同じく、本人の画面（選択・拡大・位置）は動かさない。今起きた直しだけを見せる（古い直しは見せない）
  const [activity, setActivity] = useState<DanActivity | null>(null);
  const [danFx, setDanFx] = useState<DanFx | null>(null);
  const [fxNow, setFxNow] = useState(0);
  const showDanChange = useCallback((prev: ThumbDoc | null, next: ThumbDoc, serverNow?: number) => {
    if (!prev || next.saved_by !== 'dan' || typeof document === 'undefined' || document.hidden) return;
    const at = next.saved_at ? Date.parse(next.saved_at) / 1000 : 0;
    const now = serverNow || Date.now() / 1000;
    if (!at || now - at > 8) return;
    const pm = new Map(prev.parts.map((p) => [p.id, p]));
    const nm = new Map(next.parts.map((p) => [p.id, p]));
    const from: Record<string, ThumbPart> = {};
    const ghosts: Array<{ part: ThumbPart; after: string | null }> = [];
    const touched: string[] = [];
    next.parts.forEach((p) => {
      const o = pm.get(p.id);
      if (!o) { from[p.id] = { ...p, opacity: 0 } as ThumbPart; touched.push(p.id); return; }
      if (JSON.stringify(o) === JSON.stringify(p)) return;
      touched.push(p.id);
      from[p.id] = o;
      // 絵が差し替わった（描き直した）時は、前の絵を上に重ねて薄くしていく
      if (o.type === 'image' && p.type === 'image' && o.src !== p.src) ghosts.push({ part: { ...o, id: `${o.id}__was` }, after: p.id });
    });
    prev.parts.forEach((o, i) => {
      if (nm.has(o.id)) return;
      ghosts.push({ part: { ...o, id: `${o.id}__gone` }, after: i > 0 ? prev.parts[i - 1].id : null });
    });
    if (!touched.length && !ghosts.length) return;
    setDanFx({ t0: performance.now(), from, ghosts, touched, gone: ghosts.filter((g) => g.part.id.endsWith('__gone')).map((g) => g.part) });
  }, []);
  useEffect(() => {
    if (!danFx) return;
    let raf = 0;
    const tick = () => {
      const t = performance.now() - danFx.t0;
      setFxNow(t);
      if (t < DAN_FX_MS) raf = requestAnimationFrame(tick);
      else setDanFx(null);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [danFx]);

  // 保存されている形を受け取る。手元に保存前の直しがあれば、それを今の形に重ねる（ダンの直しを消さない）
  const adoptServer = (next: ThumbDoc, force: boolean, serverNow?: number) => {
    const rev = next.rev ?? 0;
    // 保存より前に出した読み直しの返事が後から届くことがある（古い形で画面が戻り、直後の Ctrl+Z や並べ替えが消えた）。
    // rev は保存のたびに増えるので、今持っている形より古い返事は使わない
    if (!force && (rev <= baseRev.current || drag.current)) return;
    const shown = docRef.current;
    let merged = next;
    if (!force && dirty.current && baseDoc.current && shown) merged = mergeThumbDocs(baseDoc.current, shown, next);
    baseRev.current = rev;
    baseDoc.current = next;
    docRef.current = merged;
    setDoc(merged);
    if (!force) showDanChange(shown, { ...merged, saved_by: next.saved_by, saved_at: next.saved_at }, serverNow);
  };

  // ── 読み込み・ダンの直しを読み直す・保存 ──
  const load = useCallback(async (force = false) => {
    try {
      const res = await fetch(api(`${encodeURIComponent(contentId)}/thumbnail`, roomId), { credentials: 'include', cache: 'no-store' });
      if (!res.ok) return;
      const j = (await res.json()) as { doc: unknown; activity?: DanActivity | null; now?: number };
      setActivity(j.activity && j.activity.label ? j.activity : null);
      const next = asThumbDoc(j.doc);
      adoptServer(next, force, j.now);
    } catch { /* 次に読み直す */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, contentId]);

  useEffect(() => {
    // 帯の形から始めた時は、新しい保存があればそれを重ねて受け取る（手元で動かし始めた直しを消さない）
    void load(!startDoc);
    const t = window.setInterval(() => void load(false), 1500);
    return () => window.clearInterval(t);
  }, [load, startDoc]);

  useEffect(() => { void loadThumbFonts(doc); }, [doc]);
  useEffect(() => { if (doc && patterns) rememberThumbDoc(contentId, doc); }, [doc, contentId, patterns]);

  const flush = useCallback(async () => {
    // 保存は「この形はこの rev を元にした」と添えて出す。その間にダンなどが保存していたら断られるので、
    // 今の形を受け取って手元の直しを重ね直し、もう一度出す（古い手元の形で上書きしない）
    for (let attempt = 0; attempt < 4; attempt++) {
      const d = docRef.current;
      if (!d || !dirty.current) return;
      dirty.current = false;
      setSaving('saving');
      try {
        const res = await fetch(api(`${encodeURIComponent(contentId)}/thumbnail`, roomId), {
          method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ doc: d, base_rev: baseRev.current >= 0 ? baseRev.current : null }),
        });
        if (res.status === 409) {
          const j = (await res.json()) as { doc: unknown };
          dirty.current = true;
          adoptServer(asThumbDoc(j.doc), false);
          continue;
        }
        if (!res.ok) throw new Error(await res.text());
        const j = (await res.json()) as { rev: number };
        baseRev.current = j.rev;
        baseDoc.current = { ...d, rev: j.rev, saved_by: 'owner' };
        setDoc((cur) => (cur ? { ...cur, rev: j.rev } : cur));
        setSaving('saved');
        return;
      } catch {
        dirty.current = true;
        setSaving('error');
        return;
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
      undoStack.current.push({ before: clone(prev), after: clone(next) });
      if (undoStack.current.length > UNDO_MAX) undoStack.current.shift();
      redoStack.current = [];
      keepUndo();
    }
    setDoc(next);
    docRef.current = next;
    scheduleSave();
    bump((n) => n + 1);
  }, [scheduleSave, keepUndo]);

  const updatePart = useCallback((id: string, patch: Partial<ThumbPart> | ((p: ThumbPart) => ThumbPart)) => {
    const d = docRef.current;
    if (!d) return;
    commit({ ...d, parts: d.parts.map((p) => (p.id === id ? (typeof patch === 'function' ? patch(p) : ({ ...p, ...patch } as ThumbPart)) : p)) });
  }, [commit]);

  const undo = useCallback(() => {
    const step = undoStack.current.pop();
    if (!step || !docRef.current) return;
    redoStack.current.push(step);
    const next = mergeThumbDocs(step.after, step.before, docRef.current);
    setDoc(next); docRef.current = next; scheduleSave(); keepUndo(); bump((n) => n + 1);
  }, [scheduleSave, keepUndo]);
  const redo = useCallback(() => {
    const step = redoStack.current.pop();
    if (!step || !docRef.current) return;
    undoStack.current.push(step);
    const next = mergeThumbDocs(step.before, step.after, docRef.current);
    setDoc(next); docRef.current = next; scheduleSave(); keepUndo(); bump((n) => n + 1);
  }, [scheduleSave, keepUndo]);

  // ── 画面の大きさ ──
  const stageWrap = useRef<HTMLDivElement | null>(null);
  const viewW = Math.round(stageW * zoom);
  const scale = doc ? viewW / doc.width : 1;
  const hasDoc = !!doc;

  // Ctrl＋スクロールで、指している所を中心に寄る・引く（ページ全体の拡大は止める）
  useEffect(() => {
    const el = stageWrap.current;
    if (!el) return;
    const onWheel = (ev: WheelEvent) => {
      if (!ev.ctrlKey && !ev.metaKey) return;
      ev.preventDefault();
      const svg = svgRef.current;
      if (!svg) return;
      const r = svg.getBoundingClientRect();
      zoomAnchor.current = { fx: (ev.clientX - r.left) / r.width, fy: (ev.clientY - r.top) / r.height, cx: ev.clientX, cy: ev.clientY };
      const d = Math.max(-40, Math.min(40, ev.deltaY));
      setZoom((z) => Math.max(0.25, Math.min(8, z * Math.exp(-d * 0.008))));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [hasDoc]);
  // 寄った後、指していた所が同じ所に来るように送る
  useLayoutEffect(() => {
    const a = zoomAnchor.current;
    const el = stageWrap.current;
    const svg = svgRef.current;
    zoomAnchor.current = null;
    if (!a || !el || !svg) return;
    const r = svg.getBoundingClientRect();
    el.scrollLeft += r.left + a.fx * r.width - a.cx;
    el.scrollTop += r.top + a.fy * r.height - a.cy;
  }, [zoom]);

  const reload = useCallback(async () => {
    setReloading(true);
    try {
      await flush();
      // つながりが別の作品に変わっていれば、その作品を開き直す（11/21 本人「何のための読み直すボタンだよ」）
      if (onReload && (await onReload().catch(() => false))) return;
      setBust((n) => n + 1);
      await load(true);
    } finally {
      setReloading(false);
    }
  }, [flush, load, onReload]);
  // 画面に出す形（絵の住所に読み直しの印を付けるだけ。保存する形は doc のまま）
  const viewDoc = useMemo(() => (doc && bust ? {
    ...doc,
    parts: doc.parts.map((p) => (p.type === 'image' && p.src ? { ...p, src: `${p.src}${p.src.includes('?') ? '&' : '?'}r=${bust}` } : p)),
  } : doc), [doc, bust]);

  // 画面に描く形: ダンの直しが今入ったところなら、前の形から今の形へ動いている途中の形（保存する形は doc のまま）
  const shownDoc = useMemo(() => {
    const d = viewDoc || doc;
    if (!d || !danFx || fxNow >= DAN_MOVE_MS) return d;
    const e = 1 - Math.pow(1 - Math.min(1, fxNow / DAN_MOVE_MS), 3);
    const parts: ThumbPart[] = d.parts.map((p) => {
      const f = danFx.from[p.id];
      if (!f) return p;
      const q = { ...p } as Record<string, unknown>;
      const fr = f as unknown as Record<string, unknown>, to = p as unknown as Record<string, unknown>;
      for (const k of LERP_KEYS) {
        const a = typeof fr[k] === 'number' ? (fr[k] as number) : k === 'opacity' ? 1 : null;
        const b = typeof to[k] === 'number' ? (to[k] as number) : k === 'opacity' ? 1 : null;
        if (a != null && b != null) q[k] = a + (b - a) * e;
      }
      return q as unknown as ThumbPart;
    });
    for (const g of danFx.ghosts) {
      const i = g.after ? parts.findIndex((p) => p.id === g.after) : -1;
      parts.splice(i + 1, 0, { ...g.part, opacity: (g.part.opacity ?? 1) * (1 - e) } as ThumbPart);
    }
    return { ...d, parts };
  }, [viewDoc, doc, danFx, fxNow]);

  const boxOf = useCallback((p: ThumbPart): PartBox => {
    if (p.type === 'image') return { x: p.x, y: p.y, w: p.w, h: p.h };
    if (boxes[p.id]) return boxes[p.id];
    // 隠してあって測れない文字は、行の数と一番長い行から見積もる
    const ls = String(p.text ?? '').split('\n');
    const lh = p.line_height || p.size * 1.25;
    return { x: p.x, y: p.y - p.size, w: p.size * Math.max(1, ...ls.map((l) => l.length)), h: p.size * 1.2 + lh * (ls.length - 1) };
  }, [boxes]);

  // ── 作業台の範囲（2026-11-24 本人「アスペクト比はあくまで表示するウインドウ。はみ出た場所にも自由に置けるように。
  //    出力されるプレビューと切り替えて見れるように」）。サムネの枠の周りに少しと、はみ出た部品の全部が入る範囲。
  //    引きずっている間は広げ直さない（画面の大きさが動いて手元がずれないように）。手を離した時に広げ直す
  const liveBoard = useMemo<PartBox | null>(() => {
    if (!doc) return null;
    if (outputView) return { x: 0, y: 0, w: doc.width, h: doc.height };
    let x0 = -doc.width * BOARD_PAD, y0 = -doc.height * BOARD_PAD, x1 = doc.width * (1 + BOARD_PAD), y1 = doc.height * (1 + BOARD_PAD);
    for (const p of doc.parts) {
      if (p.hidden) continue;
      const b = partBounds(p, boxOf(p), boxes[p.id]);
      if (!Number.isFinite(b.x + b.y + b.w + b.h)) continue;
      x0 = Math.min(x0, b.x - BOARD_PART_PAD); y0 = Math.min(y0, b.y - BOARD_PART_PAD);
      x1 = Math.max(x1, b.x + b.w + BOARD_PART_PAD); y1 = Math.max(y1, b.y + b.h + BOARD_PART_PAD);
    }
    return { x: Math.floor(x0), y: Math.floor(y0), w: Math.ceil(x1 - x0), h: Math.ceil(y1 - y0) };
  }, [doc, boxes, boxOf, outputView]);
  const board = gesture?.board || liveBoard;
  const boardKey = board ? `${board.x},${board.y},${board.w},${board.h}` : '';
  // 画面の大きさ: 作業台の全部が欄に収まる大きさ（stageW はサムネの枠の幅の画素）
  useEffect(() => {
    const el = stageWrap.current;
    if (!el || !doc || !board) return;
    const fit = () => {
      const r = el.getBoundingClientRect();
      // 周りに余白を残す（ふちまである部品の角のつまみが、画面の端で切れずに掴めるように）2026-11-24
      const m = STAGE_MARGIN * 2;
      const k = Math.min((r.width - m) / board.w, compact ? Infinity : (r.height - m) / board.h);
      setStageW(Math.max(200, Math.floor(doc.width * k)));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boardKey, compact, hasDoc, doc?.width]);
  const boardW = board ? Math.round(board.w * scale) : viewW;
  const boardH = board ? Math.round(board.h * scale) : Math.round(viewW * (doc ? doc.height / doc.width : 9 / 16));
  // 作業台の上の点（サムネの画素）を、作業台の左上からの画面の画素に
  const toStagePx = (x: number, y: number): [number, number] => (board ? [(x - board.x) * scale, (y - board.y) * scale] : [x * scale, y * scale]);
  const inBoard = (pt: [number, number]) => !!board && pt[0] >= board.x && pt[1] >= board.y && pt[0] <= board.x + board.w && pt[1] <= board.y + board.h;

  const toSvg = (ev: { clientX: number; clientY: number }): [number, number] => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const m = svg.getScreenCTM();
    if (!m) return [0, 0];
    const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(m.inverse());
    return [pt.x, pt.y];
  };

  // ── 押した所にある部品（2026-11-24 本人「クリックできない素材がある」「関係ない所を押しても選択が外れない」）──
  // SVG の絵は透けた所も四角ごと押されてしまうので、絵の濃さを読んで、実際に見えている一番手前の部品を選ぶ。
  // 固定の部品も選べる（引きずっても動かないだけで、角で大きさは変えられる）。
  const alphaCache = useRef(new Map<string, { w: number; h: number; a: Uint8ClampedArray } | 'loading' | 'fail'>());
  useEffect(() => {
    const d = viewDoc || doc;
    if (!d) return;
    for (const p of d.parts) {
      if (p.type !== 'image' || !p.src || alphaCache.current.has(p.src)) continue;
      const src = p.src;
      alphaCache.current.set(src, 'loading');
      const img = new Image();
      img.onload = () => {
        try {
          const k = Math.min(1, 640 / Math.max(img.naturalWidth || 1, img.naturalHeight || 1));
          const w = Math.max(1, Math.round(img.naturalWidth * k)), h = Math.max(1, Math.round(img.naturalHeight * k));
          const cv = document.createElement('canvas');
          cv.width = w; cv.height = h;
          const cx = cv.getContext('2d', { willReadFrequently: true });
          if (!cx) throw new Error('no ctx');
          cx.drawImage(img, 0, 0, w, h);
          const data = cx.getImageData(0, 0, w, h).data;
          const a = new Uint8ClampedArray(w * h);
          for (let i = 0; i < w * h; i++) a[i] = data[i * 4 + 3];
          alphaCache.current.set(src, { w, h, a });
        } catch {
          alphaCache.current.set(src, 'fail');
        }
      };
      img.onerror = () => alphaCache.current.set(src, 'fail');
      img.src = src;
    }
  }, [viewDoc, doc]);

  // その点が部品の四角（回してあれば回した四角）の中か
  const insideBox = (p: ThumbPart, pt: [number, number]) => {
    const b = boxOf(p);
    const [lx, ly] = p.rotation ? rotatePoint(pt, partCenter(p, boxes[p.id]), -p.rotation) : pt;
    return lx >= b.x && ly >= b.y && lx <= b.x + b.w && ly <= b.y + b.h;
  };

  // その点で実際に見えている所（絵の透けていない所）
  const visibleAt = (p: ThumbPart, i: number, pt: [number, number]) => {
    if (p.type !== 'image') return true;
    const shown = (viewDoc || doc)?.parts[i];
    const al = shown && shown.type === 'image' ? alphaCache.current.get(shown.src) : undefined;
    if (!al || typeof al !== 'object' || p.w <= 0 || p.h <= 0) return true;
    const [lx, ly] = p.rotation ? rotatePoint(pt, partCenter(p, boxes[p.id]), -p.rotation) : pt;
    let u = (lx - p.x) / p.w;
    if (p.flip_x) u = 1 - u;
    const v = (ly - p.y) / p.h;
    const px = Math.floor(u * al.w), py = Math.floor(v * al.h);
    // 押した所のまわり少しを見る（細い線や縁も押しやすく）
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) {
        const x = px + dx, y = py + dy;
        if (x < 0 || y < 0 || x >= al.w || y >= al.h) continue;
        if (al.a[y * al.w + x] >= HIT_ALPHA) return true;
      }
    }
    return false;
  };

  // その点にある部品を手前から順に。visible=true は見えている所だけ（透けた所は下の部品へ通す）
  const partsAt = (pt: [number, number], visible: boolean): ThumbPart[] => {
    if (!doc) return [];
    const out: ThumbPart[] = [];
    for (let i = doc.parts.length - 1; i >= 0; i--) {
      const p = doc.parts[i];
      if (p.hidden || (p.opacity ?? 1) < 0.05) continue;
      if (!insideBox(p, pt)) continue;
      if (visible && !visibleAt(p, i, pt)) continue;
      out.push(p);
    }
    return out;
  };

  const hitPart = (pt: [number, number]): ThumbPart | undefined => partsAt(pt, true)[0];

  // サムネ全体を覆う部品（背景など）。ほかの部品を選んでいる時にここを押すと、まず選択を外すだけにする
  const coversCanvas = (p: ThumbPart) => {
    if (!doc) return false;
    const b = boxOf(p);
    const iw = Math.max(0, Math.min(doc.width, b.x + b.w) - Math.max(0, b.x));
    const ih = Math.max(0, Math.min(doc.height, b.y + b.h) - Math.max(0, b.y));
    return iw * ih >= doc.width * doc.height * 0.9;
  };

  // ── 指・マウスの操作 ──
  const onPointerDown = (ev: React.PointerEvent<SVGSVGElement>) => {
    if (!doc) return;
    lastPointerType.current = ev.pointerType;
    setPickMenu(null);
    if (ev.button !== 0 && ev.pointerType === 'mouse') return;
    const pt = toSvg(ev);
    if (mode === 'pen') {
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      drag.current = { kind: 'pen' };
      setGesture({ kind: 'pen', board: liveBoard });
      setMarks((m) => [...m, { color: PEN_COLOR, width: Math.max(6, 3 / scale), points: [pt] }]);
      return;
    }
    const target = ev.target as Element;
    // コメントの印を押したら、そのコメントを開く（右の欄で光らせ、書き込みを重ねて見せる）
    const pin = target.closest('[data-comment-pin]')?.getAttribute('data-comment-pin');
    if (pin) {
      ev.preventDefault();
      setShowInstr((v) => (v === pin ? null : pin));
      window.setTimeout(() => document.querySelector(`[data-thumb-instruction="${CSS.escape(pin)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 30);
      return;
    }
    const handle = target.closest('[data-handle]')?.getAttribute('data-handle');
    const sel = selected ? doc.parts.find((p) => p.id === selected) : undefined;
    const group = selection.map((id) => doc.parts.find((p) => p.id === id)).filter((p): p is ThumbPart => !!p && !p.hidden);
    const origsOf = (ps: ThumbPart[]) => Object.fromEntries(ps.map((p) => [p.id, clone(p)]));
    const additive = ev.shiftKey || ev.metaKey || ev.ctrlKey;
    if (handle === 'g-rotate' && group.length > 1) {
      // 複数をまとめて回す: 全部を囲む枠の真ん中を中心に、それぞれの位置と向きを一緒に回す
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      const u = unionBox(group.map((p) => partBounds(p, boxOf(p), boxes[p.id])))!;
      const center: [number, number] = [u.x + u.w / 2, u.y + u.h / 2];
      setGesture({ kind: 'part', board: liveBoard });
      drag.current = {
        kind: 'rotate', ids: group.map((p) => p.id), center, startAngle: Math.atan2(pt[1] - center[1], pt[0] - center[0]),
        origs: origsOf(group), before: clone(doc), group: Object.fromEntries(group.map((p) => [p.id, partCenter(p, boxes[p.id])])),
      };
      return;
    }
    if (handle && handle.startsWith('g-') && group.length > 1) {
      // 複数の部品を囲む枠の角: 向かいの角を止めて、全部をまとめて大きさを変える
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      const u = unionBox(group.map((p) => partBounds(p, boxOf(p), boxes[p.id])))!;
      const corners: Record<string, [number, number]> = { 'g-nw': [u.x + u.w, u.y + u.h], 'g-ne': [u.x, u.y + u.h], 'g-sw': [u.x + u.w, u.y], 'g-se': [u.x, u.y] };
      const anchor = corners[handle] || [u.x, u.y];
      setGesture({ kind: 'part', board: liveBoard });
      drag.current = { kind: 'scale', ids: group.map((p) => p.id), anchor, startDist: Math.hypot(pt[0] - anchor[0], pt[1] - anchor[1]) || 1, origs: origsOf(group), before: clone(doc) };
      return;
    }
    if (handle && sel) {
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      const b = boxOf(sel);
      const center = partCenter(sel, boxes[sel.id]);
      if (handle === 'rotate') {
        setGesture({ kind: 'part', board: liveBoard });
        drag.current = { kind: 'rotate', ids: [sel.id], center, startAngle: Math.atan2(pt[1] - center[1], pt[0] - center[0]), origs: origsOf([sel]), before: clone(doc) };
      } else {
        // つかんだ角の向かいの角を止めて、大きさを変える（回してある時は回した角）
        const corners: Record<string, [number, number]> = { nw: [b.x + b.w, b.y + b.h], ne: [b.x, b.y + b.h], sw: [b.x + b.w, b.y], se: [b.x, b.y] };
        const anchorLocal = corners[handle] || [b.x, b.y];
        const anchor = sel.rotation ? rotatePoint(anchorLocal, center, sel.rotation) : anchorLocal;
        setGesture({ kind: 'part', board: liveBoard });
        drag.current = { kind: 'scale', ids: [sel.id], anchor, startDist: Math.hypot(pt[0] - anchor[0], pt[1] - anchor[1]) || 1, origs: origsOf([sel]), before: clone(doc) };
      }
      return;
    }
    // 押せる範囲: 作業台の全部（枠の外にはみ出た部品も選べる）。出力だけを見ている時はサムネの枠の中
    const inCanvas = outputView ? (pt[0] >= 0 && pt[1] >= 0 && pt[0] <= doc.width && pt[1] <= doc.height) : inBoard(pt);
    press.current = null;
    const startMove = (ps: ThumbPart[]) => {
      const movable = ps.filter((p) => !p.locked);
      if (!movable.length) return;
      // ぴたっと揃える先: サムネの左右上下の端と真ん中、ほかの部品の端と真ん中
      const ids = new Set(movable.map((p) => p.id));
      const others = doc.parts.filter((p) => !p.hidden && !ids.has(p.id) && !coversCanvas(p)).map((p) => partBounds(p, boxOf(p), boxes[p.id]));
      const tx = [0, doc.width / 2, doc.width, ...others.flatMap((b) => [b.x, b.x + b.w / 2, b.x + b.w])];
      const ty = [0, doc.height / 2, doc.height, ...others.flatMap((b) => [b.y, b.y + b.h / 2, b.y + b.h])];
      const box0 = unionBox(movable.map((p) => partBounds(p, boxOf(p), boxes[p.id])));
      drag.current = { kind: 'move', ids: movable.map((p) => p.id), start: pt, origs: origsOf(movable), before: clone(doc), box0, tx, ty };
      setGesture({ kind: 'part', board: liveBoard });
    };
    const startMarquee = (base: string[], clickPick: string | null) => {
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      drag.current = { kind: 'marquee', start: pt, base, moved: false, clickPick };
    };
    // Shift・⌘・Ctrl を押しながら押す: その部品を選んでいる物に足す／外す。何も無い所から引くと囲んで足す
    if (additive && inCanvas) {
      const part = hitPart(pt);
      if (part && !(coversCanvas(part) && selection.length && !selection.includes(part.id))) {
        ev.preventDefault();
        (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
        if (selection.includes(part.id)) {
          setSelection((cur) => cur.filter((x) => x !== part.id));
        } else {
          const next = [...selection, part.id];
          setSelection(next);
          startMove(next.map((id) => doc.parts.find((p) => p.id === id)).filter((p): p is ThumbPart => !!p));
        }
        return;
      }
      startMarquee(selection, null);
      return;
    }
    // 選んでいる部品の上（四角の中）を押したら、透けた所でもその部品をつかむ（2026-11-24 本人「集中線が選択後に
    // 移動できない。長押しすると選択が外れる」）。動かさずに離した時だけ、その上に重なって見えている部品へ選び替える。
    // Alt（Mac は ⌥）を押しながらだと、その点に重なっている部品を手前から順に選び替える（下の部品へ届く）。
    if (sel && !sel.hidden && ev.altKey && inCanvas) {
      const stack = partsAt(pt, false);
      if (stack.length) {
        const k = stack.findIndex((p) => p.id === sel.id);
        setSelected(stack[(k + 1) % stack.length].id);
      }
      return;
    }
    // 複数を選んでいる時: そのどれかの上を押したら全部をつかむ。動かさずに離したら、押した所の部品1つだけを選ぶ
    if (group.length > 1 && inCanvas) {
      const member = group.find((p) => insideBox(p, pt));
      if (member) {
        ev.preventDefault();
        (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
        const top = hitPart(pt);
        press.current = { at: [ev.clientX, ev.clientY], pick: top && !coversCanvas(top) ? top.id : member.id };
        startMove(group);
        return;
      }
    }
    if (sel && !sel.hidden && insideBox(sel, pt)) {
      ev.preventDefault();
      (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
      const selIdx = doc.parts.findIndex((p) => p.id === sel.id);
      const above = partsAt(pt, true).find((p) => doc.parts.indexOf(p) > selIdx);
      press.current = { at: [ev.clientX, ev.clientY], pick: above?.id || null };
      startMove([sel]);
      return;
    }
    if (ev.altKey && inCanvas) {
      const stack = partsAt(pt, false);
      if (stack.length) setSelected(stack[0].id);
      return;
    }
    const part = inCanvas ? hitPart(pt) : undefined;
    // 何も無い所・サムネ全体を覆う背景から引くと、囲んだ部品をまとめて選ぶ。動かさずに離した時は、
    // 何かを選んでいれば選択を外し、何も選んでいなければその背景を選ぶ（前と同じ）
    if (!part || coversCanvas(part)) {
      startMarquee([], part && !selection.length ? part.id : null);
      setSelection([]);
      return;
    }
    ev.preventDefault();
    (ev.currentTarget as Element).setPointerCapture(ev.pointerId);
    setSelected(part.id);
    startMove([part]);
  };

  // 右クリック: その点に重なっている部品を全部並べて、どれでも選べる（上にある・下にある・透けている物も）
  const onContextMenu = (ev: React.MouseEvent<SVGSVGElement>) => {
    if (!doc || mode !== 'select') return;
    ev.preventDefault();
    if (lastPointerType.current !== 'mouse') return;   // 指の長押しでは出さない
    const pt = toSvg(ev);
    const stack = partsAt(pt, false);
    const top = hitPart(pt);
    if (top && !selection.includes(top.id) && !coversCanvas(top)) setSelected(top.id);
    setPickMenu({ x: ev.clientX, y: ev.clientY, ids: stack.map((p) => p.id) });
  };

  // 文字を2回押したら、右の欄の文字を打ち直せるようにする
  const onDoubleClick = (ev: React.MouseEvent<SVGSVGElement>) => {
    if (!doc || mode !== 'select') return;
    const part = hitPart(toSvg(ev));
    if (!part || part.type !== 'text') return;
    setSelected(part.id);
    window.setTimeout(() => { textRef.current?.focus(); textRef.current?.select(); }, 60);
  };

  // サムネの外（まわりの余白）を押したら選択を外す
  const onStagePointerDown = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (mode !== 'select') return;
    const svg = svgRef.current;
    if (svg && svg.contains(ev.target as Node)) return;
    setSelected(null);
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
    if (dr.kind === 'marquee') {
      const m = { x: Math.min(dr.start[0], pt[0]), y: Math.min(dr.start[1], pt[1]), w: Math.abs(pt[0] - dr.start[0]), h: Math.abs(pt[1] - dr.start[1]) };
      if (!dr.moved && Math.max(m.w, m.h) * scale < 4) return;
      dr.moved = true;
      setMarquee(m);
      // 囲みに少しでも掛かった部品（サムネ全体を覆う背景は除く）
      const hits = d.parts.filter((p) => !p.hidden && !coversCanvas(p)).filter((p) => {
        const b = partBounds(p, boxOf(p), boxes[p.id]);
        return b.x < m.x + m.w && b.x + b.w > m.x && b.y < m.y + m.h && b.y + b.h > m.y;
      }).map((p) => p.id);
      setSelection([...dr.base, ...hits.filter((id) => !dr.base.includes(id))]);
      return;
    }
    const changed: Record<string, ThumbPart> = {};
    // 動かす量: Shift で横か縦だけ。ほかの部品・サムネの端や真ん中に近づくと揃えて止める（⌘/Ctrl を押している間は揃えない）
    let mdx = 0, mdy = 0;
    if (dr.kind === 'move') {
      mdx = pt[0] - dr.start[0]; mdy = pt[1] - dr.start[1];
      if (ev.shiftKey) { if (Math.abs(mdx) > Math.abs(mdy)) mdy = 0; else mdx = 0; }
      const lines: Array<{ x?: number; y?: number }> = [];
      if (dr.box0 && !(ev.metaKey || ev.ctrlKey)) {
        const thr = 6 / scale;
        const b = dr.box0;
        const fit = (edges: number[], targets: number[]) => {
          let best: { d: number; at: number } | null = null;
          for (const e of edges) for (const t of targets) { const d = t - e; if (Math.abs(d) < thr && (!best || Math.abs(d) < Math.abs(best.d))) best = { d, at: t }; }
          return best;
        };
        const fx = !(ev.shiftKey && mdx === 0) ? fit([b.x + mdx, b.x + b.w / 2 + mdx, b.x + b.w + mdx], dr.tx) : null;
        const fy = !(ev.shiftKey && mdy === 0) ? fit([b.y + mdy, b.y + b.h / 2 + mdy, b.y + b.h + mdy], dr.ty) : null;
        if (fx) { mdx += fx.d; lines.push({ x: fx.at }); }
        if (fy) { mdy += fy.d; lines.push({ y: fy.at }); }
      }
      setGuides(lines);
    }
    for (const id of dr.ids) {
      const o = dr.origs[id];
      if (!o) continue;
      if (dr.kind === 'move') {
        changed[id] = { ...o, x: o.x + mdx, y: o.y + mdy } as ThumbPart;
      } else if (dr.kind === 'rotate' && dr.group) {
        const a = Math.atan2(pt[1] - dr.center[1], pt[0] - dr.center[0]);
        let delta = ((a - dr.startAngle) * 180) / Math.PI;
        if (!ev.shiftKey) for (const snap of [-180, -90, 0, 90, 180]) if (Math.abs(delta - snap) < 3) delta = snap;
        delta = Math.round(delta * 10) / 10;
        const c0 = dr.group[id];
        const c1 = rotatePoint(c0, dr.center, delta);
        let deg = (o.rotation || 0) + delta;
        deg = ((deg + 540) % 360) - 180;
        changed[id] = { ...o, x: o.x + c1[0] - c0[0], y: o.y + c1[1] - c0[1], rotation: Math.round(deg * 10) / 10 } as ThumbPart;
      } else if (dr.kind === 'scale') {
        const k = Math.max(0.05, Math.hypot(pt[0] - dr.anchor[0], pt[1] - dr.anchor[1]) / dr.startDist);
        changed[id] = scalePart(o, dr.anchor, k);
      } else {
        const a = Math.atan2(pt[1] - dr.center[1], pt[0] - dr.center[0]);
        let deg = (o.rotation || 0) + ((a - dr.startAngle) * 180) / Math.PI;
        deg = Math.round(deg * 10) / 10;
        if (!ev.shiftKey) for (const snap of [-180, -90, 0, 90, 180]) if (Math.abs(deg - snap) < 3) deg = snap;
        changed[id] = { ...o, rotation: deg };
      }
    }
    const next = { ...d, parts: d.parts.map((p) => changed[p.id] || p) };
    docRef.current = next;
    setDoc(next);
  };

  const onPointerUp = (ev?: React.PointerEvent<SVGSVGElement>) => {
    const dr = drag.current;
    drag.current = null;
    setGesture(null);
    setGuides([]);
    const pr = press.current;
    press.current = null;
    if (dr && dr.kind === 'marquee') {
      setMarquee(null);
      if (!dr.moved && dr.clickPick) setSelected(dr.clickPick);
      return;
    }
    // 動かさずに離した（クリック）: 選んでいる部品の上に重なって見えている部品があれば、そちらを選ぶ
    if (pr && pr.pick && ev && Math.hypot(ev.clientX - pr.at[0], ev.clientY - pr.at[1]) < 4) {
      if (dr && dr.kind !== 'pen' && docRef.current) {
        const d = docRef.current;
        const back = { ...d, parts: d.parts.map((p) => dr.origs[p.id] || p) };
        docRef.current = back; setDoc(back);
      }
      setSelected(pr.pick);
      return;
    }
    if (!dr || dr.kind === 'pen' || !docRef.current) return;
    const moved = docRef.current.parts.some((p) => dr.origs[p.id] && JSON.stringify(p) !== JSON.stringify(dr.origs[p.id]));
    if (moved) commit(docRef.current, dr.before);
  };

  // ── キー ──
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      // 字を打つ欄の中だけは、その欄の操作に任せる（つまみ・色・ボタンの上では効かせる）
      const el = ev.target as HTMLElement | null;
      if (isTextField(el)) return;
      const mod = ev.ctrlKey || ev.metaKey;
      if (mod && ev.key.toLowerCase() === 'z') { ev.preventDefault(); if (ev.shiftKey) redo(); else undo(); return; }
      if (mod && ev.key.toLowerCase() === 'y') { ev.preventDefault(); redo(); return; }
      const d = docRef.current;
      const sels = d ? selection.map((id) => d.parts.find((p) => p.id === id)).filter((p): p is ThumbPart => !!p) : [];
      if (ev.key === 'Escape' && composer) { setComposer(null); return; }
      // Ctrl+A: 出ている部品を全部選ぶ
      if (mod && ev.key.toLowerCase() === 'a' && d && mode === 'select') {
        ev.preventDefault();
        setSelection(d.parts.filter((p) => !p.hidden).map((p) => p.id));
        return;
      }
      // Ctrl+D: 部品を選んでいればその部品、選んでいなければ今の案を複製する（2026-11-24 本人「複製はCtrl+Dと…だけで良い」）
      if (mod && ev.key.toLowerCase() === 'd' && !sels.length) {
        if (patternActions.current) { ev.preventDefault(); patternActions.current.duplicateCurrent(); }
        return;
      }
      if (!sels.length || !d) return;
      if (mod && ev.key.toLowerCase() === 'd') { ev.preventDefault(); duplicate(sels); return; }
      // 前へ・後ろへ（Figma・Canva と同じ。Shift で一番前・一番後ろ）
      if (mod && (ev.key === ']' || ev.key === '}' || ev.key === '[' || ev.key === '{')) {
        ev.preventDefault();
        const fwd = ev.key === ']' || ev.key === '}';
        move(sels.map((p) => p.id), ev.shiftKey ? (fwd ? 'front' : 'back') : (fwd ? 'up' : 'down'));
        return;
      }
      if (ev.key === 'Delete' || ev.key === 'Backspace') { ev.preventDefault(); remove(sels.map((p) => p.id)); return; }
      if (ev.key === 'Escape') { setSelection([]); return; }
      const step = ev.shiftKey ? 10 : 1;
      const mv: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (mv[ev.key]) {
        ev.preventDefault();
        const ids = new Set(sels.map((p) => p.id));
        commit({ ...d, parts: d.parts.map((p) => (ids.has(p.id) ? { ...p, x: p.x + mv[ev.key][0], y: p.y + mv[ev.key][1] } as ThumbPart : p)) });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const remove = (ids: string | string[]) => {
    const d = docRef.current;
    if (!d) return;
    const gone = new Set(Array.isArray(ids) ? ids : [ids]);
    commit({ ...d, parts: d.parts.filter((p) => !gone.has(p.id)) });
    setSelection([]);
  };
  // 複製: 選んでいる部品の全部を、それぞれ元のすぐ手前に写す。写した方を選ぶ
  const duplicate = (ps: ThumbPart | ThumbPart[]) => {
    const d = docRef.current;
    if (!d) return;
    const list = Array.isArray(ps) ? ps : [ps];
    const parts = [...d.parts];
    const made: string[] = [];
    for (const p of list) {
      const copy = { ...clone(p), id: newPartId(p.type === 'text' ? 't' : 'i'), name: p.name ? `${p.name}（写し）` : undefined, x: p.x + 30, y: p.y + 30, locked: false } as ThumbPart;
      const i = parts.findIndex((q) => q.id === p.id);
      parts.splice(i + 1, 0, copy);
      made.push(copy.id);
    }
    commit({ ...d, parts });
    setSelection(made);
  };
  // コピー・貼り付け（ほかの案に貼ると同じ位置、同じ案に貼ると少しずらす）
  const pasteCount = useRef(0);
  const copyParts = (ps: ThumbPart[], dt?: DataTransfer | null) => {
    const raw = JSON.stringify(ps.map((p) => clone(p)));
    try { window.localStorage.setItem(CLIP_KEY, raw); } catch { /* 入らなくても OS 側には載る */ }
    if (dt) dt.setData('text/plain', CLIP_MARK + raw);
    else void navigator.clipboard?.writeText(CLIP_MARK + raw).catch(() => undefined);
    pasteCount.current = 0;
  };
  const pasteParts = (ps: ThumbPart[] | null) => {
    const d = docRef.current;
    if (!d || !ps || !ps.length) return;
    const here = ps.some((p) => d.parts.some((q) => q.id === p.id));
    const off = here ? 30 * ++pasteCount.current : 0;
    const made = ps.map((p) => ({ ...clone(p), id: newPartId(p.type === 'text' ? 't' : 'i'), x: p.x + off, y: p.y + off, finish: undefined } as ThumbPart));
    commit({ ...d, parts: [...d.parts, ...made] });
    setSelection(made.map((p) => p.id));
    setMode('select');
  };
  // 揃える・等間隔に並べる（複数を選んだ時）。見えている範囲（回してあれば回した範囲）で揃える
  const arrange = (how: 'left' | 'hcenter' | 'right' | 'top' | 'vcenter' | 'bottom' | 'hspace' | 'vspace') => {
    const d = docRef.current;
    if (!d) return;
    const ps = selection.map((id) => d.parts.find((p) => p.id === id)).filter((p): p is ThumbPart => !!p && !p.locked);
    if (ps.length < 2) return;
    const bs = new Map(ps.map((p) => [p.id, partBounds(p, boxOf(p), boxes[p.id])]));
    const u = unionBox([...bs.values()])!;
    const delta = new Map<string, [number, number]>();
    if (how === 'hspace' || how === 'vspace') {
      const hz = how === 'hspace';
      const sorted = [...ps].sort((a, b) => (hz ? bs.get(a.id)!.x - bs.get(b.id)!.x : bs.get(a.id)!.y - bs.get(b.id)!.y));
      const total = sorted.reduce((n, p) => n + (hz ? bs.get(p.id)!.w : bs.get(p.id)!.h), 0);
      const gap = ((hz ? u.w : u.h) - total) / (sorted.length - 1);
      let at = hz ? u.x : u.y;
      for (const p of sorted) {
        const b = bs.get(p.id)!;
        delta.set(p.id, hz ? [at - b.x, 0] : [0, at - b.y]);
        at += (hz ? b.w : b.h) + gap;
      }
    } else {
      for (const p of ps) {
        const b = bs.get(p.id)!;
        const dx = how === 'left' ? u.x - b.x : how === 'right' ? u.x + u.w - (b.x + b.w) : how === 'hcenter' ? u.x + u.w / 2 - (b.x + b.w / 2) : 0;
        const dy = how === 'top' ? u.y - b.y : how === 'bottom' ? u.y + u.h - (b.y + b.h) : how === 'vcenter' ? u.y + u.h / 2 - (b.y + b.h / 2) : 0;
        delta.set(p.id, [dx, dy]);
      }
    }
    commit({ ...d, parts: d.parts.map((p) => { const m = delta.get(p.id); return m ? { ...p, x: p.x + m[0], y: p.y + m[1] } as ThumbPart : p; }) });
  };
  const updateParts = (ids: string[], patch: Partial<ThumbPart>) => {
    const d = docRef.current;
    if (!d) return;
    const set = new Set(ids);
    commit({ ...d, parts: d.parts.map((p) => (set.has(p.id) ? ({ ...p, ...patch } as ThumbPart) : p)) });
  };
  const move = (ids: string | string[], dir: 'up' | 'down' | 'front' | 'back') => {
    const d = docRef.current;
    if (!d) return;
    const parts = stepParts(d.parts, Array.isArray(ids) ? ids : [ids], dir);
    if (parts.every((p, i) => p === d.parts[i])) return;
    commit({ ...d, parts });
  };
  // 部品の一覧で引っぱって並べ替える（slot は一覧の何番目の前か）
  const reorderTo = (ids: string[], slot: number) => {
    const d = docRef.current;
    if (!d) return;
    const parts = reorderParts(d.parts, ids, slot);
    if (parts.every((p, i) => p === d.parts[i])) return;
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

  // ── 画像を足す（貼り付け・落とす・「画像」ボタン）2026-11-23 約束「画像も貼り付けやドラッグで足せる形に」──
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(0);
  const addImageFiles = async (files: File[], at?: [number, number]) => {
    const imgs = files.filter((f) => f.type.startsWith('image/'));
    if (!imgs.length) return;
    setUploading((n) => n + imgs.length);
    for (const f of imgs) {
      try {
        const fd = new FormData();
        fd.append('file', f, f.name || 'image.png');
        const res = await fetch(api(`${encodeURIComponent(contentId)}/thumbnail/image`, roomId), { method: 'POST', credentials: 'include', body: fd });
        if (!res.ok) throw new Error(await res.text());
        const j = (await res.json()) as { asset_id: string; src: string; width?: number; height?: number };
        const d = docRef.current;
        if (!d) continue;
        const iw = j.width || 800, ih = j.height || 600;
        const k = Math.min(1, (d.width * 0.6) / iw, (d.height * 0.6) / ih);
        const w = iw * k, h = ih * k;
        const [cx, cy] = at || [d.width / 2, d.height / 2];
        const part: ThumbPart = {
          id: newPartId('i'), type: 'image', name: (f.name || '画像').replace(/\.[a-z0-9]+$/i, '').slice(0, 30) || '画像',
          src: j.src, asset_id: j.asset_id, x: cx - w / 2, y: cy - h / 2, w, h,
        };
        commit({ ...d, parts: [...d.parts, part] });
        setSelected(part.id);
        setMode('select');
      } catch (e) {
        toast.error('画像を足せませんでした', { description: String((e as Error).message || e).slice(0, 160) });
      } finally {
        setUploading((n) => Math.max(0, n - 1));
      }
    }
  };
  useEffect(() => {
    const onPaste = (ev: ClipboardEvent) => {
      const el = ev.target as HTMLElement | null;
      if (isTextField(el)) return;
      const clip = readClip(ev.clipboardData?.getData('text/plain') || '');
      if (clip) { ev.preventDefault(); pasteParts(clip); return; }
      const files = Array.from(ev.clipboardData?.files || []).filter((f) => f.type.startsWith('image/'));
      if (!files.length) return;
      ev.preventDefault();
      void addImageFiles(files);
    };
    // コピー・切り取り: 選んでいる部品を（字を打つ欄の外で）
    const onCopy = (ev: ClipboardEvent, cut: boolean) => {
      if (isTextField(ev.target as HTMLElement | null) || mode !== 'select') return;
      const d = docRef.current;
      const ps = d ? d.parts.filter((p) => selection.includes(p.id)) : [];
      if (!ps.length) return;
      ev.preventDefault();
      copyParts(ps, ev.clipboardData);
      if (cut) remove(ps.map((p) => p.id));
    };
    const c1 = (e: ClipboardEvent) => onCopy(e, false), c2 = (e: ClipboardEvent) => onCopy(e, true);
    window.addEventListener('paste', onPaste);
    window.addEventListener('copy', c1);
    window.addEventListener('cut', c2);
    return () => { window.removeEventListener('paste', onPaste); window.removeEventListener('copy', c1); window.removeEventListener('cut', c2); };
  });
  const onStageDrop = (ev: React.DragEvent) => {
    const files = Array.from(ev.dataTransfer?.files || []);
    if (!files.some((f) => f.type.startsWith('image/'))) return;
    ev.preventDefault();
    const pt = toSvg(ev);
    const d = docRef.current;
    const inside = d && pt[0] >= 0 && pt[1] >= 0 && pt[0] <= d.width && pt[1] <= d.height;
    void addImageFiles(files, inside ? pt : undefined);
  };

  // ── コメントを付けて送る（部品を選んでコメント／ペンで書き込んでコメント）──
  // 2026-11-24 本人「サムネに直接書き込んだり修正点を指示して修正することができるように。要素を選択したらコメントできるように。
  // 台本エディターみたいに」。コメントはその場に印として残り、ダンが直した結果がその下に出る
  const marksBounds = (ms: ThumbMark[]): PartBox | null => {
    const xs = ms.flatMap((m) => m.points.map((p) => p[0]));
    const ys = ms.flatMap((m) => m.points.map((p) => p[1]));
    if (!xs.length) return null;
    return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
  };
  const sendMarks = async () => {
    const d = docRef.current;
    const text = note.trim();
    const targets = d && composer ? composer.partIds.map((id) => d.parts.find((p) => p.id === id)).filter((p): p is ThumbPart => !!p) : [];
    const target = targets[0];
    if (!d || (!marks.length && !text)) return;
    if (!text && target && !marks.length) return;
    setSending(true);
    try {
      const pad = 12;
      // ダンに渡す絵: ペンの線（赤）と、コメントを付けた部品の枠（水色。複数なら1つずつ）
      const tbs = targets.map((p) => partBounds(p, boxOf(p), boxes[p.id]));
      const tb = unionBox(tbs);
      const targetMarks: ThumbMark[] = tbs.map((b) => ({
        color: TARGET_COLOR, width: Math.max(5, 3 / scale),
        points: [[b.x, b.y], [b.x + b.w, b.y], [b.x + b.w, b.y + b.h], [b.x, b.y + b.h], [b.x, b.y]],
      }));
      const mb = marksBounds(marks);
      const area = mb ? { x: mb.x - pad, y: mb.y - pad, w: mb.w + pad * 2, h: mb.h + pad * 2 } : tb;
      const box = area ? [area.x, area.y, area.w, area.h] : [];
      const hit = (b: PartBox) => box.length === 4 && b.x < box[0] + box[2] && b.x + b.w > box[0] && b.y < box[1] + box[3] && b.y + b.h > box[1];
      const under = mb ? [...d.parts].reverse().filter((p) => !p.hidden && hit(boxOf(p))).map((p) => `${p.id}（${partLabel(p)}）`) : [];
      const sent = [...marks, ...targetMarks];
      const anchor: [number, number] | null = mb ? [mb.x + mb.w, mb.y] : tb ? [tb.x + tb.w, tb.y] : null;
      const id = `ti_${Date.now().toString(36)}`;
      const res = await fetch(`/api/v1/production-assets/contents/${encodeURIComponent(contentId)}/instructions`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          room_id: roomId,
          annotation: {
            id, kind: 'thumb_marks', note: text,
            data: {
              marks: sent, box, parts_under: under,
              target: targets.length ? (targets.length > 1 ? `${targets.length}個の部品（まとめて選んだ）: ` : '') + targets.map((p) => partDetail(p, boxOf(p))).join('、') : null,
              selected: targets.length ? targets.map((p) => `${p.id}（${partLabel(p)}）`).join('、') : null,
              job_id: resendOf?.job_id,
            },
          },
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const j = (await res.json()) as { job_id: string };
      const instr: ThumbInstruction = { id, note: text, marks: sent, job_id: j.job_id, created_at: new Date().toISOString(), part_id: target?.id || null, part_ids: targets.length > 1 ? targets.map((p) => p.id) : null, anchor };
      const cur = docRef.current || d;
      const list = (cur.instructions || []).filter((x) => x.id !== resendOf?.id);
      commit({ ...cur, instructions: [...list, instr] });
      setJobs((s) => ({ ...s, [j.job_id]: { job_id: j.job_id, state: 'queued', label: '順番待ち', active: true } }));
      setMarks([]); setNote(''); setResendOf(null); setComposer(null);
      if (mode === 'pen') setMode('select');
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
  const selParts = doc ? selection.map((id) => doc.parts.find((p) => p.id === id)).filter((p): p is ThumbPart => !!p) : [];
  const multi = selParts.length > 1 ? selParts : null;
  const shownMarks = mode === 'pen' ? marks : showInstr ? instructions.find((i) => i.id === showInstr)?.marks : undefined;

  // ── 選んだ部品の枠と角 ──
  const handleR = (compact ? 13 : 7) / scale;
  const overlay = sel && mode === 'select' && !sel.hidden ? (() => {
    const b = boxOf(sel);
    const [cx, cy] = partCenter(sel, boxes[sel.id]);
    const sw = 1.5 / scale;
    const roomAbove = (b.y - (board?.y ?? 0)) * scale + STAGE_MARGIN;
    const rotY = roomAbove >= 28 + handleR * scale ? b.y - 28 / scale : b.y + 28 / scale;
    return (
      <g transform={sel.rotation ? `rotate(${sel.rotation} ${cx} ${cy})` : undefined}>
        <rect x={b.x} y={b.y} width={b.w} height={b.h} fill="none" stroke="#38bdf8" strokeWidth={sw * 1.5} strokeDasharray={`${6 / scale} ${4 / scale}`} pointerEvents="none" />
        {/* 固定の部品にも角のつまみを出す（引きずっても動かないだけ）。上に余白が無い時は回すつまみを内側に */}
        <line x1={b.x + b.w / 2} y1={b.y} x2={b.x + b.w / 2} y2={rotY} stroke="#38bdf8" strokeWidth={sw} pointerEvents="none" />
        <circle data-handle="rotate" cx={b.x + b.w / 2} cy={rotY} r={handleR} fill="#fff" stroke="#38bdf8" strokeWidth={sw} style={{ cursor: 'grab' }} />
        {([['nw', b.x, b.y], ['ne', b.x + b.w, b.y], ['sw', b.x, b.y + b.h], ['se', b.x + b.w, b.y + b.h]] as const).map(([k, x, y]) => (
          <rect key={k} data-handle={k} x={x - handleR} y={y - handleR} width={handleR * 2} height={handleR * 2} fill="#fff" stroke="#38bdf8" strokeWidth={sw}
            style={{ cursor: k === 'nw' || k === 'se' ? 'nwse-resize' : 'nesw-resize' }} />
        ))}
      </g>
    );
  })() : multi && mode === 'select' ? (() => {
    // 複数を選んだ時: 1つずつの点線の枠と、全部を囲む枠の角（引くと全部をまとめて大きさを変える）
    const shown = multi.filter((p) => !p.hidden);
    const u = unionBox(shown.map((p) => partBounds(p, boxOf(p), boxes[p.id])));
    const sw = 1.5 / scale;
    return (
      <g data-thumb-multi-overlay>
        {shown.map((p) => {
          const b = boxOf(p);
          const [cx, cy] = partCenter(p, boxes[p.id]);
          return <rect key={p.id} x={b.x} y={b.y} width={b.w} height={b.h} fill="none" stroke="#38bdf8" strokeWidth={sw} strokeDasharray={`${6 / scale} ${4 / scale}`}
            transform={p.rotation ? `rotate(${p.rotation} ${cx} ${cy})` : undefined} pointerEvents="none" />;
        })}
        {u ? (
          <>
            <rect x={u.x} y={u.y} width={u.w} height={u.h} fill="none" stroke="#38bdf8" strokeWidth={sw * 1.5} pointerEvents="none" />
            {(() => {
              const roomAbove = (u.y - (board?.y ?? 0)) * scale + STAGE_MARGIN;
              const ry = roomAbove >= 28 + handleR * scale ? u.y - 28 / scale : u.y + 28 / scale;
              return (
                <>
                  <line x1={u.x + u.w / 2} y1={u.y} x2={u.x + u.w / 2} y2={ry} stroke="#38bdf8" strokeWidth={sw} pointerEvents="none" />
                  <circle data-handle="g-rotate" cx={u.x + u.w / 2} cy={ry} r={handleR} fill="#fff" stroke="#38bdf8" strokeWidth={sw} style={{ cursor: 'grab' }} />
                </>
              );
            })()}
            {([['g-nw', u.x, u.y], ['g-ne', u.x + u.w, u.y], ['g-sw', u.x, u.y + u.h], ['g-se', u.x + u.w, u.y + u.h]] as const).map(([k, x, y]) => (
              <rect key={k} data-handle={k} x={x - handleR} y={y - handleR} width={handleR * 2} height={handleR * 2} fill="#fff" stroke="#38bdf8" strokeWidth={sw}
                style={{ cursor: k === 'g-nw' || k === 'g-se' ? 'nwse-resize' : 'nesw-resize' }} />
            ))}
          </>
        ) : null}
      </g>
    );
  })() : null;
  const guideEl = guides.length && doc ? (
    <g pointerEvents="none" data-thumb-guides>
      {guides.map((g, i) => (g.x != null
        ? <line key={i} x1={g.x} x2={g.x} y1={(board?.y ?? 0)} y2={(board ? board.y + board.h : doc.height)} stroke="#f43f5e" strokeWidth={1 / scale} />
        : <line key={i} y1={g.y} y2={g.y} x1={(board?.x ?? 0)} x2={(board ? board.x + board.w : doc.width)} stroke="#f43f5e" strokeWidth={1 / scale} />))}
    </g>
  ) : null;
  // 囲んで選んでいる間の四角
  const marqueeEl = marquee ? (
    <rect x={marquee.x} y={marquee.y} width={marquee.w} height={marquee.h} fill="rgba(56,189,248,0.12)" stroke="#38bdf8"
      strokeWidth={1 / scale} pointerEvents="none" data-thumb-marquee />
  ) : null;

  // ── ダンが触っている所: 今入った直し（光が残る間）→ thumb.py が知らせた作業中の部品 → 動いているコメントの直し ──
  const danTarget: { ids: string[]; box: PartBox | null; label: string; working: boolean } | null = (() => {
    if (!doc) return null;
    const known = (ids: string[]) => ids.filter((id) => doc.parts.some((p) => p.id === id && !p.hidden));
    const boxIds = (ids: string[]) => unionBox(ids.map((id) => doc.parts.find((p) => p.id === id)!).map((p) => partBounds(p, boxOf(p), boxes[p.id])));
    if (danFx && fxNow < DAN_FX_MS) {
      const ids = known(danFx.touched);
      const b = ids.length ? boxIds(ids) : unionBox(danFx.gone.map((p) => partBounds(p, boxOf(p), boxes[p.id])));
      if (b) return { ids, box: b, label: activity?.label || (danFx.gone.length && !ids.length ? '消しました' : '直しました'), working: false };
    }
    if (activity) {
      const ids = known(activity.parts || []);
      return { ids, box: ids.length ? boxIds(ids) : null, label: activity.label, working: true };
    }
    for (const ins of [...instructions].reverse()) {
      const st = ins.job_id ? jobs[ins.job_id] : undefined;
      if (!st || !st.active) continue;
      const ids = known(ins.part_ids && ins.part_ids.length ? ins.part_ids : ins.part_id ? [ins.part_id] : []);
      const pens = ins.marks.filter((m) => m.color !== TARGET_COLOR);
      const b = ids.length ? boxIds(ids) : marksBounds(pens.length ? pens : ins.marks);
      return { ids, box: b, label: st.progress || st.label || '直しています', working: true };
    }
    return null;
  })();
  const fade = danFx && !danTarget?.working ? Math.max(0, Math.min(1, (DAN_FX_MS - fxNow) / 600)) : 1;
  const danMarks = danTarget && danTarget.box ? (
    <g pointerEvents="none" data-dan-touch={danTarget.working ? 'working' : 'done'} opacity={fade}>
      {(danTarget.ids.length ? danTarget.ids.map((id) => doc!.parts.find((p) => p.id === id)!).map((p) => ({ id: p.id, b: boxOf(p), p })) : [{ id: 'box', b: danTarget.box, p: null as ThumbPart | null }]).map(({ id, b, p }) => {
        const [cx, cy] = p ? partCenter(p, boxes[p.id]) : [0, 0];
        return (
          <rect key={id} x={b.x} y={b.y} width={b.w} height={b.h} fill="rgba(56,189,248,0.08)" stroke="#38bdf8" strokeWidth={3 / scale}
            transform={p?.rotation ? `rotate(${p.rotation} ${cx} ${cy})` : undefined}
            style={{ filter: 'drop-shadow(0 0 6px rgba(56,189,248,.9))' }}>
            {danTarget.working ? <animate attributeName="stroke-opacity" values="1;0.35;1" dur="1.4s" repeatCount="indefinite" /> : null}
          </rect>
        );
      })}
    </g>
  ) : null;
  // 「ダン」の手（動画のエディターと同じ形）。触っている所の真ん中を指す
  const danHandAt: [number, number] | null = danTarget?.box ? toStagePx(danTarget.box.x + danTarget.box.w / 2, danTarget.box.y + danTarget.box.h / 2) : null;

  // コメントの印（番号の丸）。押すとそのコメントを開く。大きさは寄っても引いても画面の上で同じ
  const instrAnchor = (ins: ThumbInstruction): [number, number] | null => {
    if (ins.anchor) return ins.anchor;
    const pens = ins.marks.filter((m) => m.color !== TARGET_COLOR);
    const mb = marksBounds(pens.length ? pens : ins.marks);
    return mb ? [mb.x + mb.w, mb.y] : null;
  };
  const pins = (doc?.instructions || []).map((ins, k) => {
    const a = instrAnchor(ins);
    if (!a) return null;
    const st = ins.job_id ? jobs[ins.job_id] : undefined;
    const active = st ? st.active : true;
    const on = showInstr === ins.id;
    return (
      <g key={ins.id} data-comment-pin={ins.id} transform={`translate(${a[0]} ${a[1]}) scale(${1 / scale})`} style={{ cursor: 'pointer' }}>
        <path d="M0 0 L3 -14 L14 -3 Z" fill={active ? '#0ea5e9' : '#10b981'} stroke="#fff" strokeWidth={1.5} strokeLinejoin="round" />
        <circle cx={14} cy={-14} r={13} fill={active ? '#0ea5e9' : '#10b981'} stroke="#fff" strokeWidth={on ? 3 : 2} />
        <text x={14} y={-14} textAnchor="middle" dominantBaseline="central" fontSize={13} fontWeight={700} fill="#fff" style={{ userSelect: 'none' }}>{k + 1}</text>
      </g>
    );
  });

  const partProps = useCallback((p: ThumbPart) => ({
    style: { cursor: mode === 'pen' ? 'crosshair' : p.locked ? 'default' : 'move', pointerEvents: mode === 'pen' ? 'none' : 'auto' },
  }), [mode]);

  // ── 横の会話に添える（chatLink の時だけ）──
  const putAttach = useChatAttachStore((s) => s.put);
  const dropAttach = useChatAttachStore((s) => s.drop);
  const attached = useChatAttachments(chatLink?.projectId || '');
  const lastPartKey = useRef('');
  const lastCtx = useRef<string | null>(null);
  const linkRef = useRef(chatLink);
  useEffect(() => { linkRef.current = chatLink; }, [chatLink]);
  const selPart = selParts[0];
  const selBox = selParts.length ? unionBox(selParts.map((p) => boxOf(p))) : null;
  const where = `サムネ「${title}」（作品 content_id=${contentId}、部屋 ${roomId}）`;
  const partText = selParts.map((p) => partDetail(p, boxOf(p))).join('、');
  useEffect(() => {
    const link = linkRef.current;
    if (!link) return;
    if (lastCtx.current !== partText) { lastCtx.current = partText; link.onContext?.(partText); }
    const key = selPart && mode === 'select' ? `${selection.join(',')}|${partText}` : '';
    if (key === lastPartKey.current) return;
    lastPartKey.current = key;
    if (!key || !selPart || !selBox) { dropAttach(link.projectId, 'thumb-part'); return; }
    const box = [selBox.x, selBox.y, selBox.w, selBox.h];
    const ids = [...selection];
    const many = ids.length > 1;
    putAttach(link.projectId, {
      key: 'thumb-part',
      label: many ? `選んだ部品：${ids.length}個` : `選んだ部品：${selPart.type === 'text' ? `文字「${selPart.text.replace(/\n/g, ' ').slice(0, 14)}」` : partLabel(selPart)}`,
      preview: !many && selPart.type === 'image' ? selPart.src : undefined,
      detail: many
        ? `- みきさんがまとめて選んだ部品${ids.length}個（「これ」「これら」はこれ）: ${where} の ${partText}。添付の絵の赤い枠がこれらを囲む範囲。`
        : `- みきさんが選んだ部品（「これ」「この文字」「この絵」はこれ）: ${where} の ${partText}。添付の絵の赤い枠がこの部品。`,
      upload: () => link.snapshot({ box }),
      // 札の×は部品の選択も外す（枠が消え、ダンにも選んだ部品を渡さない。もう一度押せばまた添わる）2026-11-22
      onRemove: () => setSelection((cur) => cur.filter((x) => !ids.includes(x))),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partText, selection.join(','), mode, where, putAttach, dropAttach]);

  const marksKey = useMemo(() => marks.map((m) => m.points.length).join(','), [marks]);
  useEffect(() => {
    const link = linkRef.current;
    if (!link) return;
    if (!marks.length || mode !== 'pen') { dropAttach(link.projectId, 'thumb-marks'); return; }
    const d = docRef.current;
    const xs = marks.flatMap((m) => m.points.map((p) => p[0]));
    const ys = marks.flatMap((m) => m.points.map((p) => p[1]));
    const bx = [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
    const hit = (b: PartBox) => b.x < bx[0] + bx[2] && b.x + b.w > bx[0] && b.y < bx[1] + bx[3] && b.y + b.h > bx[1];
    const under = d ? [...d.parts].reverse().filter((p) => !p.hidden && hit(boxOf(p))).map((p) => `${p.id}（${partLabel(p)}）`) : [];
    const snap = marks.map((m) => ({ ...m, points: m.points.map((p) => [p[0], p[1]] as [number, number]) }));
    putAttach(link.projectId, {
      key: 'thumb-marks',
      label: `ペンの書き込み ${marks.length}本`,
      detail: `- みきさんが ${where} にペンで書き込んだ（赤い線 ${marks.length}本、添付の絵）。書き込みの範囲 x=${r0(bx[0])} y=${r0(bx[1])} 幅${r0(bx[2])} 高さ${r0(bx[3])}。`
        + (under.length ? `その下の部品（手前から）: ${under.join('、')}。` : ''),
      upload: () => link.snapshot({ marks: snap }),
      onSent: () => { setMarks([]); setMode('select'); },
      onRemove: () => setMarks([]),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marksKey, mode, where, putAttach, dropAttach]);
  // 閉じたら外す
  useEffect(() => () => {
    const link = linkRef.current;
    if (!link) return;
    dropAttach(link.projectId, 'thumb-part');
    dropAttach(link.projectId, 'thumb-marks');
    link.onContext?.('');
  }, [dropAttach]);

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
      <button type="button" className={toolBtn(mode === 'pen')} onClick={() => { setMode('pen'); setSelected(null); setComposer(null); }} title="ペンで丸や矢印を描き、コメントを付けてダンに直してもらう" data-thumb-pen>
        <PenLine className="h-3.5 w-3.5" />書き込む
      </button>
      <button type="button" className={toolBtn(false)} onClick={addText} title="文字を足す"><Type className="h-3.5 w-3.5" />文字</button>
      <button type="button" className={toolBtn(uploading > 0)} onClick={() => fileRef.current?.click()} disabled={uploading > 0}
        title="画像を足す（貼り付け・サムネへ落とすでも足せます）" data-thumb-add-image>
        {uploading > 0 ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />}画像
      </button>
      <input ref={fileRef} type="file" accept="image/*" multiple className="hidden"
        onChange={(e) => { const fs = Array.from(e.target.files || []); e.target.value = ''; void addImageFiles(fs); }} />
      <button type="button" className={toolBtn(finishRunning)} onClick={() => void startFinish()} disabled={finishRunning}
        title="文字より奥の絵（背景・人物）を、並べた形のまま光と影を整えた1枚にする" data-thumb-finish>
        {finishRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}{finishRunning ? '仕上げ中' : '仕上げ'}
      </button>
      {patterns ? (
        <button type="button" className={toolBtn(lineup)} onClick={() => setLineup(!lineup)} title={lineup ? '1枚を直す画面に戻る' : '案を大きく並べて、絵の下で題とメモを書いて決める'} data-thumb-lineup-toggle>
          <Columns3 className="h-3.5 w-3.5" />{lineup ? '並べるのをやめる' : '並べる'}
        </button>
      ) : null}
      <button type="button" className={toolBtn(listView)} onClick={() => setListView((v) => !v)} title="YouTube の一覧の大きさで見る" data-thumb-list>
        <LayoutGrid className="h-3.5 w-3.5" />{compact ? '一覧' : '一覧で見る'}
      </button>
      <button type="button" className={toolBtn(outputView)} onClick={() => setOutputView((v) => !v)}
        title={outputView ? '枠の外にはみ出た部品も見る・つかむ' : '書き出される形だけを見る（枠の外を切る）'} data-thumb-output-view>
        <Frame className="h-3.5 w-3.5" />{outputView ? '枠の外も見る' : '仕上がりで見る'}
      </button>
      <span className="mx-1 h-5 w-px bg-border" />
      <button type="button" className={toolBtn(false)} onClick={undo} disabled={!undoStack.current.length} title="元に戻す（Ctrl+Z）"><Undo2 className="h-3.5 w-3.5" /></button>
      <button type="button" className={toolBtn(false)} onClick={redo} disabled={!redoStack.current.length} title="やり直す（Ctrl+Shift+Z）"><Redo2 className="h-3.5 w-3.5" /></button>
      <button type="button" className={toolBtn(false)} onClick={() => void reload()} disabled={reloading} title="最新の形と絵を読み直す" data-thumb-reload>
        <RefreshCw className={`h-3.5 w-3.5 ${reloading ? 'animate-spin' : ''}`} />{compact ? null : '読み直す'}
      </button>
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
        <span className="min-w-0 flex-1" title={partLabel(sel)}>
          <PartPreview doc={viewDoc || doc} part={(viewDoc || doc).parts.find((q) => q.id === sel.id) || sel} box={boxOf(sel)} className="h-12 w-full" />
        </span>
        {!chatLink ? (
          <button type="button" title="この部品にコメントしてダンに直してもらう" className="rounded p-1 hover:bg-muted" onClick={() => setComposer({ partIds: [sel.id] })} data-thumb-comment-part>
            <MessageSquare className="h-4 w-4" />
          </button>
        ) : null}
        <button type="button" title="1つ前へ（⌘/Ctrl＋]、Shift も押すと一番前へ）" className="rounded p-1 hover:bg-muted" onClick={() => move(sel.id, 'up')} data-thumb-forward><ArrowUp className="h-4 w-4" /></button>
        <button type="button" title="1つ後ろへ（⌘/Ctrl＋[、Shift も押すと一番後ろへ）" className="rounded p-1 hover:bg-muted" onClick={() => move(sel.id, 'down')} data-thumb-backward><ArrowDown className="h-4 w-4" /></button>
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
                } else {
                  setDoc(next); docRef.current = next; scheduleSave();
                  const top = undoStack.current[undoStack.current.length - 1];
                  if (top) top.after = clone(next);
                  keepUndo();
                }
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
            <label><span className={label}>外の縁の色</span>
              <input type="color" className="h-8 w-full rounded border border-border" value={(sel.outline || '#000000').slice(0, 7)} onChange={(e) => updatePart(sel.id, { outline: e.target.value, outline_width: sel.outline_width || Math.round((sel.stroke_width || 0) * 1.8) || 20 })} />
            </label>
            <label><span className={label}>外の縁の太さ</span>
              <input type="number" className={field} value={Math.round(sel.outline_width || 0)} min={0} onChange={(e) => updatePart(sel.id, { outline_width: Math.max(0, Number(e.target.value)) })} data-thumb-outline />
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
  ) : multi ? (() => {
    const texts = multi.filter((p): p is ThumbTextPart => p.type === 'text');
    const allText = texts.length === multi.length;
    const ids = multi.map((p) => p.id);
    const ab = 'flex h-8 items-center justify-center rounded border border-border hover:bg-muted disabled:opacity-40';
    return (
      <div className="space-y-3" data-thumb-props data-thumb-multi-props>
        <div className="flex items-center gap-1">
          <span className="flex-1 text-xs font-semibold">{multi.length}個の部品を選んでいます</span>
          {!chatLink ? (
            <button type="button" title="選んだ部品にまとめてコメントしてダンに直してもらう" className="rounded p-1 hover:bg-muted" onClick={() => setComposer({ partIds: ids })} data-thumb-comment-part>
              <MessageSquare className="h-4 w-4" />
            </button>
          ) : null}
          <button type="button" title="まとめて1つ前へ（⌘/Ctrl＋]）" className="rounded p-1 hover:bg-muted" onClick={() => move(ids, 'up')} data-thumb-forward><ArrowUp className="h-4 w-4" /></button>
          <button type="button" title="まとめて1つ後ろへ（⌘/Ctrl＋[）" className="rounded p-1 hover:bg-muted" onClick={() => move(ids, 'down')} data-thumb-backward><ArrowDown className="h-4 w-4" /></button>
          <button type="button" title="まとめて複製（Ctrl+D）" className="rounded p-1 hover:bg-muted" onClick={() => duplicate(multi)}><Copy className="h-4 w-4" /></button>
          <button type="button" title="まとめて消す（Delete）" className="rounded p-1 hover:bg-muted hover:text-destructive" onClick={() => remove(ids)}><Trash2 className="h-4 w-4" /></button>
        </div>
        <div className="grid grid-cols-4 gap-1">
          {multi.map((p) => (
            <button key={p.id} type="button" title={`${partLabel(p)}（押すとこれだけを選ぶ）`} onClick={() => setSelected(p.id)}>
              <PartPreview doc={viewDoc || doc} part={(viewDoc || doc).parts.find((q) => q.id === p.id) || p} box={boxOf(p)} className="h-10 w-full" />
            </button>
          ))}
        </div>
        <div>
          <span className={label}>揃える</span>
          <div className="grid grid-cols-4 gap-1" data-thumb-align>
            <button type="button" className={ab} title="左を揃える" onClick={() => arrange('left')} data-thumb-align-left><AlignStartVertical className="h-4 w-4" /></button>
            <button type="button" className={ab} title="横の真ん中を揃える" onClick={() => arrange('hcenter')}><AlignCenterVertical className="h-4 w-4" /></button>
            <button type="button" className={ab} title="右を揃える" onClick={() => arrange('right')}><AlignEndVertical className="h-4 w-4" /></button>
            <button type="button" className={ab} title="横に等間隔" disabled={multi.length < 3} onClick={() => arrange('hspace')} data-thumb-align-hspace><AlignHorizontalSpaceAround className="h-4 w-4" /></button>
            <button type="button" className={ab} title="上を揃える" onClick={() => arrange('top')} data-thumb-align-top><AlignStartHorizontal className="h-4 w-4" /></button>
            <button type="button" className={ab} title="縦の真ん中を揃える" onClick={() => arrange('vcenter')}><AlignCenterHorizontal className="h-4 w-4" /></button>
            <button type="button" className={ab} title="下を揃える" onClick={() => arrange('bottom')}><AlignEndHorizontal className="h-4 w-4" /></button>
            <button type="button" className={ab} title="縦に等間隔" disabled={multi.length < 3} onClick={() => arrange('vspace')}><AlignVerticalSpaceAround className="h-4 w-4" /></button>
          </div>
        </div>
        {allText ? (
          <>
            <label className="block"><span className={label}>書体（まとめて）</span>
              <select className={field} value={texts.every((t) => t.font === texts[0].font) ? texts[0].font : ''} onChange={(e) => updateParts(ids, { font: e.target.value as ThumbFontId })}>
                {texts.every((t) => t.font === texts[0].font) ? null : <option value="">（ばらばら）</option>}
                {Object.entries(THUMB_FONTS).map(([k, f]) => <option key={k} value={k}>{f.label}</option>)}
              </select>
            </label>
            <div>
              <span className={label}>文字の色（まとめて）</span>
              <div className="flex flex-wrap gap-1.5">
                {['#ffffff', '#ffe400', '#ff2a2a', '#b05cff', '#00d0ff', '#111111'].map((c) => (
                  <button key={c} type="button" title={c} onClick={() => updateParts(ids, { fill: c })} className="h-6 w-6 rounded-full border border-border" style={{ background: c }} />
                ))}
                <input type="color" className="h-6 w-8 rounded border border-border" value={texts[0].fill.slice(0, 7)} onChange={(e) => updateParts(ids, { fill: e.target.value })} />
              </div>
            </div>
          </>
        ) : null}
        <div className="grid grid-cols-2 gap-1.5">
          <button type="button" className="h-8 rounded border border-border text-xs hover:bg-muted" onClick={() => updateParts(ids, { hidden: true })}>まとめて隠す</button>
          <button type="button" className="h-8 rounded border border-border text-xs hover:bg-muted" onClick={() => updateParts(ids, { locked: !multi.every((p) => p.locked) })}>{multi.every((p) => p.locked) ? 'まとめて固定を外す' : 'まとめて固定'}</button>
        </div>
      </div>
    );
  })() : null;

  // サムネや部品を押したら、字を打っていた欄（右の会話・文字の欄）から抜ける。サムネの上は押した時に既定の動きを
  // 止めているので、そのままだと欄に入ったままになり、Ctrl+Z などがサムネに届かなかった（2026-11-24）
  const releaseTextFocus = (ev: React.PointerEvent) => {
    const a = document.activeElement as HTMLElement | null;
    if (!a || !isTextField(a)) return;
    const t = ev.target as HTMLElement | null;
    if (t && (isTextField(t) || t.closest('label, [contenteditable="true"]'))) return;
    a.blur();
  };

  // つまみ・選ぶ欄・数の欄は、使い終わったら抜ける（2026-11-24 本人「不透明度とかに左右上下ボタンを取られてパーツ移動が
  // できない。数値やパラメーターにカーソルを残さない」）。矢印キーはいつも部品を動かす
  const releaseControlFocus = () => {
    window.setTimeout(() => {
      const a = document.activeElement as HTMLElement | null;
      if (a && a.tagName === 'INPUT' && !isTextField(a) && (a as HTMLInputElement).type !== 'color') a.blur();
      else if (a && a.tagName === 'BUTTON') a.blur();
    }, 0);
  };
  const releaseSelectFocus = (e: React.FormEvent) => {
    const t = e.target as HTMLElement;
    if (t.tagName === 'SELECT' || (t.tagName === 'INPUT' && (t as HTMLInputElement).type === 'color')) window.setTimeout(() => t.blur(), 0);
  };
  const releaseNumberOnEnter = (e: React.KeyboardEvent) => {
    const t = e.target as HTMLElement;
    if (t.tagName === 'INPUT' && (t as HTMLInputElement).type === 'number' && (e.key === 'Enter' || e.key === 'Escape')) t.blur();
  };

  // 部品の一覧で引っぱって前後を入れ替える（2026-11-24 本人「パーツ一覧で上下（前後）配置変えれるようにしろよ」）。
  // マウスは行をそのまま引っぱる。指は左のつまみ（⋮⋮）から引っぱる（行の上は一覧を送るのに使う）
  const layerSlotAt = (clientX: number, clientY: number, order: string[]): number => {
    const row = (document.elementFromPoint(clientX, clientY) as HTMLElement | null)?.closest('[data-thumb-layer]') as HTMLElement | null;
    const id = row?.getAttribute('data-thumb-layer');
    if (row && id && order.includes(id)) {
      const r = row.getBoundingClientRect();
      return order.indexOf(id) + (clientY > r.top + r.height / 2 ? 1 : 0);
    }
    const rows = Array.from(document.querySelectorAll('[data-thumb-layer]')) as HTMLElement[];
    if (!rows.length) return 0;
    return clientY < rows[0].getBoundingClientRect().top ? 0 : order.length;
  };
  const onLayerPointerDown = (e: React.PointerEvent<HTMLLIElement>, id: string) => {
    if (e.button !== 0) return;
    const t = e.target as HTMLElement;
    if (t.closest('[data-layer-toggle]')) return;
    const grip = !!t.closest('[data-layer-grip]');
    if (e.pointerType !== 'mouse' && !grip) return;
    layerPress.current = { id, x: e.clientX, y: e.clientY, grip, started: false };
    // 押しただけの時に捕まえると、ボタンの「押した」が届かなくなる。つまみだけはすぐ捕まえる
    if (grip) { e.preventDefault(); try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* 取れなくても動く */ } }
  };
  const onLayerPointerMove = (e: React.PointerEvent<HTMLLIElement>) => {
    const pr = layerPress.current;
    if (!pr || !doc) return;
    if (!pr.started) {
      if (Math.hypot(e.clientX - pr.x, e.clientY - pr.y) < 5) return;
      pr.started = true;
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* 取れなくても動く */ }
    }
    const order = [...doc.parts].reverse().map((q) => q.id);
    const ids = selection.includes(pr.id) ? order.filter((x) => selection.includes(x)) : [pr.id];
    // 一覧の上下の端に来たら送る
    const scroller = e.currentTarget.closest('[data-thumb-layers-scroll]') as HTMLElement | null;
    if (scroller) {
      const r = scroller.getBoundingClientRect();
      if (e.clientY < r.top + 32) scroller.scrollTop -= 12;
      else if (e.clientY > r.bottom - 32) scroller.scrollTop += 12;
    }
    setLayerDrag({ ids, slot: layerSlotAt(e.clientX, e.clientY, order) });
  };
  const onLayerPointerUp = () => {
    const pr = layerPress.current;
    layerPress.current = null;
    const ld = layerDrag;
    setLayerDrag(null);
    if (!pr?.started || !ld) return;
    layerClickBlock.current = true;
    window.setTimeout(() => { layerClickBlock.current = false; }, 0);
    reorderTo(ld.ids, ld.slot);
    if (!selection.includes(pr.id)) setSelected(pr.id);
  };

  // 部品の一覧での選び方（エクスプローラーや Figma と同じ）
  const onLayerClick = (e: React.MouseEvent, id: string) => {
    if (layerClickBlock.current) return;
    setMode('select');
    const order = [...doc.parts].reverse().map((q) => q.id);
    if (e.shiftKey && listAnchor.current && order.includes(listAnchor.current)) {
      const a = order.indexOf(listAnchor.current), b = order.indexOf(id);
      const range = order.slice(Math.min(a, b), Math.max(a, b) + 1);
      setSelection((cur) => ((e.metaKey || e.ctrlKey) ? [...cur, ...range.filter((x) => !cur.includes(x))] : range));
      return;
    }
    listAnchor.current = id;
    if (e.metaKey || e.ctrlKey) {
      setSelection((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
      return;
    }
    setSelected(id);
  };

  const layerOrder = [...(viewDoc || doc).parts].reverse();
  const layers = (
    <div data-thumb-layers>
      <div className="mb-1 text-[11px] font-semibold text-muted-foreground">部品（上が手前・引っぱって前後を入れ替え）</div>
      <ul className="space-y-1">
        {layerOrder.map((p, i) => {
          const dragging = !!layerDrag && layerDrag.ids.includes(p.id);
          const lineBefore = !!layerDrag && layerDrag.slot === i;
          const lineAfter = !!layerDrag && i === layerOrder.length - 1 && layerDrag.slot === layerOrder.length;
          return (
            <li key={p.id} data-thumb-layer={p.id} data-selected={selection.includes(p.id) ? 'true' : undefined}
              onPointerDown={(e) => onLayerPointerDown(e, p.id)} onPointerMove={onLayerPointerMove} onPointerUp={onLayerPointerUp} onPointerCancel={onLayerPointerUp}
              className={`group relative flex select-none items-center gap-1 rounded p-0.5 text-xs ${selection.includes(p.id) ? 'bg-sky-500/15 ring-2 ring-sky-500' : 'hover:bg-muted'} ${dragging ? 'opacity-50' : ''} ${layerDrag ? 'cursor-grabbing' : ''}`}>
              {lineBefore ? <span className="pointer-events-none absolute -top-[3px] left-0 right-0 h-[3px] rounded bg-sky-500" data-thumb-layer-drop /> : null}
              {lineAfter ? <span className="pointer-events-none absolute -bottom-[3px] left-0 right-0 h-[3px] rounded bg-sky-500" data-thumb-layer-drop /> : null}
              <span data-layer-grip title="引っぱって前後を入れ替える" className="flex h-14 w-4 shrink-0 cursor-grab items-center justify-center text-muted-foreground/60 hover:text-foreground" style={{ touchAction: 'none' }}>
                <GripVertical className="h-3.5 w-3.5" />
              </span>
              {/* 名前の文字ではなく、その部品だけの絵で見せる（名前はマウスを乗せた時だけ）。
                  ⌘/Ctrl で1つずつ足す・外す、Shift で前に押した所からここまでをまとめて選ぶ */}
              <button type="button" title={`${partLabel(p)}（Shift・⌘/Ctrl で複数選べます。引っぱると前後を入れ替えます）`} className={`min-w-0 flex-1 ${p.hidden ? 'opacity-40' : ''}`} onClick={(e) => onLayerClick(e, p.id)}>
                <PartPreview doc={viewDoc || doc} part={p} box={boxOf(p)} className="pointer-events-none h-14 w-full" />
              </button>
              <button type="button" data-layer-toggle title={p.hidden ? '出す' : '隠す'} className="rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => updatePart(p.id, { hidden: !p.hidden })}>
                {p.hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              </button>
              <button type="button" data-layer-toggle title={p.locked ? '引きずって動かせるようにする' : '引きずっても動かないようにする（角で大きさは変えられる）'} className="rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => updatePart(p.id, { locked: !p.locked })}>
                {p.locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5 opacity-40" />}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );

  const instrList = instructions.length ? (
    <div data-thumb-instructions>
      <div className="mb-1 text-[11px] font-semibold text-muted-foreground">コメント</div>
      <ul className="space-y-1.5">
        {[...instructions].reverse().map((ins) => {
          const st = ins.job_id ? jobs[ins.job_id] : undefined;
          const active = st ? st.active : true;
          const num = instructions.indexOf(ins) + 1;
          const tp = ins.part_id ? (viewDoc || doc).parts.find((q) => q.id === ins.part_id) : undefined;
          const tids = (ins.part_ids && ins.part_ids.length ? ins.part_ids : tp ? [tp.id] : []).filter((id) => (viewDoc || doc).parts.some((q) => q.id === id));
          return (
            <li key={ins.id} data-thumb-instruction={ins.id} className={`rounded border p-2 text-xs ${showInstr === ins.id ? 'border-sky-400 ring-1 ring-sky-400' : 'border-border'}`}
              onMouseEnter={() => setShowInstr(ins.id)} onMouseLeave={() => setShowInstr(null)}>
              <div className="flex items-start gap-1.5">
                <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white ${active ? 'bg-sky-500' : 'bg-emerald-500'}`}>{num}</span>
                <button type="button" className="min-w-0 flex-1 text-left" onClick={() => { setShowInstr((v) => (v === ins.id ? null : ins.id)); if (tids.length) { setSelection(tids); setMode('select'); } }}>
                  {tp ? <PartPreview doc={viewDoc || doc} part={tp} box={boxOf(tp)} className="mb-1 h-10 w-full" /> : null}
                  <div className="font-medium">{ins.note || '（書き込みだけ）'}</div>
                  <div className="mt-1 flex items-start gap-1 text-muted-foreground">
                    {active ? <Loader2 className="mt-0.5 h-3 w-3 shrink-0 animate-spin text-sky-500" /> : <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500" />}
                    <span>{st ? (st.active ? (st.progress || st.label) : (st.result || st.label)) : '順番待ち'}</span>
                  </div>
                </button>
                <button type="button" title="消す" className="rounded p-0.5 text-muted-foreground hover:text-destructive" onClick={() => removeInstruction(ins.id)}><X className="h-3.5 w-3.5" /></button>
              </div>
              {!active ? (
                <button type="button" className="mt-1.5 text-[11px] text-sky-600 hover:underline dark:text-sky-300"
                  onClick={() => {
                    setResendOf(ins); setNote(ins.note);
                    const pens = ins.marks.filter((m) => m.color !== TARGET_COLOR);
                    if (tids.length && !pens.length) { setMarks([]); setMode('select'); setSelection(tids); setComposer({ partIds: tids }); }
                    else { setMarks(pens); setMode('pen'); setSelected(null); setComposer(tids.length ? { partIds: tids } : null); }
                  }}>
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

  const penBar = mode === 'pen' && chatLink ? (
    <div className="rounded-md border border-red-300 bg-red-50/60 p-2 text-xs leading-relaxed dark:bg-red-950/30" data-thumb-penbar data-thumb-penbar-chat>
      <div>{marks.length
        ? `描いた線（${marks.length}本）は、${compact ? '会話' : '右の会話'}の入力欄に添えてあります。どうしたいかを会話に書いて送ってください。`
        : 'サムネの上に丸や矢印を描くと、会話に添えられます。'}</div>
      <div className="mt-1.5 flex gap-1.5">
        {compact && phoneChat ? (
          <button type="button" disabled={!marks.length} onClick={() => setPhoneChatOpen(true)}
            className="flex h-8 flex-1 items-center justify-center gap-1 rounded-md bg-sky-600 text-xs font-semibold text-white disabled:opacity-40" data-thumb-to-chat>
            <MessageSquare className="h-3.5 w-3.5" />会話で送る
          </button>
        ) : null}
        <button type="button" onClick={() => setMarks((m) => m.slice(0, -1))} disabled={!marks.length} className="h-8 rounded-md border border-border px-2 text-xs disabled:opacity-40">1本消す</button>
        <button type="button" onClick={() => { setMarks([]); setMode('select'); }} className="h-8 rounded-md border border-border px-2 text-xs">やめる</button>
      </div>
    </div>
  ) : mode === 'pen' ? (
    <div className="rounded-md border border-red-300 bg-red-50/60 p-2 text-xs leading-relaxed dark:bg-red-950/30" data-thumb-penbar>
      <div>{marks.length ? '描いた線の横の欄に、どう直してほしいかを書いて送ってください。' : 'サムネの上に丸や矢印を描くと、その横にコメントの欄が出ます。'}</div>
      <div className="mt-1.5 flex gap-1.5">
        <button type="button" onClick={() => setMarks((m) => m.slice(0, -1))} disabled={!marks.length} className="h-8 rounded-md border border-border px-2 text-xs disabled:opacity-40">1本消す</button>
        <button type="button" onClick={() => { setMarks([]); setNote(''); setResendOf(null); setMode('select'); }} className="h-8 rounded-md border border-border px-2 text-xs">やめる</button>
      </div>
    </div>
  ) : null;

  // ── その場に出るコメントの欄（台本の画面のコメントと同じく、選んだ部品・描いた線の横に出る）──
  const penDrawing = gesture?.kind === 'pen';
  const composerAt: { anchor: [number, number]; parts: ThumbPart[] } | null = (() => {
    if (chatLink) return null;
    const cparts = composer ? composer.partIds.map((id) => doc.parts.find((p) => p.id === id)).filter((p): p is ThumbPart => !!p) : [];
    if (mode === 'pen') {
      const mb = marks.length && !penDrawing ? marksBounds(marks) : null;
      if (!mb) return null;
      return { anchor: [mb.x + mb.w, mb.y], parts: cparts };
    }
    if (!cparts.length || cparts.length !== selection.length || !cparts.every((p) => selection.includes(p.id))) return null;
    const tb = unionBox(cparts.map((p) => partBounds(p, boxOf(p), boxes[p.id])))!;
    return { anchor: [tb.x + tb.w, tb.y], parts: cparts };
  })();
  // 選んだ部品の右上の小さな「コメント」ボタン（つかんでいる間は隠す）。複数を選んでいれば全部を囲む範囲の右上
  const shownSel = selParts.filter((p) => !p.hidden);
  const commentBtnAt: [number, number] | null = !chatLink && mode === 'select' && shownSel.length && !gesture && !marquee && !composerAt ? (() => {
    const tb = unionBox(shownSel.map((p) => partBounds(p, boxOf(p), boxes[p.id])))!;
    return toStagePx(tb.x + tb.w, tb.y);
  })() : null;
  const COMPOSER_W = 272;
  const floatPos = ([px, py]: [number, number], w: number, h: number) => ({
    left: Math.max(4, Math.min(boardW - w - 4, px + 12)),
    top: Math.max(4, Math.min(boardH - h - 4, py - 8)),
  });
  const floating = (
    <>
      {danHandAt && danTarget ? (
        <div aria-hidden className="pointer-events-none absolute z-40" data-dan-hand
          style={{ left: danHandAt[0], top: danHandAt[1], opacity: fade, transition: 'left .42s cubic-bezier(.3,.7,.2,1), top .42s cubic-bezier(.3,.7,.2,1), opacity .3s' }}>
          <MousePointer2 className="h-5 w-5 fill-sky-400 text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.7)]" />
          <span className="ml-3 mt-[-2px] flex w-max max-w-[240px] items-center gap-1 rounded-full bg-sky-500 px-2 py-[2px] text-[11px] font-semibold leading-tight text-white shadow">
            {danTarget.working ? <Loader2 className="h-3 w-3 animate-spin" /> : null}ダン<span className="truncate font-normal">{danTarget.label}</span>
          </span>
        </div>
      ) : null}
      {commentBtnAt ? (
        <button type="button" onPointerDown={(e) => e.stopPropagation()} onClick={() => setComposer({ partIds: shownSel.map((p) => p.id) })}
          title="この部品にコメントしてダンに直してもらう"
          className="absolute z-20 flex h-8 items-center gap-1 rounded-full bg-sky-600 px-2.5 text-xs font-semibold text-white shadow-lg hover:bg-sky-500"
          style={floatPos(commentBtnAt, 96, 32)} data-thumb-comment-btn>
          <MessageSquare className="h-3.5 w-3.5" />コメント
        </button>
      ) : null}
      {composerAt ? (() => {
        const [px, py] = toStagePx(composerAt.anchor[0], composerAt.anchor[1]);
        const targets = composerAt.parts;
        return (
          <div onPointerDown={(e) => e.stopPropagation()} className="absolute z-30 rounded-lg border border-border bg-popover p-2 text-popover-foreground shadow-xl"
            style={{ width: COMPOSER_W, ...floatPos([px, py], COMPOSER_W, 150) }} data-thumb-composer>
            {targets.length ? (
              <div className="mb-1.5 flex items-center gap-1.5">
                {targets.slice(0, 4).map((target) => (
                  <PartPreview key={target.id} doc={viewDoc || doc} part={(viewDoc || doc).parts.find((q) => q.id === target.id) || target} box={boxOf(target)} className="h-8 w-12 shrink-0" />
                ))}
                <span className="text-[11px] text-muted-foreground">{targets.length > 1 ? `${targets.length}個の部品` : 'この部品'}へのコメント{marks.length ? '（赤い線つき）' : ''}</span>
              </div>
            ) : <div className="mb-1.5 text-[11px] text-muted-foreground">赤い線へのコメント</div>}
            <textarea
              autoFocus
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') { e.preventDefault(); setComposer(null); if (mode === 'pen') { setMarks([]); setMode('select'); } return; }
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void sendMarks(); }
              }}
              rows={2}
              placeholder="どう直してほしいか（Enter で送る）"
              className="w-full resize-none rounded border border-border bg-background px-2 py-1.5 text-sm"
              data-thumb-note
            />
            <div className="mt-1.5 flex gap-1.5">
              <button type="button" disabled={sending || !note.trim()} onClick={() => void sendMarks()}
                className="flex h-8 flex-1 items-center justify-center gap-1 rounded-md bg-sky-600 text-xs font-semibold text-white disabled:opacity-40" data-thumb-send>
                {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}ダンに送る
              </button>
              <button type="button" onClick={() => { setComposer(null); setNote(''); setResendOf(null); if (mode === 'pen') { setMarks([]); setMode('select'); } }}
                className="h-8 rounded-md border border-border px-2 text-xs">やめる</button>
            </div>
          </div>
        );
      })() : null}
    </>
  );

  const stage = (
    <div className={`relative min-h-0 min-w-0 ${compact ? 'w-full' : 'h-full w-full'}`}>
    <div ref={stageWrap} className={`min-h-0 min-w-0 overflow-auto ${compact ? 'w-full' : 'h-full w-full'}`}
      style={compact ? { height: boardH + STAGE_MARGIN * 2 } : undefined} data-thumb-stage-wrap
      onPointerDown={onStagePointerDown}
      onDragOver={(e) => { if (Array.from(e.dataTransfer?.items || []).some((i) => i.kind === 'file')) e.preventDefault(); }}
      onDrop={onStageDrop}>
      <div className="flex min-h-full min-w-full w-max items-center justify-center" style={{ padding: STAGE_MARGIN }}>
      <div style={{ width: boardW }} className={`relative shrink-0 ${outputView ? 'shadow-lg' : ''}`} data-thumb-stage>
        <ThumbCanvas
          ref={svgRef}
          doc={shownDoc || doc}
          width={boardW}
          pasteboard={outputView || !board ? undefined : board}
          marks={shownMarks}
          onMeasure={(id, box) => setBoxes((b) => (b[id] && Math.abs(b[id].x - box.x) < 0.5 && Math.abs(b[id].y - box.y) < 0.5 && Math.abs(b[id].w - box.w) < 0.5 && Math.abs(b[id].h - box.h) < 0.5 ? b : { ...b, [id]: box }))}
          partProps={partProps}
          overlay={<>{danMarks}{overlay}{guideEl}{marqueeEl}{pins}</>}
          style={{ touchAction: 'none', cursor: mode === 'pen' ? 'crosshair' : undefined }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => onPointerUp()}
          onContextMenu={onContextMenu}
          onDoubleClick={onDoubleClick}
        />
        {floating}
      </div>
      </div>
    </div>
      {zoom !== 1 ? (
        <button type="button" onClick={() => setZoom(1)} title="枠に収まる大きさに戻す" data-thumb-zoom
          className="absolute bottom-2 left-2 z-10 rounded-md bg-black/70 px-2 py-1 text-[11px] font-medium text-white">
          {Math.round(zoom * 100)}%・戻す
        </button>
      ) : null}
      {pickMenu ? (
        <>
          <div className="fixed inset-0 z-[55]" onPointerDown={() => setPickMenu(null)} onContextMenu={(e) => { e.preventDefault(); setPickMenu(null); }} />
          <div className="fixed z-[60] w-52 overflow-hidden rounded-md border border-border bg-popover py-1 text-xs shadow-lg"
            style={{ left: Math.min(pickMenu.x, window.innerWidth - 216), top: Math.max(4, Math.min(pickMenu.y, window.innerHeight - 24 - 9 * 26 - pickMenu.ids.length * 48)) }} data-thumb-pick-menu>
            {(() => {
              // 選んでいる部品への操作（Canva・Figma の右クリックと同じ）
              const d = docRef.current;
              const ps = d ? d.parts.filter((p) => selection.includes(p.id)) : [];
              const ids = ps.map((p) => p.id);
              const clip = typeof window !== 'undefined' ? readClip() : null;
              const items: Array<[string, string, boolean, () => void]> = [
                ['コピー', '⌘C', !!ps.length, () => copyParts(ps)],
                ['切り取り', '⌘X', !!ps.length, () => { copyParts(ps); remove(ids); }],
                ['貼り付け', '⌘V', !!clip, () => pasteParts(readClip())],
                ['複製', '⌘D', !!ps.length, () => duplicate(ps)],
                ['一番前へ', '⇧⌘]', !!ps.length, () => move(ids, 'front')],
                ['1つ前へ', '⌘]', !!ps.length, () => move(ids, 'up')],
                ['1つ後ろへ', '⌘[', !!ps.length, () => move(ids, 'down')],
                ['一番後ろへ', '⇧⌘[', !!ps.length, () => move(ids, 'back')],
                ['消す', 'Delete', !!ps.length, () => remove(ids)],
              ];
              return (
                <div className="border-b border-border pb-1" data-thumb-ctx-actions>
                  {items.map(([name, key, on, act]) => (
                    <button key={name} type="button" disabled={!on} data-thumb-ctx={name}
                      className="flex w-full items-center justify-between px-2.5 py-1 text-left hover:bg-muted disabled:opacity-40"
                      onClick={() => { act(); setPickMenu(null); }}>
                      <span>{name}</span><span className="text-[10px] text-muted-foreground">{key}</span>
                    </button>
                  ))}
                </div>
              );
            })()}
            <div className="px-2.5 pb-1 pt-1 text-[10px] text-muted-foreground">ここにある部品（上が手前）</div>
            {pickMenu.ids.map((id) => {
              const p = doc.parts.find((q) => q.id === id);
              if (!p) return null;
              return (
                <button key={id} type="button" title={partLabel(p)} className={`flex w-full items-center gap-1.5 px-1.5 py-1 text-left hover:bg-muted ${selection.includes(id) ? 'bg-sky-500/15' : ''}`}
                  onClick={() => { setSelected(id); setMode('select'); setPickMenu(null); }}>
                  <PartPreview doc={viewDoc || doc} part={(viewDoc || doc).parts.find((q) => q.id === id) || p} box={boxOf(p)} className={`h-10 min-w-0 flex-1 ${selection.includes(id) ? 'ring-2 ring-sky-500' : ''}`} />
                  {p.locked ? <Lock className="h-3 w-3 shrink-0 opacity-60" /> : null}
                </button>
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );

  const strip = patterns ? (
    <ThumbPatterns roomId={roomId} currentId={contentId} liveDoc={doc} link={patterns} compact={compact} onActions={setPatternActions}
      beforeSwitch={async () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); await flush(); }} />
  ) : null;

  const lineupView = lineup && patterns ? (
    <ThumbLineup roomId={roomId} videoId={patterns.videoId} currentId={contentId} liveDoc={doc} compact={compact}
      onOpen={async (p) => {
        setLineup(false);
        if (p.id === contentId) return;
        if (saveTimer.current) window.clearTimeout(saveTimer.current);
        await flush();
        patterns.onOpen(p);
      }} />
  ) : null;

  const listPanel = listView ? <ThumbListView doc={doc} title={title} onClose={() => setListView(false)} compact={compact} /> : null;

  const savingText = saving === 'saving' ? '保存中…' : saving === 'error' ? '保存できていません' : '';

  if (compact) {
    return (
      <div className="relative flex h-full min-h-0 flex-col bg-background" data-thumb-editor="phone" onPointerDownCapture={releaseTextFocus} onPointerUpCapture={releaseControlFocus} onChangeCapture={releaseSelectFocus} onKeyDownCapture={releaseNumberOnEnter}>
        <div className="flex shrink-0 items-center gap-2 px-2 py-1.5">
          <button type="button" onClick={onBack} className="rounded p-1.5 hover:bg-muted" title={backLabel || '戻る'} aria-label={backLabel || '戻る'} data-thumb-back><ArrowLeft className="h-5 w-5" /></button>
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</span>
          <span className="text-[11px] text-muted-foreground">{savingText}</span>
        </div>
        {lineupView && !phoneChatOpen ? (
          <>
            <div className="shrink-0 px-2 pb-1">{tools}</div>
            <div className="min-h-0 flex-1 border-t border-border">{lineupView}</div>
          </>
        ) : (
          <>
        <div className="shrink-0">{stage}</div>
        {strip ? <div className="shrink-0 border-b border-border">{strip}</div> : null}
          </>
        )}
        {lineupView && !phoneChatOpen ? null : phoneChatOpen && phoneChat ? (
          <div className="min-h-0 flex-1 border-t border-border">
            {phoneChat(<button type="button" onClick={() => setPhoneChatOpen(false)} className="rounded p-1 hover:bg-muted" title="サムネの道具に戻る"><X className="h-4 w-4" /></button>)}
          </div>
        ) : (
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overflow-x-hidden p-3" data-thumb-layers-scroll>
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
            {attached.length ? (
              <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1 text-[11px] font-bold" data-thumb-chat-badge>{attached.length}</span>
            ) : null}
          </button>
        ) : null}
        {listPanel}
        {comparePanel}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background" data-thumb-editor="pc" onPointerDownCapture={releaseTextFocus} onPointerUpCapture={releaseControlFocus} onChangeCapture={releaseSelectFocus} onKeyDownCapture={releaseNumberOnEnter}>
      <header className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <button type="button" onClick={onBack} className="flex items-center gap-1 rounded p-1.5 text-xs hover:bg-muted" title={backLabel || 'ライブラリへ戻る'} aria-label={backLabel || 'ライブラリへ戻る'} data-thumb-back><ArrowLeft className="h-4 w-4" />{backLabel ? <span>{backLabel}</span> : null}</button>
        <h1 className="min-w-0 max-w-[30%] truncate text-sm font-semibold">{title}</h1>
        <div className="ml-2 min-w-0 flex-1">{tools}</div>
        <span className="text-[11px] text-muted-foreground">{savingText}</span>
      </header>
      <div className="flex min-h-0 flex-1">
        {lineupView ? <div className="min-h-0 min-w-0 flex-1 bg-muted/40">{lineupView}</div> : (
        <>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-muted/40">
          <div className="min-h-0 flex-1 p-6 pb-3">{stage}</div>
          {strip ? <div className="shrink-0 border-t border-border bg-background/70">{strip}</div> : null}
        </div>
        <aside className="w-72 shrink-0 space-y-4 overflow-y-auto border-l border-border p-3" data-thumb-layers-scroll>
          {finishCard}
          {penBar}
          {mode === 'select' ? props : null}
          {instrList}
          {layers}
        </aside>
        </>
        )}
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
