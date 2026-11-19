/// <reference lib="webworker" />
// 素材の目次を、画面とは別の処理で読む（mp4-index-parse.ts）。
import { parseMp4Index, transferablesOf } from './mp4-index-parse';

self.onmessage = async (ev: MessageEvent<{ id: number; idx: Uint8Array; kind: 'video' | 'audio' }>) => {
  const { id, idx, kind } = ev.data;
  try {
    const out = await parseMp4Index(idx, kind);
    (self as unknown as Worker).postMessage({ id, ok: true, out }, transferablesOf(out));
  } catch (e) {
    (self as unknown as Worker).postMessage({ id, ok: false, error: String((e as Error)?.message || e) });
  }
};
