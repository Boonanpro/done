// サムネを部品で持つ形（2026-11-18 本人「サムネの微調整の往復に時間がかかりすぎる。自分で手で直せる・書き込みで
// 指示できる・その場で変わる様子が見える仕組みがほしい」）。
//
// 作品（contents.json の1件）の format が 'thumbnail' の時、timeline.thumbnail にこの形で入る。
// 部品は配列の順に奥から手前へ重なる。座標は width×height（既定 1920×1080）の画素。書き出しは 1280×720 の PNG。
// エディターの画面も、書き出し（/thumbnail-frame をサーバーが headless Chromium で撮る）も、同じ <ThumbCanvas>（SVG）で描く。
// ダンが直す時は scripts/thumb.py（同じ形の JSON を読み書きする）。

export type ThumbShadow = { color?: string; blur?: number; opacity?: number; dx?: number; dy?: number };

export type ThumbBase = {
  id: string;
  name?: string;
  hidden?: boolean;
  locked?: boolean;
  opacity?: number;
  rotation?: number; // 度。部品の真ん中を中心に回す
};

export type ThumbImagePart = ThumbBase & {
  type: 'image';
  src: string;          // 絵の URL（/api/v1/production-assets/media?… など）
  asset_id?: string;    // 作品の部屋の素材の id（ダンの描き直しが元の絵を探す）
  x: number; y: number; w: number; h: number;
  flip_x?: boolean;
  // 「仕上げ」で作った1枚の絵（sources は隠した元の絵の部品の id。仕上げを外すと元に戻る）
  finish?: { job_id?: string; sources: string[] } | null;
};

export type ThumbTextPart = ThumbBase & {
  type: 'text';
  text: string;          // 改行で複数行
  x: number;             // 1行目の左端
  y: number;             // 1行目の文字の並びの線（ベースライン）
  font: ThumbFontId;
  size: number;          // 文字の大きさ（px）
  fill: string;
  stroke?: string;       // 縁の色
  stroke_width?: number; // 縁の太さ（文字の外側へ出る幅 px）
  outline?: string;       // 外の縁の色（二重の縁。内の縁 stroke の外にもう1本）
  outline_width?: number; // 外の縁の太さ（文字の外側へ出る幅 px。stroke_width より太くする）。影はこちらに付く
  letter_spacing?: number;
  line_height?: number;  // 行の間（px、ベースラインからベースライン）
  shadow?: ThumbShadow | null;
  bg?: { color: string; radius?: number; top: number; bottom: number; left: number; right: number } | null;
};

export type ThumbPart = ThumbImagePart | ThumbTextPart;

export type ThumbDoc = {
  width: number;
  height: number;
  background?: string;
  parts: ThumbPart[];
  rev?: number;
  // 誰がいつ保存したか（'dan' | 'owner'）。ダンの直しを画面で動きで見せるのに使う
  saved_by?: string;
  saved_at?: string;
  // 一覧で並べて見る時に横に並べるほかのサムネ（参考や同じチャンネルの過去の動画）
  references?: Array<{ src: string; title?: string; channel?: string }>;
  title?: string; // 一覧で並べた時に下に出す動画の題
  // 本人がペンで書き込んで送った指示（結果は指示の欄にだけ出す）
  instructions?: ThumbInstruction[];
};

export type ThumbInstruction = {
  id: string;
  note: string;
  marks: ThumbMark[];
  job_id?: string;
  created_at: string;
  /** コメントを付けた部品（部品を選んでコメントした時） */
  part_id?: string | null;
  /** 複数の部品をまとめて選んでコメントした時の全部（part_id はその先頭） */
  part_ids?: string[] | null;
  /** コメントの印を出す所（サムネの画素） */
  anchor?: [number, number] | null;
};

export type ThumbFontId =
  | 'hiragino-w9' | 'hiragino-w8' | 'hiragino-w6'
  | 'noto-sans' | 'dela-gothic' | 'zen-maru' | 'reggae' | 'mplus-rounded' | 'rocknroll' | 'mincho' | 'toppan-mincho';

const OWNER_FONT_BASE = '/api/v1/editor-assistant/scene-vendor/fonts/';

// [表示名, CSS の family, 太さ, ファイル]
export const THUMB_FONTS: Record<ThumbFontId, { label: string; family: string; weight: number; url: string }> = {
  'hiragino-w9': { label: 'ヒラギノ角ゴ W9', family: 'HiraginoW9', weight: 900, url: `${OWNER_FONT_BASE}HiraginoSans-W9.otf` },
  'hiragino-w8': { label: 'ヒラギノ角ゴ W8', family: 'HiraginoW8', weight: 800, url: `${OWNER_FONT_BASE}HiraginoSans-W8.otf` },
  'hiragino-w6': { label: 'ヒラギノ角ゴ W6', family: 'HiraginoW6', weight: 600, url: `${OWNER_FONT_BASE}HiraginoSans-W6.otf` },
  'noto-sans': { label: 'Noto Sans 太', family: 'NotoSansJP', weight: 900, url: '/fonts/NotoSansJP.ttf' },
  'dela-gothic': { label: '極太', family: 'DelaGothicOne', weight: 400, url: '/fonts/DelaGothicOne-Regular.ttf' },
  'zen-maru': { label: '角丸', family: 'ZenMaruGothic', weight: 900, url: '/fonts/ZenMaruGothic-Black.ttf' },
  'reggae': { label: 'レゲエ', family: 'ReggaeOne', weight: 400, url: '/fonts/ReggaeOne-Regular.ttf' },
  'mplus-rounded': { label: '丸ポップ', family: 'MPLUSRounded', weight: 800, url: '/fonts/MPLUSRounded1c-ExtraBold.ttf' },
  'rocknroll': { label: 'ロック', family: 'RocknRollOne', weight: 400, url: '/fonts/RocknRollOne-Regular.ttf' },
  'mincho': { label: '明朝', family: 'ShipporiMincho', weight: 800, url: '/fonts/ShipporiMincho-ExtraBold.ttf' },
  'toppan-mincho': { label: '見出し明朝', family: 'ToppanMidashiMincho', weight: 800, url: `${OWNER_FONT_BASE}ToppanBunkyuMidashiMincho-ExtraBold.otf` },
};

export function thumbFont(id: unknown) {
  return (typeof id === 'string' && Object.prototype.hasOwnProperty.call(THUMB_FONTS, id))
    ? THUMB_FONTS[id as ThumbFontId] : THUMB_FONTS['hiragino-w9'];
}

// 使っている書体だけを読む（書き出しは読み終わるまで待つ）
const loads = new Map<string, Promise<void>>();
export function loadThumbFonts(doc: ThumbDoc | null | undefined, timeoutMs = 10000): Promise<void> {
  if (typeof document === 'undefined' || typeof FontFace === 'undefined' || !doc) return Promise.resolve();
  const ids = new Set<string>();
  for (const p of doc.parts) if (p.type === 'text') ids.add(p.font);
  return Promise.all([...ids].map((id) => {
    const f = thumbFont(id);
    let p = loads.get(f.url);
    if (!p) {
      p = (async () => {
        const face = new FontFace(f.family, `url("${f.url}")`, { weight: String(f.weight) });
        await face.load();
        document.fonts.add(face);
      })().catch(() => { loads.delete(f.url); });
      loads.set(f.url, p);
    }
    return Promise.race([p, new Promise<void>((r) => setTimeout(r, timeoutMs))]);
  })).then(() => undefined);
}

export function emptyThumbDoc(): ThumbDoc {
  return { width: 1920, height: 1080, background: '#111', parts: [], rev: 0 };
}

export function asThumbDoc(raw: unknown): ThumbDoc {
  const d = (raw && typeof raw === 'object' ? raw : {}) as Partial<ThumbDoc>;
  return {
    ...emptyThumbDoc(),
    ...d,
    parts: Array.isArray(d.parts) ? d.parts.filter((p) => p && typeof p === 'object' && (p.type === 'image' || p.type === 'text')) as ThumbPart[] : [],
  };
}

export function newPartId(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

// ペンで描いた印（ダンへの書き込み指示）。座標はサムネの画素。
export type ThumbMark = { color: string; width: number; points: Array<[number, number]> };

// ── 仕上げ（荒く並べた絵を、構図のまま光と影を整えた1枚にする。サーバーは thumbnail_doc.finish_*）──

export type ThumbFinishJob = {
  job_id: string;
  state: 'running' | 'done' | 'error';
  step?: string;
  message?: string;
  src?: string;
  asset_id?: string;
  sources?: string[];
  decided?: 'adopted' | 'discarded';
  started_at?: string;
};

export function finishPart(doc: ThumbDoc): ThumbImagePart | undefined {
  return doc.parts.find((p): p is ThumbImagePart => p.type === 'image' && !!p.finish);
}

// 仕上げた絵を外し、隠していた元の絵を出す
export function removeFinish(doc: ThumbDoc): ThumbDoc {
  const fin = finishPart(doc);
  if (!fin) return doc;
  const srcs = new Set(fin.finish?.sources || []);
  return { ...doc, parts: doc.parts.filter((p) => p !== fin).map((p) => (srcs.has(p.id) ? { ...p, hidden: false } : p)) };
}

// 仕上げた絵を入れる（元の絵は隠すだけ。前の仕上げは外してから）。サーバーの apply_finish と同じ
export function applyFinish(doc: ThumbDoc, job: ThumbFinishJob): ThumbDoc {
  if (!job.src || !job.asset_id) return doc;
  const base = removeFinish(doc);
  const srcs = new Set(job.sources || []);
  const idxs = base.parts.map((p, i) => (srcs.has(p.id) ? i : -1)).filter((i) => i >= 0);
  const at = idxs.length ? Math.min(...idxs) : 0;
  const parts: ThumbPart[] = base.parts.map((p) => (srcs.has(p.id) ? { ...p, hidden: true } : p));
  parts.splice(at, 0, {
    id: newPartId('f'), type: 'image', name: '仕上げた絵', src: job.src, asset_id: job.asset_id,
    x: 0, y: 0, w: base.width, h: base.height, locked: true, finish: { job_id: job.job_id, sources: [...srcs] },
  });
  return { ...base, parts };
}

// ── 3者の重ね合わせ（2026-11-24 ダンが案件の絵の赤丸を消して保存した2秒後、開いていたエディターが手元の古い形で
//    上書きして、ダンの直しが消えた）。base＝手元の形の元にした保存の形、ours＝手元の形、theirs＝今保存されている形。
//    部品ごとに、手元で変えた部品は手元の形、変えていない部品は今保存されている形を使う。元に戻す・やり直すも
//    これで「自分の1手の前後」だけを今の形に当てる（ダンの直しを巻き戻さない）。
const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

function mergeList<T extends { id: string }>(base: T[], ours: T[], theirs: T[]): T[] {
  const bm = new Map(base.map((x) => [x.id, x]));
  const om = new Map(ours.map((x) => [x.id, x]));
  const tm = new Map(theirs.map((x) => [x.id, x]));
  const ids = new Set([...bm.keys(), ...om.keys(), ...tm.keys()]);
  const pick = new Map<string, T>();
  for (const id of ids) {
    const o = om.get(id), b = bm.get(id), t = tm.get(id);
    const v = same(o, b) ? t : o;   // 手元で変えて（足して・消して）いなければ、今保存されている方
    if (v) pick.set(id, v);
  }
  // 並び: 手元で並びを変えていれば手元の並び、変えていなければ今保存されている並び。残りはもう一方の並びで足す
  const common = (xs: T[], keep: Set<string>) => xs.map((x) => x.id).filter((id) => keep.has(id));
  const both = new Set([...bm.keys()].filter((id) => om.has(id)));
  const ownOrder = !same(common(base, both), common(ours, both));
  const first = ownOrder ? ours : theirs, second = ownOrder ? theirs : ours;
  const out: string[] = [];
  for (const x of first) if (pick.has(x.id) && !out.includes(x.id)) out.push(x.id);
  second.forEach((x, i) => {
    if (!pick.has(x.id) || out.includes(x.id)) return;
    // もう一方で足された物は、その並びの前の物のすぐ後ろへ
    const prev = second.slice(0, i).reverse().find((y) => out.includes(y.id));
    out.splice(prev ? out.indexOf(prev.id) + 1 : 0, 0, x.id);
  });
  return out.map((id) => pick.get(id)!);
}

export function mergeThumbDocs(base: ThumbDoc, ours: ThumbDoc, theirs: ThumbDoc): ThumbDoc {
  const out: Record<string, unknown> = { ...theirs };
  const keys = new Set([...Object.keys(base), ...Object.keys(ours), ...Object.keys(theirs)]);
  const b = base as unknown as Record<string, unknown>, o = ours as unknown as Record<string, unknown>;
  for (const k of keys) {
    if (k === 'parts' || k === 'instructions' || k === 'rev' || k === 'saved_by' || k === 'saved_at') continue;
    if (!same(o[k], b[k])) out[k] = o[k];
  }
  out.parts = mergeList(base.parts || [], ours.parts || [], theirs.parts || []);
  out.instructions = mergeList(base.instructions || [], ours.instructions || [], theirs.instructions || []);
  return out as unknown as ThumbDoc;
}
