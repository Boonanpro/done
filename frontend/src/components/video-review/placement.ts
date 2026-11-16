// One set of numbers for where a picture sits — the editor's mirror of app/services/clip_placement.py
// (2026-11-16 本人「編集したことはちゃんと数値にも反映されないと不自然」).
//
//   fit         'cover' | 'contain'  what 100% means (the source covering / fitting the canvas)
//   transform   {scale, x, y}        size (1 = 100%), offset of the picture centre (canvas fractions)
//   crop        mask: fractions of the picture trimmed away
//   shape       cut inscribed in the visible (cropped) picture
//   motion_keys [{t, scale, x, y, ease}]  keyframes (clip-relative). When present they drive
//               scale/x/y; `ease` shapes the move from that key to the next.
//
// A clip with a `position` box or box `transform_keys` is the OLD form (the server converts it on
// the next save); the preview still draws it the old way until then.

export type Ease = 'linear' | 'ease_out' | 'ease_in' | 'ease_in_out' | 'hold';
export const EASES: Array<{ value: Ease; label: string }> = [
  { value: 'linear', label: '一定' },
  { value: 'ease_out', label: 'だんだん遅く' },
  { value: 'ease_in', label: 'だんだん速く' },
  { value: 'ease_in_out', label: 'ゆっくり始めて止まる' },
  { value: 'hold', label: '止めて次で切り替え' },
];
export type MotionKey = { t: number; scale: number; x: number; y: number; ease?: Ease | string };
export type Motion = { scale: number; x: number; y: number };
export type Rect = { x: number; y: number; w: number; h: number };

type PlacedClip = {
  position?: unknown;
  transform_keys?: unknown;
  transform?: { scale?: number; x?: number; y?: number } | null;
  motion_keys?: MotionKey[] | null;
  fit?: string | null;
  crop?: { top?: number; bottom?: number; left?: number; right?: number } | null;
};

export function easeAt(name: string | undefined, f: number): number {
  const v = f < 0 ? 0 : f > 1 ? 1 : f;
  switch (name) {
    case 'ease_out': case 'cubic_out': return 1 - (1 - v) ** 3;
    case 'ease_in': case 'cubic_in': return v ** 3;
    case 'ease_in_out': case 'cubic_in_out': return v < 0.5 ? 4 * v ** 3 : 1 - (-2 * v + 2) ** 3 / 2;
    case 'hold': return v < 1 ? 0 : 1;
    default: return v;
  }
}

export function isOneForm(clip: PlacedClip): boolean {
  const p = clip.position as unknown;
  const tk = clip.transform_keys as unknown;
  return !(p && typeof p === 'object') && !(Array.isArray(tk) && tk.length > 0);
}

export function sortedKeys(clip: PlacedClip): MotionKey[] {
  const ks = Array.isArray(clip.motion_keys) ? clip.motion_keys.filter((k) => k && Number.isFinite(k.t) && k.scale > 0) : [];
  return [...ks].sort((a, b) => a.t - b.t);
}

export function staticMotion(clip: PlacedClip): Motion {
  const tf = clip.transform || {};
  const s = Number(tf.scale);
  return { scale: s > 0 ? s : 1, x: Number(tf.x) || 0, y: Number(tf.y) || 0 };
}

/** scale / x / y at clip-relative time `rel` (keys win over the static transform). */
export function motionAt(clip: PlacedClip, rel: number): Motion {
  const ks = sortedKeys(clip);
  if (!ks.length) return staticMotion(clip);
  if (rel <= ks[0].t) return { scale: ks[0].scale, x: ks[0].x, y: ks[0].y };
  for (let i = 1; i < ks.length; i += 1) {
    const a = ks[i - 1];
    const b = ks[i];
    if (rel < b.t) {
      const e = easeAt(String(a.ease || 'linear'), (rel - a.t) / Math.max(1e-9, b.t - a.t));
      return { scale: a.scale + (b.scale - a.scale) * e, x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e };
    }
  }
  const z = ks[ks.length - 1];
  return { scale: z.scale, x: z.x, y: z.y };
}

/** The picture's size at 100%, px. */
export function baseSize(sw: number, sh: number, W: number, H: number, fit?: string | null): { w: number; h: number } {
  const k = fit === 'contain' ? Math.min(W / sw, H / sh) : Math.max(W / sw, H / sh);
  return { w: sw * k, h: sh * k };
}

/** Where the whole (uncropped) picture is drawn, px. */
export function pictureRect(clip: PlacedClip, m: Motion, sw: number, sh: number, W: number, H: number): Rect {
  const b = baseSize(sw, sh, W, H, clip.fit);
  const w = b.w * m.scale;
  const h = b.h * m.scale;
  return { x: W / 2 + m.x * W - w / 2, y: H / 2 + m.y * H - h / 2, w, h };
}

export function cropOf(clip: PlacedClip): { left: number; top: number; right: number; bottom: number } {
  const c = clip.crop || {};
  const f = (v: unknown) => Math.max(0, Math.min(0.95, Number(v) || 0));
  return { left: f(c.left), top: f(c.top), right: f(c.right), bottom: f(c.bottom) };
}

/** What shows of the picture after the crop mask, px (not clipped to the canvas). */
export function visibleRect(clip: PlacedClip, P: Rect): Rect {
  const c = cropOf(clip);
  return { x: P.x + P.w * c.left, y: P.y + P.h * c.top, w: P.w * (1 - c.left - c.right), h: P.h * (1 - c.top - c.bottom) };
}

/** Keys after setting the value at clip time `rel`: replaces a key within half a frame, else inserts one. */
export function setKeyAt(keys: MotionKey[], rel: number, m: Motion, fps = 30): MotionKey[] {
  const tol = 0.5 / fps;
  const t = Number(rel.toFixed(4));
  const out = keys.map((k) => ({ ...k }));
  const hit = out.findIndex((k) => Math.abs(k.t - t) <= tol);
  const val = { scale: Number(m.scale.toFixed(4)), x: Number(m.x.toFixed(4)), y: Number(m.y.toFixed(4)) };
  if (hit >= 0) out[hit] = { ...out[hit], ...val };
  else {
    // a new key keeps the curve the move through this time had
    const prev = [...out].reverse().find((k) => k.t < t);
    out.push({ t, ...val, ease: (prev?.ease as Ease) || 'linear' });
  }
  return out.sort((a, b) => a.t - b.t);
}
