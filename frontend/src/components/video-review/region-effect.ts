// 範囲の効果（モザイク・ぼかし・単色・マーカー・スポットライト・枠・ズーム）。
// add_region は素材を持たず範囲（region）を持つクリップを映像の段に置く。書き出し（native_ui の Z_FX、
// timeline_commands.REGION_STYLES）と同じく「素材が無く範囲があり、style が note でない」クリップを効果とし、
// その段より下に重なった絵を加工する。プレビューがこれを絵として描こうとすると、画面をふさぐ映像と見なして
// 下の映像を描かず真っ黒になっていた（2026-11-18 スヤさん2本目 0:50〜1:02）。

type RegionLike = {
  asset_id?: string | null;
  text?: string | null;
  timeline_start: number;
  style?: unknown;
};

export type Rect = { x: number; y: number; w: number; h: number };

type RegionFields = {
  region?: { x?: number; y?: number; width?: number; height?: number } | null;
  region_keys?: Array<{ t: number; x: number; y: number; w?: number; h?: number }> | null;
  effect_strength?: number | null;
  effect_opacity?: number | null;
  effect_color?: string | null;
  effect_rot?: number | null;
};

export const REGION_STYLE_NAMES: Record<string, string> = {
  mosaic: 'モザイク',
  gaussian: 'ぼかし',
  soft: 'ぼかし',
  solid: '単色',
  marker: 'マーカー',
  spotlight: 'スポットライト',
  frame: '枠',
  zoom: 'ズーム',
};

function fields(c: RegionLike): RegionFields {
  return c as unknown as RegionFields;
}

export function regionStyle(c: RegionLike): string {
  return typeof c.style === 'string' ? c.style.toLowerCase() : '';
}

function baseRect(c: RegionLike): Rect | null {
  const r = fields(c).region;
  if (!r || typeof r !== 'object') return null;
  const w = Number(r.width) || 0;
  const h = Number(r.height) || 0;
  if (!(w > 1e-4 && h > 1e-4)) return null;
  return { x: Number(r.x) || 0, y: Number(r.y) || 0, w: Math.min(1, w), h: Math.min(1, h) };
}

/** 範囲の効果のクリップか（書き出しと同じ決め方）。 */
export function isRegionEffect(c: RegionLike): boolean {
  if (c.asset_id) return false;
  if (typeof c.text === 'string' && c.text.trim()) return false;
  if (regionStyle(c) === 'note') return false;
  return baseRect(c) != null;
}

/** タイムラインに出す名前（モザイク・ぼかし…）。 */
export function regionLabel(c: RegionLike): string {
  return REGION_STYLE_NAMES[regionStyle(c)] || 'ぼかし';
}

/** 時刻 t（タイムラインの秒）の範囲。region_keys（クリップの頭からの秒）を直線でつなぐ（native の Clip::region_at と同じ）。 */
export function regionAt(c: RegionLike, t: number): Rect | null {
  const b = baseRect(c);
  if (!b) return null;
  const keys = fields(c).region_keys;
  if (!Array.isArray(keys) || !keys.length) return b;
  const ks = keys
    .filter((k) => k && Number.isFinite(Number(k.t)) && Number.isFinite(Number(k.x)) && Number.isFinite(Number(k.y)))
    .map((k) => ({ t: Number(k.t), x: Number(k.x), y: Number(k.y), w: k.w != null ? Number(k.w) : b.w, h: k.h != null ? Number(k.h) : b.h }))
    .sort((a, z) => a.t - z.t);
  if (!ks.length) return b;
  const rel = t - Number(c.timeline_start || 0);
  if (rel <= ks[0].t) return { x: ks[0].x, y: ks[0].y, w: ks[0].w, h: ks[0].h };
  const last = ks[ks.length - 1];
  if (rel >= last.t) return { x: last.x, y: last.y, w: last.w, h: last.h };
  const i = ks.findIndex((k) => k.t > rel);
  const a = ks[i - 1];
  const z = ks[i];
  const f = Math.max(0, Math.min(1, (rel - a.t) / Math.max(1e-9, z.t - a.t)));
  return { x: a.x + (z.x - a.x) * f, y: a.y + (z.y - a.y) * f, w: a.w + (z.w - a.w) * f, h: a.h + (z.h - a.h) * f };
}

let scratch: HTMLCanvasElement | null = null;
let small: HTMLCanvasElement | null = null;
function canvasEl(which: 'scratch' | 'small', w: number, h: number): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null;
  let c = which === 'scratch' ? scratch : small;
  if (!c) {
    c = document.createElement('canvas');
    if (which === 'scratch') scratch = c; else small = c;
  }
  if (c.width !== w) c.width = w;
  if (c.height !== h) c.height = h;
  return c;
}

/**
 * 効果を ctx の今の中身（その段より下の絵）にかける。ctx は (ps,0,0,ps,0,0) の変換で、w×h は CSS の大きさ。
 * 強さの単位は書き出しと同じ 1080 の高さの画素（モザイクのます目・ぼかしの半径・枠の太さ）。
 */
export function drawRegionEffect(ctx: CanvasRenderingContext2D, c: RegionLike, t: number, w: number, h: number): void {
  const rg = regionAt(c, t);
  if (!rg) return;
  const f = fields(c);
  const style = regionStyle(c);
  const canvas = ctx.canvas;
  const W = canvas.width;
  const H = canvas.height;
  if (!(W > 0 && H > 0 && w > 0 && h > 0)) return;
  const unit = H / 1080; // 書き出しの1画素 → この canvas の画素
  const opacity = f.effect_opacity != null ? Math.max(0, Math.min(1, Number(f.effect_opacity))) : 1;
  const rot = Number(f.effect_rot) || 0;
  // 範囲（この canvas の画素）。画面の外にはみ出した分は切る
  const rx = rg.x * W;
  const ry = rg.y * H;
  const rw = rg.w * W;
  const rh = rg.h * H;
  const x0 = Math.max(0, Math.floor(rx));
  const y0 = Math.max(0, Math.floor(ry));
  const x1 = Math.min(W, Math.ceil(rx + rw));
  const y1 = Math.min(H, Math.ceil(ry + rh));
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.filter = 'none';
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
  try {
    if (style === 'spotlight' || style === 'marker') {
      // 範囲の外を沈める（スポットライトは不透明度が沈み量、マーカーは外を少しだけ沈めて範囲に黄色を塗る）
      const dim = style === 'spotlight' ? Math.max(0.05, Math.min(0.95, 1 - 0.55 * opacity)) : 0.85;
      ctx.beginPath();
      ctx.rect(0, 0, W, H);
      ctx.rect(rx, ry, rw, rh);
      ctx.fillStyle = `rgba(0,0,0,${1 - dim})`;
      ctx.fill('evenodd');
      if (style === 'marker' && opacity > 0) {
        ctx.globalAlpha = 0.45 * opacity;
        ctx.fillStyle = f.effect_color || '#ffe14d';
        ctx.globalCompositeOperation = 'multiply';
        ctx.fillRect(rx, ry, rw, rh);
      }
      return;
    }
    if (style === 'frame') {
      const th = Math.max(1, Math.min(24, Number(f.effect_strength) || 4)) * unit;
      ctx.translate(rx + rw / 2, ry + rh / 2);
      if (rot) ctx.rotate((rot * Math.PI) / 180);
      ctx.globalAlpha = opacity;
      ctx.fillStyle = f.effect_color || '#ffe14d';
      const hx = rw / 2;
      const hy = rh / 2;
      ctx.fillRect(-hx - th, -hy - th, rw + 2 * th, th);
      ctx.fillRect(-hx - th, hy, rw + 2 * th, th);
      ctx.fillRect(-hx - th, -hy, th, rh);
      ctx.fillRect(hx, -hy, th, rh);
      return;
    }
    if (style === 'solid') {
      ctx.translate(rx + rw / 2, ry + rh / 2);
      if (rot) ctx.rotate((rot * Math.PI) / 180);
      ctx.globalAlpha = opacity;
      ctx.fillStyle = f.effect_color || '#000000';
      ctx.fillRect(-rw / 2, -rh / 2, rw, rh);
      return;
    }
    if (style === 'zoom') {
      // 範囲の中心へ寄る（画面全体を z 倍に）
      const z = Math.max(1.1, Math.min(3, Number(f.effect_strength) || 1.6));
      const cx = rx + rw / 2;
      const cy = ry + rh / 2;
      const sw = W / z;
      const sh = H / z;
      const sx = Math.max(0, Math.min(W - sw, cx - sw / 2));
      const sy = Math.max(0, Math.min(H - sh, cy - sh / 2));
      const sc = canvasEl('scratch', W, H);
      if (!sc) return;
      const s2 = sc.getContext('2d');
      if (!s2) return;
      s2.clearRect(0, 0, W, H);
      s2.drawImage(canvas, 0, 0);
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(sc, sx, sy, sw, sh, 0, 0, W, H);
      return;
    }
    if (x1 - x0 < 1 || y1 - y0 < 1) return;
    const bw = x1 - x0;
    const bh = y1 - y0;
    if (style.includes('mosaic')) {
      // ます目の大きさ = effect_strength（既定14）。ます目ごとの平均の色で塗る（書き出しの apply_mosaic）
      const cell = Math.max(2, Math.min(64, Number(f.effect_strength) || 14)) * unit;
      const cx = Math.max(2, Math.round(rw / cell));
      const cy = Math.max(2, Math.round(rh / cell));
      const sm = canvasEl('small', cx, cy);
      if (!sm) return;
      const s2 = sm.getContext('2d');
      if (!s2) return;
      s2.imageSmoothingEnabled = true;
      s2.imageSmoothingQuality = 'high';
      s2.clearRect(0, 0, cx, cy);
      s2.drawImage(canvas, rx, ry, rw, rh, 0, 0, cx, cy);
      ctx.beginPath();
      ctx.rect(x0, y0, bw, bh);
      ctx.clip();
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(sm, 0, 0, cx, cy, rx, ry, rw, rh);
      return;
    }
    // ぼかし（gaussian / soft / その他）
    const radius = Math.max(2, Math.min(64, Number(f.effect_strength) || 16)) * unit;
    const pad = Math.ceil(radius * 2);
    const sx = Math.max(0, x0 - pad);
    const sy = Math.max(0, y0 - pad);
    const sw = Math.min(W, x1 + pad) - sx;
    const sh = Math.min(H, y1 + pad) - sy;
    const sc = canvasEl('scratch', sw, sh);
    if (!sc) return;
    const s2 = sc.getContext('2d');
    if (!s2) return;
    s2.clearRect(0, 0, sw, sh);
    s2.drawImage(canvas, sx, sy, sw, sh, 0, 0, sw, sh);
    ctx.beginPath();
    if (rot) {
      ctx.translate(rx + rw / 2, ry + rh / 2);
      ctx.rotate((rot * Math.PI) / 180);
      ctx.rect(-rw / 2, -rh / 2, rw, rh);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
    } else {
      ctx.rect(x0, y0, bw, bh);
    }
    ctx.clip();
    ctx.filter = `blur(${radius}px)`;
    ctx.drawImage(sc, sx, sy);
  } finally {
    ctx.restore();
  }
}
