/**
 * グラフ（Chart）の形の計算。PC（components/chat/chat-shapes.tsx の SVG）とスマホ（mobile/chat-shapes.tsx の
 * react-native-svg）が同じ計算結果を描くので、折れ線・棒・目盛り・負の値・欠けた値の見え方が同じになる（2026-10-23。
 * それまでスマホは折れ線も棒で描き、負の値を絶対値で描いていた）。写しは frontend/scripts/sync-mobile-chat-shapes.mjs が作る。
 *
 * - 縦の範囲は 0 を必ず含む（棒は 0 の線から上下に伸びる。折れ線も同じ目盛り）。目盛りは切りのいい刻みで4〜6本
 * - 数値でない・まだ届いていない値は null。折れ線はそこで線を切り、棒は描かない（0 にすると存在しない下降が見える）
 * - 横の名前が重なる時は間引く（全部の名前の位置は labels に残す）
 * 依存なし。
 */

export type ChartKind = 'line' | 'bar';
export type ChartSeriesStyle = { tone: 'primary' | 'muted'; opacity: number; dash: string | null };

/** 系列ごとの描き方（色の濃さと線の種類で分ける。色そのものは画面の配色の primary / muted） */
export const SERIES_STYLE: readonly ChartSeriesStyle[] = [
  { tone: 'primary', opacity: 1, dash: null },
  { tone: 'primary', opacity: 0.55, dash: '6 3' },
  { tone: 'primary', opacity: 0.3, dash: '2 3' },
  { tone: 'muted', opacity: 0.8, dash: '4 2' },
];

export const CHART_HEIGHT = 220;
const PAD = { top: 10, right: 10, bottom: 24, left: 8 };
const LABEL_FONT = 11;

export type ChartInputLoose = { kind?: unknown; labels?: unknown; series?: unknown; unit?: unknown; title?: unknown };

export type ChartGeometry = {
  kind: ChartKind;
  width: number;
  height: number;
  plot: { x: number; y: number; w: number; h: number };
  /** 横線と左の目盛りの文字 */
  yTicks: { y: number; label: string; zero: boolean }[];
  /** 下の名前（間引いた後） */
  xLabels: { x: number; label: string }[];
  zeroY: number;
  series: {
    name: string;
    style: ChartSeriesStyle;
    /** 折れ線: 欠けた値で切った線（SVG の path の d） */
    path: string;
    points: { x: number; y: number; value: number; label: string }[];
    bars: { x: number; y: number; w: number; h: number; value: number; label: string }[];
  }[];
  /** 値の書き方（単位つき） */
  format: (v: number) => string;
};

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** 切りのいい刻み（1・2・2.5・5 ×10^n） */
function niceStep(range: number, count: number): number {
  const raw = range / Math.max(1, count);
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * p) return m * p;
  return 10 * p;
}

/** 目盛りの文字（大きい数は「万」「億」で縮める） */
function tickLabel(v: number, unit: string): string {
  const a = Math.abs(v);
  const s = a >= 1e8 ? `${+(v / 1e8).toFixed(1)}億` : a >= 1e4 ? `${+(v / 1e4).toFixed(1)}万` : `${+v.toFixed(2)}`;
  return `${s}${unit}`;
}

/** 文字の幅の目安（全角は2、半角は1文字ぶん × 文字の大きさの0.6） */
export function textWidth(s: string, font = LABEL_FONT): number {
  let n = 0;
  for (const ch of s) n += ch.charCodeAt(0) > 0xff ? 1 : 0.6;
  return n * font;
}

export function chartGeometry(input: ChartInputLoose, width: number, height = CHART_HEIGHT): ChartGeometry {
  const kind: ChartKind = input.kind === 'line' ? 'line' : 'bar';
  const unit = typeof input.unit === 'string' ? input.unit : '';
  const labels = (Array.isArray(input.labels) ? input.labels : []).map((l) => (typeof l === 'string' ? l : String(l ?? '')));
  const rawSeries = (Array.isArray(input.series) ? input.series : []).filter(
    (s): s is { name?: unknown; values?: unknown } => !!s && typeof s === 'object' && Array.isArray((s as { values?: unknown }).values),
  );
  const series = rawSeries.map((s, i) => ({
    name: typeof s.name === 'string' && s.name.trim() ? s.name : `系列${i + 1}`,
    values: labels.map((_, j) => num((s.values as unknown[])[j])),
  }));
  const format = (v: number) => `${v.toLocaleString('ja-JP')}${unit}`;

  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  let lo = Math.min(0, ...all);
  let hi = Math.max(0, ...all);
  if (lo === hi) hi = lo + 1;
  const step = niceStep(hi - lo, 4);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));

  const tickTexts = ticks.map((t) => tickLabel(t, unit));
  const axisW = Math.ceil(Math.max(...tickTexts.map((t) => textWidth(t)))) + 8;
  const plot = { x: PAD.left + axisW, y: PAD.top, w: Math.max(10, width - PAD.left - axisW - PAD.right), h: Math.max(10, height - PAD.top - PAD.bottom) };
  const yOf = (v: number) => plot.y + plot.h - ((v - lo) / (hi - lo)) * plot.h;
  const zeroY = yOf(0);
  const band = labels.length ? plot.w / labels.length : plot.w;
  const xOf = (i: number) => plot.x + band * (i + 0.5);

  // 名前が重ならない間隔で間引く
  const widest = Math.max(1, ...labels.map((l) => textWidth(l)));
  const every = Math.max(1, Math.ceil((widest + 6) / Math.max(1, band)));
  const xLabels = labels.map((label, i) => ({ x: xOf(i), label })).filter((_, i) => i % every === 0);

  const groupW = Math.min(band * 0.7, 48 * series.length);
  const barW = series.length ? groupW / series.length : 0;
  const out = series.map((s, si) => {
    const style = SERIES_STYLE[si % SERIES_STYLE.length];
    const points: ChartGeometry['series'][number]['points'] = [];
    let path = '';
    let pen = false;
    s.values.forEach((v, i) => {
      if (v === null) { pen = false; return; }
      const x = xOf(i);
      const y = yOf(v);
      points.push({ x, y, value: v, label: labels[i] });
      path += `${pen ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)} `;
      pen = true;
    });
    const bars = s.values.flatMap((v, i) => {
      if (v === null) return [];
      const x = xOf(i) - groupW / 2 + barW * si;
      const y = Math.min(yOf(v), zeroY);
      return [{ x, y, w: Math.max(1, barW - 2), h: Math.max(1, Math.abs(yOf(v) - zeroY)), value: v, label: labels[i] }];
    });
    return { name: s.name, style, path: path.trim(), points, bars };
  });

  return {
    kind, width, height, plot, zeroY, format,
    yTicks: ticks.map((t, i) => ({ y: yOf(t), label: tickTexts[i], zero: t === 0 })),
    xLabels,
    series: out,
  };
}
