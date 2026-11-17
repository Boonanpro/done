// 映像の段の上下 = 画面の前後（2026-11-18 本人「上の段のクリップが前、下の段はその後ろ。テロップに限らず必ず守る仕組みに」）。
// エディターが段を並べる時（computeClipLanes）、プレビューが重ねる時（timeline-preview）、書き出しが重ねる時
// （app/api/production_asset_routes.py の visual_lane）は、全部この1つの決め方を使う。数字が大きい段ほど前。

type LaneClip = { layer?: number | null; track?: string | null; composition?: string | null };

/** 映像の側のクリップが乗っている段（大きいほど前）。visualIndex = 音声以外のトラックの中での順番（隠した段も数える）。 */
export function visualLane(trackType: string | null | undefined, clip: LaneClip, visualIndex: number): number {
  const own = clip.layer;
  if (typeof own === 'number' && Number.isFinite(own)) return own;
  if (trackType === 'caption' || clip.track === 'caption') return Math.max(2, visualIndex);
  if (trackType === 'effect') return 3;
  if (trackType === 'overlay') return 1;
  if (clip.composition === 'pip' || clip.composition === 'overlay') return 1;
  return visualIndex;
}

/** 前後の順に並べる（後ろ→前）。同じ段の中は元の並び順のまま。 */
export function byLane<T>(items: T[], laneOf: (it: T) => number): T[] {
  return items.map((it, i) => ({ it, i, l: laneOf(it) })).sort((a, b) => a.l - b.l || a.i - b.i).map((x) => x.it);
}

export type StackKind = 'pic' | 'scene' | 'cap';
export type StackBand = { kind: StackKind; ids: Set<string>; canvas: number };

/** プレビューで重ねる層を、後ろ→前の順に作る。絵と映像は canvas（canvas 番号 0 が一番下の黒い canvas）、
 *  場面とテロップは HTML の層。段が大きい物ほど後ろの層に入り、前に出る。同じ段の物は同じ時刻に重ならない
 *  （1つの段に同じ時刻の物は置けない）ので、層が増えないよう 絵→場面→テロップ の順にまとめる。 */
export function stackBands(entries: Array<{ kind: StackKind; layer: number; id: string }>): { bands: StackBand[]; canvasOf: Map<string, number>; canvases: number } {
  const rank: Record<StackKind, number> = { pic: 0, scene: 1, cap: 2 };
  const sorted = entries.map((e, i) => ({ ...e, i })).sort((a, b) => a.layer - b.layer || rank[a.kind] - rank[b.kind] || a.i - b.i);
  const bands: StackBand[] = [{ kind: 'pic', ids: new Set(), canvas: 0 }];
  let canvases = 1;
  for (const e of sorted) {
    const last = bands[bands.length - 1];
    if (last.kind === e.kind) { last.ids.add(e.id); continue; }
    bands.push({ kind: e.kind, ids: new Set([e.id]), canvas: e.kind === 'pic' ? canvases++ : -1 });
  }
  const canvasOf = new Map<string, number>();
  for (const b of bands) if (b.kind === 'pic') for (const id of b.ids) canvasOf.set(id, b.canvas);
  return { bands, canvasOf, canvases };
}
