// The owner's own undo/redo, kept apart from Dan's edits (11/10 owner: "俺の操作に干渉してくるのやめてほしい").
// Like a shared document: an undo step remembers only what the OWNER changed (the state before
// and after their burst). Undoing reverts exactly those clips / fields / annotations on top of
// whatever the timeline is now, so Dan's edits that arrived in between stay, and Dan's edits never
// erase the owner's history.
import type { EditSequence, ReviewAnnotation, SequenceClip } from './video-review-editor';

export type HistSnapshot = { annotations: ReviewAnnotation[]; sequence: EditSequence | null };
export type HistStep = { before: HistSnapshot; after: HistSnapshot };

type Track = NonNullable<EditSequence['tracks']>[number];
type Located = { trackId: string; index: number; clip: SequenceClip };

const same = (a: unknown, b: unknown) => a === b || JSON.stringify(a) === JSON.stringify(b);

function clipIndex(seq: EditSequence | null): Map<string, Located> {
  const out = new Map<string, Located>();
  for (const track of seq?.tracks || []) {
    (track.clips || []).forEach((clip, index) => out.set(String(clip.id), { trackId: track.id, index, clip }));
  }
  return out;
}

/** Apply onto `current` exactly the fields that changed between `from` and `to`, leaving every key
 *  the step did not touch as it is now. */
function patchFields<T extends object>(current: T, from: T, to: T): T {
  const next = { ...current } as Record<string, unknown>;
  const f = from as Record<string, unknown>;
  const t = to as Record<string, unknown>;
  for (const key of new Set([...Object.keys(f), ...Object.keys(t)])) {
    if (same(f[key], t[key])) continue;
    if (t[key] === undefined) delete next[key];
    else next[key] = t[key];
  }
  return next as T;
}

/** Move the timeline from `from` to `to` for what the step changed, starting from `current`. */
export function rebaseSequence(
  current: EditSequence | null,
  from: EditSequence | null,
  to: EditSequence | null,
): EditSequence | null {
  if (same(from, to)) return current;
  if (!current) return to;
  const fromClips = clipIndex(from);
  const toClips = clipIndex(to);
  // Mutable copy: tracks and their clip lists.
  const tracks: Track[] = (current.tracks || []).map((t) => ({ ...t, clips: [...(t.clips || [])] }));
  const trackOf = (id: string): Track => {
    let track = tracks.find((t) => t.id === id);
    if (!track) {
      const shape = (to?.tracks || []).find((t) => t.id === id) || (from?.tracks || []).find((t) => t.id === id);
      track = { ...(shape || { id, type: 'video' }), clips: [] };
      tracks.push(track);
    }
    return track;
  };
  const findNow = (id: string): { track: Track; index: number } | null => {
    for (const track of tracks) {
      const index = (track.clips || []).findIndex((c) => String(c.id) === id);
      if (index >= 0) return { track, index };
    }
    return null;
  };

  for (const id of new Set([...fromClips.keys(), ...toClips.keys()])) {
    const a = fromClips.get(id);
    const b = toClips.get(id);
    if (a && b && a.trackId === b.trackId && same(a.clip, b.clip)) continue;
    const now = findNow(id);
    if (!b) {
      // The step brought this clip in; going back takes it out (if it is still there).
      if (now) now.track.clips!.splice(now.index, 1);
      continue;
    }
    if (!a) {
      // The step took this clip out; going back puts it where it was (unless it is back already).
      if (now) continue;
      const track = trackOf(b.trackId);
      track.clips!.splice(Math.min(b.index, track.clips!.length), 0, b.clip);
      continue;
    }
    // Changed by the step. If someone removed it since, there is nothing to change back.
    if (!now) continue;
    const patched = patchFields(now.track.clips![now.index], a.clip, b.clip);
    if (a.trackId !== b.trackId && now.track.id === a.trackId) {
      now.track.clips!.splice(now.index, 1);
      const target = trackOf(b.trackId);
      target.clips!.splice(Math.min(b.index, target.clips!.length), 0, patched);
    } else {
      now.track.clips![now.index] = patched;
    }
  }

  // Sequence-level fields the step changed (duration etc.), and track settings (mute, label…).
  const { tracks: _f, ...fromRest } = from || {};
  const { tracks: _t, ...toRest } = to || {};
  const { tracks: _c, ...curRest } = current;
  const rest = patchFields(curRest, fromRest, toRest);
  const outTracks = tracks.map((track) => {
    const fa = (from?.tracks || []).find((t) => t.id === track.id);
    const tb = (to?.tracks || []).find((t) => t.id === track.id);
    if (!fa || !tb) return track;
    const { clips: _a, ...faMeta } = fa;
    const { clips: _b, ...tbMeta } = tb;
    return { ...patchFields(track, faMeta as Track, tbMeta as Track), clips: track.clips };
  });
  return { ...rest, tracks: outTracks };
}

export function rebaseAnnotations(
  current: ReviewAnnotation[],
  from: ReviewAnnotation[],
  to: ReviewAnnotation[],
): ReviewAnnotation[] {
  if (same(from, to)) return current;
  const out = [...current];
  const fromById = new Map(from.map((a) => [a.id, a]));
  const toById = new Map(to.map((a, i) => [a.id, { a, i }]));
  for (const id of new Set([...fromById.keys(), ...toById.keys()])) {
    const a = fromById.get(id);
    const b = toById.get(id);
    if (a && b && same(a, b.a)) continue;
    const at = out.findIndex((x) => x.id === id);
    if (!b) {
      if (at >= 0) out.splice(at, 1);
    } else if (!a) {
      if (at < 0) out.splice(Math.min(b.i, out.length), 0, b.a);
    } else if (at >= 0) {
      out[at] = patchFields(out[at], a, b.a);
    }
  }
  return out;
}

/** Undo (`to` = step.before) or redo (`to` = step.after) one owner step on top of `current`. */
export function applyOwnStep(current: HistSnapshot, step: HistStep, direction: 'undo' | 'redo'): HistSnapshot {
  const [from, to] = direction === 'undo' ? [step.after, step.before] : [step.before, step.after];
  return {
    annotations: rebaseAnnotations(current.annotations, from.annotations, to.annotations),
    sequence: rebaseSequence(current.sequence, from.sequence, to.sequence),
  };
}
