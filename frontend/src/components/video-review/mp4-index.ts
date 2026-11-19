/**
 * 素材の目次を裏（Web Worker）で読む入口。裏の処理を作れない・途中で落ちた時は画面の側で読む。
 * 中身は mp4-index-parse.ts。
 */
import { parseMp4Index, type Mp4Index } from './mp4-index-parse';

export type { Mp4Index, VideoIndex, AudioIndex } from './mp4-index-parse';

let worker: Worker | null | undefined;
let nextId = 1;
const waiting = new Map<number, { resolve: (v: Mp4Index) => void; reject: (e: Error) => void }>();

function getWorker(): Worker | null {
  if (worker !== undefined) return worker;
  worker = null;
  if (typeof window === 'undefined' || typeof Worker === 'undefined') return null;
  if (new URLSearchParams(window.location.search).get('mp4worker') === '0') return null; // 比べる時だけ前の作り
  try {
    const w = new Worker(new URL('./mp4-index.worker.ts', import.meta.url), { type: 'module' });
    w.onmessage = (ev: MessageEvent<{ id: number; ok: boolean; out?: Mp4Index; error?: string }>) => {
      const p = waiting.get(ev.data.id);
      if (!p) return;
      waiting.delete(ev.data.id);
      if (ev.data.ok && ev.data.out) p.resolve(ev.data.out); else p.reject(new Error(ev.data.error || 'mp4 index failed'));
    };
    w.onerror = () => {
      // 裏の処理が使えない: 待っている物は画面の側で読み直してもらう
      worker = null;
      for (const [, p] of waiting) p.reject(new Error('worker-unavailable'));
      waiting.clear();
      w.terminate();
    };
    worker = w;
  } catch {
    worker = null;
  }
  return worker;
}

/** ftyp+moov だけの並びを読む。idx はこの後使わないこと（裏の処理へ渡して空になる）。 */
export async function readMp4Index(idx: Uint8Array, kind: 'video' | 'audio'): Promise<Mp4Index> {
  const w = getWorker();
  if (w) {
    const keep = idx.slice(); // 裏が落ちた時に画面の側で読み直す分
    try {
      return await new Promise<Mp4Index>((resolve, reject) => {
        const id = nextId++;
        waiting.set(id, { resolve, reject });
        w.postMessage({ id, idx, kind }, [idx.buffer as ArrayBuffer]);
      });
    } catch (e) {
      if ((e as Error).message !== 'worker-unavailable') throw e;
      return parseMp4Index(keep, kind);
    }
  }
  return parseMp4Index(idx, kind);
}
