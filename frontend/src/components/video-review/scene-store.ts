/**
 * What is inside each editable scene clip (the texts the scene marks with data-edit), as the
 * scene's own frame reports it after loading: key, label, current text, font, colour and when
 * it is on screen (seconds into the scene). The timeline draws these as the clip's inner rows
 * and the side panel edits them; both read it from here so the editor itself need not change.
 */
import { useSyncExternalStore } from 'react';

export type SceneItem = { key: string; label: string; text: string; start: number; end: number; font: string; color: string; size: number };
export type SceneInfo = { duration: number; items: SceneItem[] };

const infos = new Map<string, SceneInfo>();
const subs = new Set<() => void>();
let version = 0;

export function setSceneInfo(clipId: string, info: SceneInfo) {
  infos.set(clipId, info);
  version += 1;
  subs.forEach((f) => f());
}

function subscribe(f: () => void) { subs.add(f); return () => { subs.delete(f); }; }

export function useSceneInfo(clipId: string | null | undefined): SceneInfo | null {
  useSyncExternalStore(subscribe, () => version, () => version);
  return clipId ? infos.get(clipId) || null : null;
}

/** this clip's scene contents only (re-renders just that clip when it changes) */
export function useSceneInfoFor(clipId: string): SceneInfo | null {
  return useSyncExternalStore(subscribe, () => infos.get(clipId) || null, () => null);
}
