/**
 * clip.grade for the canvas preview, with the SAME maths as the export
 * (production_asset_routes._grade_filter / the native compositor's apply_grade):
 *   c = clamp(c * 2^ev); c = (c - pivot) * contrast + pivot; c = mix(luma(c), c, sat);
 *   c *= (1 + .22 temp + .10 tint, 1 - .12 tint, 1 - .22 temp + .10 tint); clamp.
 * Drawn as an SVG filter (sRGB maths) referenced from ctx.filter. Before this the preview
 * ignored the grade, so a graded clip looked different in the editor and in the export.
 */
const LUMA = [0.2126, 0.7152, 0.0722];
const PIVOT = 0.4135;
const cache = new Map<string, string>();
let svg: SVGSVGElement | null = null;

const num = (v: unknown, d: number) => { const n = Number(v); return v != null && Number.isFinite(n) ? n : d; };

export function gradeFilter(grade: unknown): string {
  if (!grade || typeof grade !== 'object' || typeof document === 'undefined') return 'none';
  const g = grade as Record<string, unknown>;
  const ev = num(g.ev, 0), ct = Math.max(0, num(g.contrast, 1)), sat = Math.max(0, num(g.sat, 1));
  const temp = num(g.temp, 0), tint = num(g.tint, 0);
  if (Math.abs(ev) < 1e-4 && Math.abs(ct - 1) < 1e-4 && Math.abs(sat - 1) < 1e-4 && Math.abs(temp) < 1e-4 && Math.abs(tint) < 1e-4) return 'none';
  const key = [ev, ct, sat, temp, tint].map((v) => v.toFixed(4)).join('_');
  const hit = cache.get(key);
  if (hit) return hit;
  const k = 2 ** Math.max(-8, Math.min(8, ev));
  const gains = [1 + 0.22 * temp + 0.1 * tint, 1 - 0.12 * tint, 1 - 0.22 * temp + 0.1 * tint];
  const rows: number[] = [];
  for (let i = 0; i < 3; i += 1) {
    for (let j = 0; j < 3; j += 1) rows.push(gains[i] * ct * ((1 - sat) * LUMA[j] + (i === j ? sat : 0)));
    rows.push(0, gains[i] * PIVOT * (1 - ct));
  }
  rows.push(0, 0, 0, 1, 0);
  const id = `dan-grade-${cache.size}`;
  if (!svg) {
    svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '0'); svg.setAttribute('height', '0');
    svg.style.position = 'absolute';
    svg.setAttribute('aria-hidden', 'true');
    document.body.appendChild(svg);
  }
  const f = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
  f.setAttribute('id', id);
  f.setAttribute('color-interpolation-filters', 'sRGB');
  const ns = 'http://www.w3.org/2000/svg';
  const ctf = document.createElementNS(ns, 'feComponentTransfer');
  for (const ch of ['feFuncR', 'feFuncG', 'feFuncB']) {
    const fn = document.createElementNS(ns, ch);
    fn.setAttribute('type', 'linear'); fn.setAttribute('slope', String(k)); fn.setAttribute('intercept', '0');
    ctf.appendChild(fn);
  }
  const cm = document.createElementNS(ns, 'feColorMatrix');
  cm.setAttribute('type', 'matrix');
  cm.setAttribute('values', rows.map((v) => v.toFixed(6)).join(' '));
  f.appendChild(ctf); f.appendChild(cm);
  svg.appendChild(f);
  const url = `url(#${id})`;
  cache.set(key, url);
  return url;
}
