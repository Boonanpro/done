// メインの段を詰めて直す（リップル）。2026-11-25 本人「メインレーンのクリップを短くしたら隙間が空いちゃう、
// クリップ同士の間に割り込んで順番を変えることができない。プレミアやダビンチを参考にサクサク編集できるように」。
//
// メインの段（一番下の映像の段）は隙間なく並ぶ物として扱う（Final Cut の主の並び・DaVinci のカットページと同じ）。
// メインのクリップの長さを変える・消す・並べ替えると、その後ろの全部の段（字幕・絵・効果音・モザイク）が
// 同じだけ前後に動き、映像と字幕がずれない（Premiere の「同期ロック」と同じ）。
// - 縮める（区間を抜く）: 抜いた区間の中だけにある物は消す（切った話の字幕など）。区間をまたぐ物（BGM）は
//   その分だけ短くして音を途切れさせない。
// - 伸ばす（区間を足す）: 足した所より後ろから始まる物を後ろへずらす。またいでいる物はそのまま。
// - 並べ替え: 動かすクリップを抜いて詰め、別のつなぎ目に差し込む。そのクリップの上にある字幕などは一緒に動く。
// 長いBGMのように何本ものクリップにまたがる物は、並べ替えでは動かさない（全体の長さは変わらないので）。
// 半分以上が動かすクリップの中にある物は、長くても乗っている物として一緒に動く（ridesOn）。

export type RClip = {
  id: string;
  timeline_start: number;
  timeline_end: number;
  source_start?: number | null;
  source_end?: number | null;
  speed?: number | null;
  role?: string | null;
  motion_keys?: Array<{ t: number } & Record<string, unknown>> | null;
  [k: string]: unknown;
};
export type RTrack = { type?: string | null; clips?: RClip[] | null; [k: string]: unknown };
export type RSeq = { tracks?: RTrack[] | null; duration?: number; [k: string]: unknown };
export type RAnn = { id: string; start: number; end?: number | null; data?: unknown; [k: string]: unknown };
export type RLane = { zone: 'visual' | 'audio'; layer: number };

const EPS = 0.01;
const r2 = (v: number) => Number(v.toFixed(2));
const r3 = (v: number) => Number(v.toFixed(3));

/** タイムラインで dt 秒進んだ時に素材の中で何秒進むか（速さを掛け、止め絵は進まない）。 */
export function srcAdvance(c: { source_start?: number | null; source_end?: number | null; speed?: number | null }, dt: number): number {
  const ss = Number(c.source_start || 0);
  if (c.source_end != null && Number(c.source_end) <= ss) return 0;
  const sp = Number(c.speed);
  return dt * (Number.isFinite(sp) && sp > 0 ? sp : 1);
}
const hasSource = (c: RClip) => Number.isFinite(c.source_end as number) && Number(c.source_end) > Number(c.source_start || 0) + 1e-6;

/** 何本ものクリップにまたがる物（BGM・長い絵）。並べ替えでは動かさず、詰める時は長さだけ変える。 */
export function isSpanning(c: RClip, lane?: RLane): boolean {
  const role = String(c.role || '');
  if (lane?.zone === 'audio' && (role === 'music' || role === 'bgm')) return true;
  return c.timeline_end - c.timeline_start > 20;
}

/** メインのクリップ [a, b] に乗っている物か（字幕・絵・モザイク・別に録った声）。自分の長さの半分以上が
 *  そのクリップの中にあり、BGM ではない。長さは問わない（30秒のクリップに付けた30秒の声も乗っている物）。
 *  2026-11-25 本人「コピペしたら音が出なくなる」: カメラの音は消してあり、聞こえる声は別に録った声の
 *  クリップだったので、映像と声のつながりだけを写すと声が抜けていた。 */
export function ridesOn(c: RClip, lane: RLane | undefined, a: number, b: number): boolean {
  const role = String(c.role || '');
  if (lane?.zone === 'audio' && (role === 'music' || role === 'bgm')) return false;
  const ov = Math.max(0, Math.min(c.timeline_end, b) - Math.max(c.timeline_start, a));
  return ov >= Math.max(EPS, (c.timeline_end - c.timeline_start) * 0.5);
}

/** 選んだメインのクリップに乗っている、ほかの段のクリップの id（写す・動かす時に一緒に連れて行く）。 */
export function riderIds(seq: RSeq, ids: string[], lanes: Map<string, RLane>, mainLayer: number | null): string[] {
  if (mainLayer === null) return [];
  const idset = new Set(ids.map(String));
  const all = (seq.tracks || []).flatMap((t) => t.clips || []);
  const isMain = (c: RClip) => { const l = lanes.get(String(c.id)); return l?.zone === 'visual' && l.layer === mainLayer; };
  const hosts = all.filter((c) => idset.has(String(c.id)) && isMain(c));
  if (!hosts.length) return [];
  const out: string[] = [];
  for (const c of all) {
    if (idset.has(String(c.id)) || isMain(c)) continue;
    const lane = lanes.get(String(c.id));
    if (hosts.some((h) => ridesOn(c, lane, h.timeline_start, h.timeline_end))) out.push(String(c.id));
  }
  return out;
}

/** メインの段: 映像のクリップがある一番下の映像の段。無ければ null。 */
export function mainLayerOf(tracks: RTrack[], lanes: Map<string, RLane>): number | null {
  let best: number | null = null;
  for (const t of tracks) {
    if (t.type === 'audio') continue;
    for (const c of t.clips || []) {
      const l = lanes.get(String(c.id));
      if (!l || l.zone !== 'visual' || !c.asset_id) continue;
      if (best === null || l.layer < best) best = l.layer;
    }
  }
  return best;
}

function shiftClip(c: RClip, d: number): RClip {
  if (Math.abs(d) < 1e-6) return c;
  return { ...c, timeline_start: r2(c.timeline_start + d), timeline_end: r2(c.timeline_end + d) };
}

type AnnData = { keyframes?: Array<{ t: number } & Record<string, unknown>>; track_boxes?: Record<string, number[]> };
function shiftAnn(a: RAnn, d: number): RAnn {
  if (Math.abs(d) < 1e-6) return a;
  const data = (a.data || {}) as AnnData;
  const nd: AnnData & Record<string, unknown> = { ...(data as Record<string, unknown>) };
  if (data.keyframes) nd.keyframes = data.keyframes.map((k) => ({ ...k, t: r2(k.t + d) }));
  if (data.track_boxes) nd.track_boxes = Object.fromEntries(Object.entries(data.track_boxes).map(([k, v]) => [String(r2(Number(k) + d)), v]));
  return { ...a, start: r2(a.start + d), end: a.end == null ? a.end : r2(a.end + d), ...(a.data ? { data: nd } : {}) };
}

/** 区間 [x, x+len] を抜いて後ろを詰める（len>0）。skip の id のクリップは呼び手が直すので触らない。 */
export function removeRange<S extends RSeq, A extends RAnn>(
  seq: S, anns: A[], x: number, len: number, skip: Set<string>, opts: { insideKeep?: boolean } = {},
): { seq: S; anns: A[] } {
  if (len <= EPS) return { seq, anns };
  const y = x + len;
  const tracks = (seq.tracks || []).map((track) => {
    const out: RClip[] = [];
    for (const c of track.clips || []) {
      if (skip.has(String(c.id))) { out.push(c); continue; }
      const s = c.timeline_start, e = c.timeline_end;
      const av = hasSource(c);
      if (e <= x + EPS) { out.push(c); continue; }
      if (s >= y - EPS) { out.push(shiftClip(c, -len)); continue; }
      if (s >= x - EPS && e <= y + EPS) {
        // 抜いた区間の中だけにある物: 消す（隙間を詰める時は区間の頭へ寄せて残す）
        if (opts.insideKeep) out.push(shiftClip(c, x - s));
        continue;
      }
      if (s < x && e > y) {
        out.push({ ...c, timeline_end: r2(e - len), ...(av ? { source_end: r3(Number(c.source_end) - srcAdvance(c, len)) } : {}) });
        continue;
      }
      if (s < x) {
        out.push({ ...c, timeline_end: r2(x), ...(av ? { source_end: r3(Number(c.source_end) - srcAdvance(c, e - x)) } : {}) });
        continue;
      }
      // 頭が区間の中、後ろが区間の外: 頭を切って区間の頭から始める
      const cut = y - s;
      const keys = c.motion_keys && c.motion_keys.length ? { motion_keys: c.motion_keys.map((k) => ({ ...k, t: Number((k.t - cut).toFixed(4)) })) } : {};
      out.push({ ...c, timeline_start: r2(x), timeline_end: r2(e - len), ...(av ? { source_start: r3(Number(c.source_start || 0) + srcAdvance(c, cut)) } : {}), ...keys });
    }
    return { ...track, clips: out };
  });
  const outAnns: A[] = [];
  for (const a of anns) {
    const s = a.start, e = a.end ?? a.start;
    if (e <= x + EPS && s < x + EPS) { outAnns.push(a); continue; }
    if (s >= y - EPS) { outAnns.push(shiftAnn(a, -len) as A); continue; }
    if (s >= x - EPS && e <= y + EPS) { if (opts.insideKeep) outAnns.push(shiftAnn(a, x - s) as A); continue; }
    if (s < x && e > y) { outAnns.push({ ...a, end: r2(e - len) }); continue; }
    if (s < x) { outAnns.push({ ...a, end: r2(x) }); continue; }
    const moved = shiftAnn(a, -len) as A;
    outAnns.push({ ...moved, start: r2(x) });
  }
  return { seq: withDuration({ ...seq, tracks }), anns: outAnns };
}

/** x に len 秒を足して、x から後ろに始まる物を後ろへずらす。BGM のように x をまたぐ・x から始まる長い物はそのまま。 */
export function insertRange<S extends RSeq, A extends RAnn>(
  seq: S, anns: A[], x: number, len: number, skip: Set<string>, lanes: Map<string, RLane>, mainLayer: number | null,
): { seq: S; anns: A[] } {
  if (len <= EPS) return { seq, anns };
  const tracks = (seq.tracks || []).map((track) => ({
    ...track,
    clips: (track.clips || []).map((c) => {
      if (skip.has(String(c.id))) return c;
      if (c.timeline_start < x - EPS) return c;
      const lane = lanes.get(String(c.id));
      const onMain = lane?.zone === 'visual' && lane.layer === mainLayer;
      if (!onMain && c.timeline_start < x + EPS && isSpanning(c, lane)) return c;
      return shiftClip(c, len);
    }),
  }));
  const outAnns = anns.map((a) => (a.start >= x - EPS ? (shiftAnn(a, len) as A) : a));
  return { seq: withDuration({ ...seq, tracks }), anns: outAnns };
}

export function withDuration<S extends RSeq>(seq: S): S {
  const d = Math.max(0, ...(seq.tracks || []).flatMap((t) => (t.clips || []).map((c) => c.timeline_end || 0)));
  return { ...seq, duration: r3(d) };
}

function patchClips<S extends RSeq>(seq: S, patch: Map<string, Partial<RClip>>): S {
  if (!patch.size) return seq;
  return { ...seq, tracks: (seq.tracks || []).map((t) => ({ ...t, clips: (t.clips || []).map((c) => (patch.has(String(c.id)) ? { ...c, ...patch.get(String(c.id)) } : c)) })) };
}

/** メインのクリップ（と相方の音声 ids）の頭か終わりを動かし、後ろを全部の段で詰める・ずらす。
 *  mode=end: 終わりを delta 秒動かす（+で伸ばす）。mode=start: 頭を delta 秒動かす（+で縮める。クリップは同じ所から
 *  始まり、中身が delta 秒先から始まる＝Premiere のリップルトリム）。maxGrow で伸ばせる上限を渡す。 */
export function rippleTrim<S extends RSeq, A extends RAnn>(
  seq: S, anns: A[], ids: string[], mode: 'start' | 'end', delta: number, lanes: Map<string, RLane>, mainLayer: number | null,
): { seq: S; anns: A[]; delta: number } {
  const all = (seq.tracks || []).flatMap((t) => t.clips || []);
  const main = all.find((c) => String(c.id) === ids[0]);
  if (!main) return { seq, anns, delta: 0 };
  const len = main.timeline_end - main.timeline_start;
  const group = all.filter((c) => ids.includes(String(c.id)));
  // 縮めるのは 0.1 秒まで（伸ばせる上限は呼び手が素材の長さで決めて渡す）
  let d = delta;
  if (mode === 'end') d = Math.max(d, -(len - 0.1));
  else d = Math.min(d, len - 0.1);
  if (Math.abs(d) < 1e-6) return { seq, anns, delta: 0 };
  const a = main.timeline_start, b = main.timeline_end;
  const skip = new Set(group.map((c) => String(c.id)));
  const patch = new Map<string, Partial<RClip>>();
  for (const c of group) {
    const av = hasSource(c);
    if (mode === 'end') {
      patch.set(String(c.id), { timeline_end: r2(c.timeline_end + d), ...(av ? { source_end: r3(Number(c.source_end) + srcAdvance(c, d)) } : {}) });
    } else {
      const keys = c.motion_keys && c.motion_keys.length ? { motion_keys: c.motion_keys.map((k) => ({ ...k, t: Number((k.t - d).toFixed(4)) })) } : {};
      patch.set(String(c.id), { timeline_end: r2(c.timeline_end - d), ...(av ? { source_start: r3(Math.max(0, Number(c.source_start || 0) + srcAdvance(c, d))) } : {}), ...keys });
    }
  }
  let next = patchClips(seq, patch);
  let res: { seq: S; anns: A[] };
  if (mode === 'end') {
    res = d < 0 ? removeRange(next, anns, b + d, -d, skip) : insertRange(next, anns, b, d, skip, lanes, mainLayer);
  } else {
    res = d > 0 ? removeRange(next, anns, a, d, skip) : insertRange(next, anns, a, -d, skip, lanes, mainLayer);
  }
  next = res.seq;
  return { seq: withDuration(next), anns: res.anns, delta: d };
}

/** メインのクリップ（と相方 ids）を抜いて詰め、詰めた後のタイムラインの時刻 P に差し込む。
 *  上に乗っている物（半分以上がそのクリップの上にある字幕・絵・モザイク）は一緒に動く。 */
export function rippleMove<S extends RSeq, A extends RAnn>(
  seq: S, anns: A[], ids: string[], P: number, lanes: Map<string, RLane>, mainLayer: number | null,
): { seq: S; anns: A[] } {
  const all = (seq.tracks || []).flatMap((t) => t.clips || []);
  const main = all.find((c) => String(c.id) === ids[0]);
  if (!main) return { seq, anns };
  const a = main.timeline_start, b = main.timeline_end, L = b - a;
  const idset = new Set(ids);
  const isMain = (c: RClip) => { const l = lanes.get(String(c.id)); return l?.zone === 'visual' && l.layer === mainLayer; };
  const mainClips = all.filter((c) => isMain(c) && !idset.has(String(c.id)));
  // 抜いて詰めた後の時刻
  const lifted = (t: number) => (t >= b - EPS ? t - L : t);
  // 差し込んだ後の時刻（詰めた後の時刻 t' について）
  const placed = (t: number) => (t >= P - EPS ? t + L : t);
  const outside = (t: number) => placed(lifted(t)) - t;
  const mainShift = new Map<string, number>();
  for (const c of mainClips) mainShift.set(String(c.id), outside(c.timeline_start));
  const mainAt = (t: number) => mainClips.find((c) => t >= c.timeline_start - EPS && t < c.timeline_end - EPS);
  const ride = P - a;
  const attached = (s: number, e: number) => {
    const ov = Math.max(0, Math.min(e, b) - Math.max(s, a));
    return ov >= Math.max(EPS, (e - s) * 0.5);
  };
  const shiftFor = (s: number, e: number, spanning: boolean): number => {
    if (spanning) return 0;
    if (attached(s, e)) return ride;
    const host = mainAt(s + EPS) || mainAt(e - EPS);
    if (host) return mainShift.get(String(host.id)) || 0;
    if (s > a - EPS && s < b - EPS) return 0;
    return outside(s);
  };
  const tracks = (seq.tracks || []).map((track) => ({
    ...track,
    clips: (track.clips || []).map((c) => {
      if (idset.has(String(c.id))) return shiftClip(c, ride);
      if (isMain(c)) return shiftClip(c, mainShift.get(String(c.id)) || 0);
      const lane = lanes.get(String(c.id));
      // 乗っている物は長くても一緒に動く（30秒のクリップの声が置いて行かれていた）
      if (ridesOn(c, lane, a, b)) return shiftClip(c, ride);
      return shiftClip(c, shiftFor(c.timeline_start, c.timeline_end, isSpanning(c, lane)));
    }),
  }));
  const outAnns = anns.map((x) => shiftAnn(x, shiftFor(x.start, x.end ?? x.start + 0.5, false)) as A);
  return { seq: withDuration({ ...seq, tracks }), anns: outAnns };
}

/** 並べ替えで差し込める所（抜いて詰めた後のメインのつなぎ目）。 */
export function insertPoints(seq: RSeq, ids: string[], lanes: Map<string, RLane>, mainLayer: number | null): number[] {
  const all = (seq.tracks || []).flatMap((t) => t.clips || []);
  const main = all.find((c) => String(c.id) === ids[0]);
  if (!main) return [];
  const a = main.timeline_start, b = main.timeline_end, L = b - a;
  const lifted = (t: number) => (t >= b - EPS ? t - L : t);
  const pts = new Set<number>([0]);
  for (const c of all) {
    const l = lanes.get(String(c.id));
    if (ids.includes(String(c.id)) || l?.zone !== 'visual' || l.layer !== mainLayer) continue;
    pts.add(r2(lifted(c.timeline_start)));
    pts.add(r2(lifted(c.timeline_end)));
  }
  return Array.from(pts).sort((p, q) => p - q);
}

/** メインの段の t の所にある隙間 [g0, g1]。隙間でなければ null。 */
export function mainGapAt(seq: RSeq, t: number, lanes: Map<string, RLane>, mainLayer: number | null): [number, number] | null {
  const main = (seq.tracks || []).flatMap((tr) => tr.clips || []).filter((c) => {
    const l = lanes.get(String(c.id));
    return l?.zone === 'visual' && l.layer === mainLayer;
  }).sort((p, q) => p.timeline_start - q.timeline_start);
  if (main.some((c) => t >= c.timeline_start - EPS && t <= c.timeline_end + EPS)) return null;
  let g0 = 0;
  for (const c of main) {
    if (c.timeline_end <= t) g0 = Math.max(g0, c.timeline_end);
  }
  const after = main.find((c) => c.timeline_start > t);
  if (!after) return null; // 最後のクリップより後ろは隙間ではない
  return g0 < after.timeline_start - EPS ? [g0, after.timeline_start] : null;
}

/** メインの段の隙間を全部（gap だけなら1つ）詰める。隙間の中にある別の段の物は隙間の頭へ寄せて残す。 */
export function closeMainGaps<S extends RSeq, A extends RAnn>(
  seq: S, anns: A[], lanes: Map<string, RLane>, mainLayer: number | null, only?: [number, number],
): { seq: S; anns: A[]; closed: number } {
  const main = (seq.tracks || []).flatMap((tr) => tr.clips || []).filter((c) => {
    const l = lanes.get(String(c.id));
    return l?.zone === 'visual' && l.layer === mainLayer;
  }).sort((p, q) => p.timeline_start - q.timeline_start);
  const gaps: Array<[number, number]> = [];
  let edge = 0;
  for (const c of main) {
    if (c.timeline_start > edge + EPS) gaps.push([edge, c.timeline_start]);
    edge = Math.max(edge, c.timeline_end);
  }
  const todo = only ? gaps.filter((g) => Math.abs(g[0] - only[0]) < EPS && Math.abs(g[1] - only[1]) < EPS) : gaps;
  let s = seq, an = anns, closed = 0;
  // 後ろの隙間から詰める（前を詰めると後ろの時刻が変わるので）
  for (const [g0, g1] of todo.slice().reverse()) {
    const res = removeRange(s, an, g0, g1 - g0, new Set(), { insideKeep: true });
    s = res.seq; an = res.anns; closed += g1 - g0;
  }
  return { seq: s, anns: an, closed: r2(closed) };
}

/** メインのクリップを消して、全部の段を詰める（後ろの区間から）。 */
export function rippleDeleteMain<S extends RSeq, A extends RAnn>(
  seq: S, anns: A[], mainIds: string[],
): { seq: S; anns: A[] } {
  const all = (seq.tracks || []).flatMap((t) => t.clips || []);
  const ranges = all.filter((c) => mainIds.includes(String(c.id))).map((c) => [c.timeline_start, c.timeline_end] as [number, number])
    .sort((p, q) => p[0] - q[0]);
  // 重なる・つながる区間はまとめる
  const merged: Array<[number, number]> = [];
  for (const rg of ranges) {
    const last = merged[merged.length - 1];
    if (last && rg[0] <= last[1] + EPS) last[1] = Math.max(last[1], rg[1]);
    else merged.push([...rg]);
  }
  let s = seq, an = anns;
  for (const [x, y] of merged.reverse()) {
    const res = removeRange(s, an, x, y - x, new Set());
    s = res.seq; an = res.anns;
  }
  return { seq: s, anns: an };
}
