/**
 * 素材の目次（moov: どのコマ・どの音がファイルのどこにあるか）を mp4box で読み、
 * 受け渡しやすい数字の並びにする。長い録画では目次だけで数MB・25万コマあり、画面の処理の中で読むと
 * 作品を開くたびに0.2〜0.4秒止まっていた（2026-11-19 本人の Windows の記録）。ふだんは
 * mp4-index.worker.ts の中（画面とは別の処理）で動き、裏で動かせない時だけ画面の側で動く。
 */
import { createFile, DataStream, type MP4File, type MP4ArrayBuffer } from 'mp4box';

export type VideoIndex = {
  kind: 'video';
  duration: number; width: number; height: number; codec: string;
  description?: Uint8Array;
  cts: Float64Array; dur: Float64Array; offset: Float64Array; size: Float64Array; sync: Uint8Array;
  /** 解読の順の番号を、見せる時刻の順に並べた物 */
  presOrder: Int32Array;
};
export type AudioIndex = {
  kind: 'audio';
  duration: number; silent: boolean; codec: string; sampleRate: number; channels: number;
  description?: Uint8Array;
  /** 再生機（<video>）と同じ時刻にそろえた並び（時刻順） */
  pt: Float64Array; dur: Float64Array; offset: Float64Array; size: Float64Array;
};
export type Mp4Index = VideoIndex | AudioIndex;

function readInfo(idx: Uint8Array): Promise<{ file: MP4File; info: Record<string, unknown> & { duration: number; timescale: number } }> {
  const copy = idx.slice();
  const ab = copy.buffer as MP4ArrayBuffer;
  ab.fileStart = 0;
  const file: MP4File = createFile();
  return new Promise((resolve, reject) => {
    file.onError = (e) => reject(new Error(String(e)));
    file.onReady = (info) => resolve({ file, info: info as unknown as Record<string, unknown> & { duration: number; timescale: number } });
    file.appendBuffer(ab);
    file.flush();
    setTimeout(() => reject(new Error('moov parse timeout')), 5000);
  });
}

function extractDescription(file: MP4File, trackId: number): Uint8Array | undefined {
  const trak = file.getTrackById(trackId);
  for (const entry of trak.mdia.minf.stbl.stsd.entries) {
    const box = entry.avcC || entry.hvcC || entry.vpcC || entry.av1C;
    if (box) {
      const stream = new DataStream(undefined, 0, DataStream.BIG_ENDIAN);
      box.write(stream);
      return new Uint8Array(stream.buffer, 8); // drop box size+type header
    }
  }
  return undefined;
}

/** ftyp+moov だけの並び（idx）を読む。サンプルの位置はファイルの頭からの絶対位置のまま。 */
export async function parseMp4Index(idx: Uint8Array, kind: 'video' | 'audio'): Promise<Mp4Index> {
  const { file, info } = await readInfo(idx);
  const timescale = info.timescale || 1;
  if (kind === 'video') {
    const vt = (info.videoTracks as Array<{ id: number; codec: string; track_width: number; track_height: number }> | undefined)?.[0];
    if (!vt) throw new Error('no video track');
    const list = file.getTrackSamplesInfo(vt.id) || [];
    const n = list.length;
    const out: VideoIndex = {
      kind: 'video', duration: info.duration / timescale, width: vt.track_width, height: vt.track_height, codec: vt.codec,
      description: extractDescription(file, vt.id),
      cts: new Float64Array(n), dur: new Float64Array(n), offset: new Float64Array(n), size: new Float64Array(n), sync: new Uint8Array(n),
      presOrder: new Int32Array(0),
    };
    for (let i = 0; i < n; i++) {
      const s = list[i];
      out.cts[i] = s.cts / s.timescale; out.dur[i] = s.duration / s.timescale;
      out.offset[i] = s.offset; out.size[i] = s.size; out.sync[i] = s.is_sync ? 1 : 0;
    }
    const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => out.cts[a] - out.cts[b]);
    out.presOrder = Int32Array.from(order);
    return out;
  }
  type ATrack = { id: number; codec: string; audio?: { sample_rate: number; channel_count: number } };
  const at = (info.audioTracks as ATrack[] | undefined)?.[0];
  const empty0 = new Float64Array(0);
  if (!at) return { kind: 'audio', duration: info.duration / timescale, silent: true, codec: '', sampleRate: 48000, channels: 2, pt: empty0, dur: empty0, offset: empty0, size: empty0 };
  const trak = file.getTrackById(at.id) as unknown as {
    mdia: { mdhd?: { timescale: number }; minf: { stbl: { stsd: { entries: Array<{ esds?: { esd?: { descs?: Array<{ descs?: Array<{ data?: Uint8Array }> }> } } }> } } } };
    edts?: { elst?: { entries?: Array<{ segment_duration: number; media_time: number }> } };
  };
  const dsi = trak.mdia.minf.stbl.stsd.entries[0]?.esds?.esd?.descs?.[0]?.descs?.[0]?.data;
  // 編集リスト（AAC の先頭の詰め物の分）: 再生機（<video>）と同じ時刻に揃える
  const mts = trak.mdia.mdhd?.timescale || 0;
  let shift = 0;
  let empty = 0;
  for (const e of trak.edts?.elst?.entries || []) {
    if (e.media_time === -1) { empty += e.segment_duration / timescale; continue; }
    if (mts) shift = e.media_time / mts;
    break;
  }
  const list = (file.getTrackSamplesInfo(at.id) || [])
    .map((s) => ({ pt: s.cts / s.timescale - shift + empty, dur: s.duration / s.timescale, offset: s.offset, size: s.size }))
    .sort((a, b) => a.pt - b.pt);
  const n = list.length;
  const out: AudioIndex = {
    kind: 'audio', duration: info.duration / timescale, silent: n === 0, codec: at.codec,
    sampleRate: at.audio?.sample_rate || 48000, channels: Math.max(1, Math.min(2, at.audio?.channel_count || 2)),
    description: dsi ? new Uint8Array(dsi) : undefined,
    pt: new Float64Array(n), dur: new Float64Array(n), offset: new Float64Array(n), size: new Float64Array(n),
  };
  for (let i = 0; i < n; i++) { const s = list[i]; out.pt[i] = s.pt; out.dur[i] = s.dur; out.offset[i] = s.offset; out.size[i] = s.size; }
  return out;
}

/** 受け渡しで写さずに渡せる中身（数字の並びの元の置き場） */
export function transferablesOf(x: Mp4Index): ArrayBuffer[] {
  const arrs: Array<{ buffer: ArrayBufferLike } | undefined> = x.kind === 'video'
    ? [x.cts, x.dur, x.offset, x.size, x.sync, x.presOrder, x.description]
    : [x.pt, x.dur, x.offset, x.size, x.description];
  const seen = new Set<ArrayBufferLike>();
  for (const a of arrs) if (a && a.buffer.byteLength) seen.add(a.buffer);
  return [...seen] as ArrayBuffer[];
}
