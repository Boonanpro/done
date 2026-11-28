// タイムラインの基本の編集（2026-11-25 本人「Premiere や DaVinci のような一通りの編集機能を、直感的に不自由なく」）。
// エディターの部品から切り離した、中身を変えるだけの決め方。node --experimental-strip-types で試験できる。
//
// - 置く・動かす・貼る時は、重なる相手を消さずに空いている段へ逃がす（Final Cut と同じ）。上書きは Ctrl/⌘ を押した時だけ。
// - 割り込む（挿入）: 時刻 P で全部の段を L 秒後ろへずらし、メインのクリップが P をまたいでいれば P で切る。
// - ロール・スリップ・スライド（Premiere・DaVinci の道具）と、1コマずつ動かす時に隣に当たる所。

import { insertRange, srcAdvance, withDuration, type RAnn, type RClip, type RLane, type RSeq } from './ripple-edit.ts';

const EPS = 0.01;
const r2 = (v: number) => Number(v.toFixed(2));
const r3 = (v: number) => Number(v.toFixed(3));

export type OClip = RClip & { layer?: number | null; link_id?: string | null; asset_id?: string | null };
export type Placement = { id: string; zone: 'visual' | 'audio'; layer: number; start: number; end: number };

const allClips = (seq: RSeq): OClip[] => (seq.tracks || []).flatMap((t) => (t.clips || []) as OClip[]);
const hasSource = (c: RClip) => Number.isFinite(c.source_end as number) && Number(c.source_end) > Number(c.source_start || 0) + 1e-6;

/** 音声の段は詰めて並べる作り（computeClipLanes）なので、動かす前に今の段を全部の音声クリップに書いて止める。 */
export function pinAudioLayers<S extends RSeq>(seq: S, lanes: Map<string, RLane>): S {
  return {
    ...seq,
    tracks: (seq.tracks || []).map((t) => ({
      ...t,
      clips: (t.clips || []).map((c) => {
        const l = lanes.get(String(c.id));
        return t.type === 'audio' && l && !Number.isFinite((c as OClip).layer as number) ? { ...c, layer: l.layer } : c;
      }),
    })),
  };
}

const laneKey = (lanes: Map<string, RLane>, id: string, layer?: number | null) => {
  const l = lanes.get(String(id));
  return `${l?.zone || 'visual'}#${layer ?? l?.layer ?? 0}`;
};

/** 動かしたクリップ（moved: id → 新しい値）を置き、同じ段で重なった動かしていないクリップを切り詰める・消す・2つに分ける
 *  （上書き。Ctrl/⌘ を押して動かした時と、空いている段へ逃がした後の仕上げ）。 */
export function overwriteMoved<S extends RSeq>(snap: S, moved: Map<string, Partial<OClip>>, lanes: Map<string, RLane>): S {
  const byId = new Map(allClips(snap).map((c) => [String(c.id), c]));
  const targets = Array.from(moved.entries()).map(([id, f]) => {
    const o = byId.get(id)!;
    return { id, lane: laneKey(lanes, id, f.layer ?? undefined), as: Number(f.timeline_start ?? o?.timeline_start), ae: Number(f.timeline_end ?? o?.timeline_end) };
  });
  const tracks = (snap.tracks || []).map((track) => {
    const out: RClip[] = [];
    for (const c0 of track.clips || []) {
      const cl = lanes.get(String(c0.id));
      const c = (track.type === 'audio' && cl && !Number.isFinite((c0 as OClip).layer as number) ? { ...c0, layer: cl.layer } : c0) as OClip;
      const mv = moved.get(String(c.id));
      if (mv) { out.push({ ...c, ...mv, ...(cl && mv.layer === undefined ? { layer: cl.layer } : {}) }); continue; }
      const lane = laneKey(lanes, String(c.id));
      const t = targets.find((x) => x.lane === lane && x.id !== c.id && x.ae > c.timeline_start + 0.001 && x.as < c.timeline_end - 0.001);
      if (!t) { out.push(c); continue; }
      const bs = c.timeline_start, be = c.timeline_end;
      const av = Number.isFinite(c.source_end as number);
      if (t.as <= bs + 0.001 && t.ae >= be - 0.001) continue; // 全部隠れた → 消す
      if (t.as <= bs + 0.001) {
        out.push({ ...c, timeline_start: r2(t.ae), ...(av ? { source_start: r2(Number(c.source_start || 0) + srcAdvance(c, t.ae - bs)) } : {}) });
      } else if (t.ae >= be - 0.001) {
        out.push({ ...c, timeline_end: r2(t.as), ...(av ? { source_end: r2(Number(c.source_end || 0) - srcAdvance(c, be - t.as)) } : {}) });
      } else {
        out.push({ ...c, timeline_end: r2(t.as), ...(av ? { source_end: r2(Number(c.source_start || 0) + srcAdvance(c, t.as - bs)) } : {}) });
        out.push({ ...c, id: `${c.id}__r`, timeline_start: r2(t.ae), ...(av ? { source_start: r2(Number(c.source_start || 0) + srcAdvance(c, t.ae - bs)) } : {}) });
      }
    }
    return { ...track, clips: out };
  });
  return withDuration({ ...snap, tracks });
}

/** 動かす・置くクリップが同じ段の別の物と重なるなら、重ならない段へ逃がす。映像は上（前）へ、音声は下へ探し、
 *  無ければ新しい段になる。fixed のクリップは段を変えない（端を伸ばしているクリップなど）。locked は使えない段
 *  （"visual-3" の形）。extra は段に並んでいるクリップ以外の物（モザイク・指示の箱）。返すのは段を足した moved。 */
export function resolveFree<S extends RSeq>(
  snap: S, moved: Map<string, Partial<OClip>>, lanes: Map<string, RLane>,
  opts: { fixed?: Set<string>; locked?: Set<string>; extra?: Placement[] } = {},
): Map<string, Partial<OClip>> {
  const byId = new Map(allClips(snap).map((c) => [String(c.id), c]));
  const placed: Placement[] = [...(opts.extra || [])];
  for (const c of byId.values()) {
    if (moved.has(String(c.id))) continue;
    const l = lanes.get(String(c.id));
    if (l) placed.push({ id: String(c.id), zone: l.zone, layer: l.layer, start: c.timeline_start, end: c.timeline_end });
  }
  const items = Array.from(moved.entries()).map(([id, f]) => {
    const o = byId.get(id);
    const l = lanes.get(id) || { zone: 'visual' as const, layer: Number(o?.layer ?? 0) };
    return { id, zone: l.zone, layer: Number(f.layer ?? l.layer), start: Number(f.timeline_start ?? o?.timeline_start ?? 0), end: Number(f.timeline_end ?? o?.timeline_end ?? 0) };
  });
  const out = new Map(moved);
  const collides = (it: { id: string; zone: string; start: number; end: number }, L: number) =>
    !!opts.locked?.has(`${it.zone}-${L}`) ||
    placed.some((p) => p.id !== it.id && p.zone === it.zone && p.layer === L && p.end > it.start + EPS && p.start < it.end - EPS);
  // 段を変えないクリップを先に置き、残りを下の段から順に置く
  const order = [...items.filter((it) => opts.fixed?.has(it.id)), ...items.filter((it) => !opts.fixed?.has(it.id)).sort((p, q) => p.layer - q.layer || p.start - q.start)];
  for (const it of order) {
    let L = it.layer;
    if (!opts.fixed?.has(it.id)) {
      let guard = 0;
      while (collides(it, L) && guard++ < 200) L += 1;
    }
    placed.push({ ...it, layer: L });
    if (L !== it.layer || Number.isFinite(moved.get(it.id)?.layer as number) || it.zone === 'audio') out.set(it.id, { ...moved.get(it.id), layer: L });
  }
  return out;
}

/** 時刻 t をまたいでいる pick のクリップを t で2つに切る。右側には新しい id（と組ごとの新しい link_id）を付ける。 */
export function splitAt<S extends RSeq>(seq: S, t: number, pick: (c: OClip) => boolean, newId: () => string): S {
  const rightLink = new Map<string, string>();
  let cut = 0;
  const tracks = (seq.tracks || []).map((track) => {
    const out: RClip[] = [];
    for (const c0 of track.clips || []) {
      const c = c0 as OClip;
      if (!(pick(c) && t > c.timeline_start + 0.05 && t < c.timeline_end - 0.05)) { out.push(c); continue; }
      cut += 1;
      const d = t - c.timeline_start;
      const av = Number.isFinite(c.source_end as number);
      let link: string | undefined;
      if (c.link_id) { link = rightLink.get(c.link_id); if (!link) { link = `lk_${newId()}`; rightLink.set(c.link_id, link); } }
      const at = r3(Number(c.source_start || 0) + srcAdvance(c, d));
      const keys = c.motion_keys && c.motion_keys.length ? { motion_keys: c.motion_keys.map((k) => ({ ...k, t: Number((k.t - d).toFixed(4)) })) } : {};
      out.push({ ...c, timeline_end: r2(t), ...(av ? { source_end: at } : {}) });
      out.push({ ...c, id: `${String(c.id).split('__')[0]}__s_${newId()}`, timeline_start: r2(t), ...(av ? { source_start: at } : {}), ...(link ? { link_id: link } : {}), ...keys });
    }
    return { ...track, clips: out };
  });
  return cut ? { ...seq, tracks } : seq;
}

/** 時刻 P に L 秒の場所を空ける（割り込み）。P をまたぐメインのクリップは相方と一緒に P で切り、P から後ろの物を
 *  全部の段で L 秒後ろへずらす。BGM のように P をまたいで流れている物はそのまま。 */
export function insertBlock<S extends RSeq, A extends RAnn>(
  seq: S, anns: A[], P: number, L: number, lanes: Map<string, RLane>, mainLayer: number | null, newId: () => string,
): { seq: S; anns: A[]; lanes: Map<string, RLane> } {
  const isMain = (c: OClip) => { const l = lanes.get(String(c.id)); return l?.zone === 'visual' && l.layer === mainLayer; };
  const crossing = allClips(seq).filter((c) => isMain(c) && P > c.timeline_start + 0.05 && P < c.timeline_end - 0.05);
  const links = new Set(crossing.map((c) => c.link_id).filter((x): x is string => !!x));
  const ids = new Set(crossing.map((c) => String(c.id)));
  let s = splitAt(seq, P, (c) => ids.has(String(c.id)) || (!!c.link_id && links.has(c.link_id)), newId);
  // 切った右側も元と同じ段に並べる
  const lanes2 = new Map(lanes);
  for (const c of allClips(s)) {
    if (lanes2.has(String(c.id))) continue;
    const base = String(c.id).split('__s_')[0];
    const l = lanes.get(base);
    if (l) lanes2.set(String(c.id), l);
  }
  const res = insertRange(s, anns, P, L, new Set(), lanes2, mainLayer);
  s = res.seq;
  return { seq: s, anns: res.anns, lanes: lanes2 };
}

/** つなぎ目（全部のクリップの頭と終わり、0）。↑↓ で前後のつなぎ目へ飛ぶのに使う。 */
export function editPoints(seq: RSeq, skip?: (c: OClip) => boolean): number[] {
  const pts = new Set<number>([0]);
  for (const c of allClips(seq)) {
    if (skip?.(c)) continue;
    pts.add(r3(c.timeline_start));
    pts.add(r3(c.timeline_end));
  }
  return Array.from(pts).sort((a, b) => a - b);
}

/** 同じ段の、ids 以外のクリップ（と extra）。 */
function sameLane(seq: RSeq, c: OClip, lanes: Map<string, RLane>, ids: Set<string>, extra: Placement[] = []): Array<{ start: number; end: number }> {
  const l = lanes.get(String(c.id));
  if (!l) return [];
  const out: Array<{ start: number; end: number }> = [];
  for (const o of allClips(seq)) {
    if (ids.has(String(o.id))) continue;
    const ol = lanes.get(String(o.id));
    if (ol && ol.zone === l.zone && ol.layer === l.layer) out.push({ start: o.timeline_start, end: o.timeline_end });
  }
  for (const p of extra) if (p.zone === l.zone && p.layer === l.layer) out.push(p);
  return out;
}

/** 端を伸ばせる所（同じ段の隣のクリップの手前まで）。端を伸ばしても隣を消さない。 */
export function trimRoom(seq: RSeq, id: string, lanes: Map<string, RLane>, ids: Set<string>, extra?: Placement[]): { minStart: number; maxEnd: number } {
  const c = allClips(seq).find((x) => String(x.id) === id);
  if (!c) return { minStart: 0, maxEnd: Number.POSITIVE_INFINITY };
  let minStart = 0, maxEnd = Number.POSITIVE_INFINITY;
  for (const o of sameLane(seq, c, lanes, ids, extra)) {
    if (o.end <= c.timeline_start + EPS) minStart = Math.max(minStart, o.end);
    if (o.start >= c.timeline_end - EPS) maxEnd = Math.min(maxEnd, o.start);
  }
  return { minStart, maxEnd };
}

/** ids をまとめて d 秒動かす時に、同じ段の隣に当たらずに動ける分（1コマずつ動かす時）。 */
export function nudgeRoom(seq: RSeq, ids: string[], d: number, lanes: Map<string, RLane>, extra?: Placement[]): number {
  const set = new Set(ids.map(String));
  const cs = allClips(seq).filter((c) => set.has(String(c.id)));
  if (!cs.length) return 0;
  let out = d;
  if (d < 0) out = Math.max(out, -Math.min(...cs.map((c) => c.timeline_start)));
  for (const c of cs) {
    for (const o of sameLane(seq, c, lanes, set, extra)) {
      if (d > 0 && o.start >= c.timeline_end - EPS) out = Math.min(out, o.start - c.timeline_end);
      if (d < 0 && o.end <= c.timeline_start + EPS) out = Math.max(out, o.end - c.timeline_start);
    }
  }
  return Math.abs(out) < 1e-6 ? 0 : out;
}

/** 同じ段で、c の頭（which=start）か終わり（end）にぴったり付いている隣のクリップ。 */
export function touchingNeighbor(seq: RSeq, id: string, which: 'start' | 'end', lanes: Map<string, RLane>): OClip | null {
  const all = allClips(seq);
  const c = all.find((x) => String(x.id) === id);
  const l = c ? lanes.get(String(c.id)) : undefined;
  if (!c || !l) return null;
  const edge = which === 'start' ? c.timeline_start : c.timeline_end;
  return all.find((o) => {
    if (o.id === c.id) return false;
    const ol = lanes.get(String(o.id));
    if (!ol || ol.zone !== l.zone || ol.layer !== l.layer) return false;
    return which === 'start' ? Math.abs(o.timeline_end - edge) < 0.03 : Math.abs(o.timeline_start - edge) < 0.03;
  }) || null;
}

/** 組（同じ link_id）の相手も入れた id。 */
export function withPartners(seq: RSeq, ids: string[]): string[] {
  const all = allClips(seq);
  const set = new Set(ids.map(String));
  const links = new Set(all.filter((c) => set.has(String(c.id)) && c.link_id).map((c) => c.link_id));
  for (const c of all) if (c.link_id && links.has(c.link_id)) set.add(String(c.id));
  return Array.from(set);
}

type DurOf = (c: OClip) => number; // 素材の長さ（秒）。分からない・絵なら Infinity

/** 頭を d 秒動かした時に、素材の外へ出ない・0.1秒より短くならない範囲。 */
function headRoom(c: OClip, _durOf: DurOf): [number, number] {
  const sp = Number(c.speed) > 0 ? Number(c.speed) : 1;
  const lo = c.kind !== 'image' && hasSource(c) ? -Number(c.source_start || 0) / sp : Number.NEGATIVE_INFINITY;
  return [lo, c.timeline_end - c.timeline_start - 0.1];
}
function tailRoom(c: OClip, durOf: DurOf): [number, number] {
  const sp = Number(c.speed) > 0 ? Number(c.speed) : 1;
  const dur = durOf(c);
  const hi = hasSource(c) && Number.isFinite(dur) ? Math.max(0, dur - Number(c.source_end || 0)) / sp : Number.POSITIVE_INFINITY;
  return [-(c.timeline_end - c.timeline_start - 0.1), hi];
}

function patch<S extends RSeq>(seq: S, f: (c: OClip) => Partial<OClip> | null): S {
  return withDuration({
    ...seq,
    tracks: (seq.tracks || []).map((t) => ({ ...t, clips: (t.clips || []).map((c) => { const p = f(c as OClip); return p ? { ...c, ...p } : c; }) })),
  });
}
const moveHead = (c: OClip, d: number): Partial<OClip> => ({
  timeline_start: r2(c.timeline_start + d),
  ...(c.kind !== 'image' && hasSource(c) ? { source_start: r3(Math.max(0, Number(c.source_start || 0) + srcAdvance(c, d))) } : {}),
  ...(c.motion_keys && c.motion_keys.length ? { motion_keys: c.motion_keys.map((k) => ({ ...k, t: Number((k.t - d).toFixed(4)) })) } : {}),
});
const moveTail = (c: OClip, d: number): Partial<OClip> => ({
  timeline_end: r2(c.timeline_end + d),
  ...(hasSource(c) ? { source_end: r3(Number(c.source_end || 0) + srcAdvance(c, d)) } : {}),
});

/** 選んだ何本かの同じ側の端を、まとめて同じだけ動かす（2026-11-26 本人「複数クリップ選択して端を伸び縮みさせる時は
 *  複数クリップまとめてできるようにして」。Premiere・DaVinci と同じ）。組（同じ link_id）は同じだけ動き、組ごとに
 *  素材の外・0.1秒より短く・0秒より前・同じ段の隣の手前で止まる。動かした物の新しい中身を返す。 */
export function multiTrimMoved(
  seq: RSeq, ids: string[], mode: 'start' | 'end', d: number, durOf: DurOf, lanes: Map<string, RLane>, extra?: Placement[],
  overwrite = false, // Ctrl/⌘ の間は隣に当たっても止めない（上書き）
): Map<string, Partial<OClip>> {
  const set = new Set(ids.map(String));
  const cs = allClips(seq).filter((c) => set.has(String(c.id)));
  const groups = new Map<string, OClip[]>();
  for (const c of cs) {
    const k = c.link_id ? `l:${c.link_id}` : `c:${c.id}`;
    groups.set(k, [...(groups.get(k) || []), c]);
  }
  const out = new Map<string, Partial<OClip>>();
  for (const g of groups.values()) {
    let lo = Number.NEGATIVE_INFINITY, hi = Number.POSITIVE_INFINITY;
    for (const c of g) {
      const [a, b] = mode === 'start' ? headRoom(c, durOf) : tailRoom(c, durOf);
      lo = Math.max(lo, a); hi = Math.min(hi, b);
      // 選んだ物どうしも隣として数える（端を伸ばしても、隣の選んだクリップの頭や終わりは動かないので）
      const room = overwrite ? { minStart: 0, maxEnd: Number.POSITIVE_INFINITY } : trimRoom(seq, String(c.id), lanes, new Set(g.map((x) => String(x.id))), extra);
      if (mode === 'start') lo = Math.max(lo, -c.timeline_start, Math.min(room.minStart, c.timeline_start) - c.timeline_start);
      else hi = Math.min(hi, Math.max(room.maxEnd, c.timeline_end) - c.timeline_end);
    }
    const dd = hi < lo ? 0 : Math.min(Math.max(d, lo), hi);
    if (Math.abs(dd) < 1e-6) continue;
    for (const c of g) out.set(String(c.id), mode === 'start' ? moveHead(c, dd) : moveTail(c, dd));
  }
  return out;
}

/** A selected stack can contain a caption with a touching neighbour and a picture
 *  with a free edge. Move those edges together and roll the neighbouring edge. */
export function selectionRoll(
  seq: RSeq, selected: string[], grabbed: string, side: 'start' | 'end', lanes: Map<string, RLane>,
  linked: boolean, locked: (id: string) => boolean, extra: Placement[],
) {
  const expand = (ids: string[]) => linked ? withPartners(seq, ids) : ids;
  const same = new Set(expand(selected));
  const opposite = new Set<string>();
  const seam = touchingNeighbor(seq, grabbed, side, lanes);
  // Grabbing the join between two selected clips edits the shared join only.
  if (seam && same.has(String(seam.id))) {
    for (const id of expand([String(seam.id)])) same.delete(id);
  }
  for (const id of same) {
    const neighbor = touchingNeighbor(seq, id, side, lanes);
    if (neighbor) for (const n of expand([String(neighbor.id)])) opposite.add(n);
  }
  if (!opposite.size) return null;
  const heads = side === 'start' ? same : opposite;
  const tails = side === 'end' ? same : opposite;
  const clips = allClips(seq);
  let min = -Infinity, max = Infinity;
  for (const c of clips) {
    const id = String(c.id);
    if (!heads.has(id) && !tails.has(id)) continue;
    if (locked(id)) { min = 0; max = 0; break; }
    // Ignore only the edges that will move out of the way at this very join.
    if (heads.has(id)) {
      const prev = touchingNeighbor(seq, id, 'start', lanes);
      const ignore = new Set([id]);
      if (prev && tails.has(String(prev.id))) ignore.add(String(prev.id));
      min = Math.max(min, trimRoom(seq, id, lanes, ignore, extra).minStart - c.timeline_start);
    }
    if (tails.has(id)) {
      const next = touchingNeighbor(seq, id, 'end', lanes);
      const ignore = new Set([id]);
      if (next && heads.has(String(next.id))) ignore.add(String(next.id));
      max = Math.min(max, trimRoom(seq, id, lanes, ignore, extra).maxEnd - c.timeline_end);
    }
  }
  return { prevIds: [...tails], nextIds: [...heads], room: { minStart: min, maxEnd: max } };
}

/** ロール: 左のクリップ（と相方）の終わりと右のクリップ（と相方）の頭を一緒に d 秒動かす。全体の長さは変わらない。
 *  動ける範囲に収めた d を返す。 */
export function applyRoll<S extends RSeq>(seq: S, leftIds: string[], rightIds: string[], d: number, durOf: DurOf): { seq: S; d: number } {
  const all = allClips(seq);
  const ls = all.filter((c) => leftIds.includes(String(c.id)));
  const rs = all.filter((c) => rightIds.includes(String(c.id)));
  let lo = Number.NEGATIVE_INFINITY, hi = Number.POSITIVE_INFINITY;
  for (const c of ls) { const [a, b] = tailRoom(c, durOf); lo = Math.max(lo, a); hi = Math.min(hi, b); }
  for (const c of rs) { const [a, b] = headRoom(c, durOf); lo = Math.max(lo, a); hi = Math.min(hi, b); }
  const dd = Math.min(hi, Math.max(lo, d));
  if (!Number.isFinite(dd) || Math.abs(dd) < 1e-6) return { seq, d: 0 };
  const L = new Set(leftIds.map(String)), R = new Set(rightIds.map(String));
  return { seq: patch(seq, (c) => {
    const id = String(c.id);
    if (!L.has(id) && !R.has(id)) return null;
    return { ...(L.has(id) ? moveTail(c, dd) : {}), ...(R.has(id) ? moveHead(c, dd) : {}) };
  }), d: dd };
}

/** スリップ: 置き場所と長さはそのままで、使う素材の区間だけを d 秒ずらす（右へ引くと素材の前の方が見える）。 */
export function applySlip<S extends RSeq>(seq: S, ids: string[], d: number, durOf: DurOf): { seq: S; d: number } {
  const set = new Set(ids.map(String));
  const cs = allClips(seq).filter((c) => set.has(String(c.id)) && hasSource(c));
  if (!cs.length) return { seq, d: 0 };
  // 素材の中で -d だけ進める。頭が0より前・終わりが素材の外に出ない範囲
  let lo = Number.NEGATIVE_INFINITY, hi = Number.POSITIVE_INFINITY;
  for (const c of cs) {
    const sp = Number(c.speed) > 0 ? Number(c.speed) : 1;
    const dur = durOf(c);
    // 素材の中の移動量 m = -d*sp。 source_start + m >= 0、source_end + m <= dur
    hi = Math.min(hi, Number(c.source_start || 0) / sp);
    if (Number.isFinite(dur)) lo = Math.max(lo, -(dur - Number(c.source_end || 0)) / sp);
  }
  const dd = Math.min(hi, Math.max(lo, d));
  if (!Number.isFinite(dd) || Math.abs(dd) < 1e-6) return { seq, d: 0 };
  return {
    seq: patch(seq, (c) => {
      if (!set.has(String(c.id)) || !hasSource(c)) return null;
      const m = -srcAdvance(c, dd);
      return { source_start: r3(Number(c.source_start || 0) + m), source_end: r3(Number(c.source_end || 0) + m) };
    }),
    d: dd,
  };
}

/** スライド: クリップ（ids）を d 秒動かし、前に付いているクリップ（prevIds）の終わりと後ろに付いているクリップ
 *  （nextIds）の頭を同じだけ動かして、隙間も重なりも作らない。前後に付いている物が無い側は、空いている所まで。 */
export function applySlide<S extends RSeq>(
  seq: S, ids: string[], prevIds: string[], nextIds: string[], d: number, durOf: DurOf, room: { minStart: number; maxEnd: number },
): { seq: S; d: number } {
  const all = allClips(seq);
  const set = new Set(ids.map(String)), P = new Set(prevIds.map(String)), N = new Set(nextIds.map(String));
  const cs = all.filter((c) => set.has(String(c.id)));
  if (!cs.length) return { seq, d: 0 };
  let lo = Number.NEGATIVE_INFINITY, hi = Number.POSITIVE_INFINITY;
  for (const c of all.filter((x) => P.has(String(x.id)))) { const [a, b] = tailRoom(c, durOf); lo = Math.max(lo, a); hi = Math.min(hi, b); }
  for (const c of all.filter((x) => N.has(String(x.id)))) { const [a, b] = headRoom(c, durOf); lo = Math.max(lo, a); hi = Math.min(hi, b); }
  const s0 = Math.min(...cs.map((c) => c.timeline_start)), e0 = Math.max(...cs.map((c) => c.timeline_end));
  if (!prevIds.length) lo = Math.max(lo, room.minStart - s0);
  if (!nextIds.length) hi = Math.min(hi, room.maxEnd - e0);
  const dd = Math.min(hi, Math.max(lo, d));
  if (!Number.isFinite(dd) || Math.abs(dd) < 1e-6) return { seq, d: 0 };
  return {
    seq: patch(seq, (c) => {
      const id = String(c.id);
      if (set.has(id)) return { timeline_start: r2(c.timeline_start + dd), timeline_end: r2(c.timeline_end + dd) };
      if (P.has(id)) return moveTail(c, dd);
      if (N.has(id)) return moveHead(c, dd);
      return null;
    }),
    d: dd,
  };
}
