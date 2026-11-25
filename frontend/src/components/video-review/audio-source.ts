// 音の素材を前もって解読しておく所（編集ソフトと同じやり方）。
//
// 前は音のクリップ1つごとに隠れた <video> を置き、クリップに入った瞬間にその要素を録画の途中へ
// 頭出しして鳴らしていた。粗編集のように数秒ごとに切れている（スヤさん1本目は600か所）と、
// 切れ目のたびに頭出しの読み込みを待つ間だけ音が出ず、「映像は動いているのに音が鳴らない」が
// 頻繁に起きた（2026-11-13 本人）。
//
// ここでは、素材ごとに音の部分だけを Range で読んで（映像の分は読まない）、WebCodecs の
// AudioDecoder で 4 秒ずつ PCM に解読し、AudioBuffer として持つ。再生側（timeline-preview.tsx）は
// それを Web Audio の時計で、クリップの境目の時刻ぴったりに鳴らす。頭出しの待ちが無くなる。
// mp4 以外（wav・mp3 など短い音の素材）は丸ごと読んで decodeAudioData する。

import { readMp4Index } from './mp4-index';
import { readLocalRange } from './local-media';
import { mediaFetch } from './media-route';
import { stretchChannels } from './time-stretch';

const BLOCK_SEC = 4;                  // 1 回に解読する長さ
const MAX_BLOCKS = 40;                // 素材ごとに持つ数（約160秒・ステレオ48kHzで約60MB）
const HEAD_BYTES = 64 * 1024;
const WHOLE_FILE_LIMIT = 200 * 1024 * 1024; // mp4 でない素材を丸ごと読む上限
const RANGE_GAP = 96 * 1024;          // 音の断片の間がこれより狭ければ1回の Range にまとめる
export const STRETCH_BLOCK_SEC = BLOCK_SEC; // 倍速で鳴らす時の区切り（丸ごとの素材もこの長さで区切って縮める）
const MAX_STRETCHED = 24;

type ASample = { pt: number; dur: number; offset: number; size: number };

export type AudioSegment = { buffer: AudioBuffer; bufOffset: number; srcStart: number; srcEnd: number };

/** 制作の素材（variant=view / proxy / original）なら、音だけの写し（短い AAC の m4a）の住所。それ以外は null */
export function audioOnlyUrl(url: string): string | null {
  if (!url.includes('/production-assets/media?') || !/[?&]variant=(view|proxy|original)(&|$)/.test(url)) return null;
  return url.replace(/([?&]variant=)(view|proxy|original)/, '$1audio');
}

export function webAudioSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.AudioContext !== 'undefined' && typeof window.AudioDecoder !== 'undefined';
}

export class AssetAudioSource {
  readonly url: string;
  ready: Promise<void>;
  failed = false;
  /** 音の無い素材（映像だけ）。鳴らす物が無いので待たない */
  silent = false;
  duration = 0;

  private ctx: BaseAudioContext;
  private samples: ASample[] = [];
  private codec = '';
  private description?: Uint8Array;
  private sampleRate = 48000;
  private channels = 2;
  private whole: AudioBuffer | null = null;          // mp4 でない素材: 丸ごと
  private blocks = new Map<number, AudioBuffer>();   // 4 秒ずつ（Map の順 = 古い順）
  private loads = new Map<number, Promise<void>>();
  private closed = false;

  constructor(url: string, ctx: BaseAudioContext) {
    this.url = url;
    this.ctx = ctx;
    this.fetchUrl = audioOnlyUrl(url) || url;
    this.ready = this.init().catch(async (e) => {
      if (this.fetchUrl === this.url) throw e;
      // 音だけの写しが作れなかった（古い配り口など）: 映像入りの写しから読む
      this.fetchUrl = this.url;
      this.samples = [];
      this.silent = false;
      await this.init();
    }).catch((e) => {
      this.failed = true;
      console.warn('[audio-source] init failed', url, e);
    });
  }

  // 読む先: 制作の素材なら、まず音だけの写し（variant=audio）。無ければ渡された写しそのもの
  private fetchUrl: string;

  private async fetchRange(lo: number, hi: number): Promise<{ buf: ArrayBuffer; total: number; partial: boolean }> {
    const local = await readLocalRange(this.fetchUrl, lo, hi);
    if (local) return local;
    const res = await mediaFetch(this.fetchUrl, { headers: { Range: `bytes=${lo}-${hi}` } });
    if (!res.ok) throw new Error(`fetch ${res.status}`);
    if (res.status === 206) {
      const m = /\/(\d+)\s*$/.exec(res.headers.get('Content-Range') || '');
      return { buf: await res.arrayBuffer(), total: m ? Number(m[1]) : 0, partial: true };
    }
    const len = Number(res.headers.get('Content-Length') || 0);
    if (len > WHOLE_FILE_LIMIT) throw new Error(`no range support (size ${len})`);
    const buf = await res.arrayBuffer();
    return { buf, total: buf.byteLength, partial: false };
  }

  private async init(): Promise<void> {
    const head = await this.fetchRange(0, HEAD_BYTES - 1);
    const headBytes = new Uint8Array(head.buf);
    const isMp4 = headBytes.byteLength >= 8 && String.fromCharCode(headBytes[4], headBytes[5], headBytes[6], headBytes[7]) === 'ftyp';
    if (!isMp4 || typeof window.AudioDecoder === 'undefined') {
      await this.initWhole(head);
      return;
    }
    try {
      await this.initMp4(head, headBytes);
    } catch (e) {
      // mov の PCM など AudioDecoder が読めない音: 小さい素材なら丸ごと解読する
      this.samples = [];
      this.silent = false;
      if (head.total && head.total <= WHOLE_FILE_LIMIT) { await this.initWhole(head); return; }
      throw e;
    }
  }

  private async initMp4(head: { buf: ArrayBuffer; total: number; partial: boolean }, headBytes: Uint8Array): Promise<void> {
    const total = head.total;
    const readAt = async (pos: number, len: number): Promise<Uint8Array> => {
      if (!head.partial || pos + len <= headBytes.byteLength) return headBytes.subarray(pos, pos + len);
      return new Uint8Array((await this.fetchRange(pos, pos + len - 1)).buf);
    };
    let ftyp: Uint8Array | null = null;
    let moov: Uint8Array | null = null;
    let pos = 0;
    for (let guard = 0; guard < 64 && pos + 8 <= total && !moov; guard++) {
      const h = await readAt(pos, 16);
      const dv = new DataView(h.buffer, h.byteOffset, h.byteLength);
      let size = dv.getUint32(0);
      const type = String.fromCharCode(h[4], h[5], h[6], h[7]);
      if (size === 1) size = Number(dv.getBigUint64(8));
      else if (size === 0) size = total - pos;
      if (size < 8) throw new Error('bad box');
      if (type === 'ftyp') ftyp = (await readAt(pos, size)).slice();
      else if (type === 'moov') moov = (await readAt(pos, size)).slice();
      pos += size;
    }
    if (!moov) throw new Error('no moov');
    const idx = new Uint8Array((ftyp?.byteLength || 0) + moov.byteLength);
    if (ftyp) idx.set(ftyp, 0);
    idx.set(moov, ftyp?.byteLength || 0);
    // 目次を読むのは裏の処理で（長い録画では画面が0.2〜0.4秒止まっていた。2026-11-19）
    const ix = await readMp4Index(idx, 'audio');
    if (ix.kind !== 'audio') throw new Error('bad index');
    this.duration = ix.duration;
    if (ix.silent && !ix.codec) { this.silent = true; return; }
    this.codec = ix.codec;
    this.sampleRate = ix.sampleRate;
    this.channels = ix.channels;
    if (ix.description) this.description = ix.description;
    const n = ix.pt.length;
    const samples: ASample[] = new Array(n);
    for (let i = 0; i < n; i++) samples[i] = { pt: ix.pt[i], dur: ix.dur[i], offset: ix.offset[i], size: ix.size[i] };
    this.samples = samples;
    if (!this.samples.length) { this.silent = true; return; }
    const support = await AudioDecoder.isConfigSupported(this.decoderConfig()).catch(() => ({ supported: false }));
    if (!support.supported) throw new Error(`codec not supported ${this.codec}`);
  }

  private async initWhole(head: { buf: ArrayBuffer; partial: boolean; total: number }) {
    let buf = head.buf;
    if (head.partial) {
      if (head.total > WHOLE_FILE_LIMIT) throw new Error('too large to decode whole');
      buf = (await this.fetchRange(0, head.total - 1)).buf;
    }
    this.whole = await this.ctx.decodeAudioData(buf.slice(0));
    this.duration = this.whole.duration;
  }

  private decoderConfig(): AudioDecoderConfig {
    return {
      codec: this.codec,
      sampleRate: this.sampleRate,
      numberOfChannels: this.channels,
      ...(this.description ? { description: this.description } : {}),
    };
  }

  /** 素材の時刻 [s0, s1] の音を解読しておく（済んでいれば何もしない） */
  ensure(s0: number, s1: number): Promise<void> {
    if (this.failed || this.silent || this.whole || this.closed || !this.samples.length) return Promise.resolve();
    const b0 = Math.max(0, Math.floor(s0 / BLOCK_SEC));
    const b1 = Math.max(b0, Math.floor(Math.max(s0, s1 - 1e-6) / BLOCK_SEC));
    const all: Promise<void>[] = [];
    for (let b = b0; b <= b1; b++) all.push(this.loadBlock(b));
    return Promise.all(all).then(() => undefined);
  }

  private loadBlock(b: number): Promise<void> {
    const have = this.blocks.get(b);
    if (have) { this.blocks.delete(b); this.blocks.set(b, have); return Promise.resolve(); }
    const inflight = this.loads.get(b);
    if (inflight) return inflight;
    const p = this.decodeBlock(b)
      .then((buf) => {
        if (this.closed || !buf) return;
        this.blocks.set(b, buf);
        while (this.blocks.size > MAX_BLOCKS) {
          const first = this.blocks.keys().next().value as number;
          this.blocks.delete(first);
        }
      })
      .catch((e) => { console.warn('[audio-source] block failed', this.url, b, e); })
      .finally(() => { this.loads.delete(b); });
    this.loads.set(b, p);
    return p;
  }

  private async decodeBlock(b: number): Promise<AudioBuffer | null> {
    const start = b * BLOCK_SEC;
    const end = start + BLOCK_SEC;
    // 前の2つの断片も解読して捨てる（AAC は前の断片と重ねて音を作るので、途中からだと最初が崩れる）
    let i0 = this.lowerBound(start);
    i0 = Math.max(0, i0 - 2);
    let i1 = this.lowerBound(end);
    i1 = Math.min(this.samples.length, i1 + 1);
    if (i0 >= i1) return null;
    const want = this.samples.slice(i0, i1);
    // バイトの範囲をまとめて読む（映像の分はできるだけ飛ばす）
    const order = want.map((s, k) => ({ s, k })).sort((a, c) => a.s.offset - c.s.offset);
    const runs: Array<{ lo: number; hi: number; items: typeof order }> = [];
    for (const it of order) {
      const last = runs[runs.length - 1];
      if (last && it.s.offset - last.hi <= RANGE_GAP) { last.hi = Math.max(last.hi, it.s.offset + it.s.size); last.items.push(it); }
      else runs.push({ lo: it.s.offset, hi: it.s.offset + it.s.size, items: [it] });
    }
    const data: Uint8Array[] = new Array(want.length);
    await Promise.all(runs.map(async (r) => {
      const { buf } = await this.fetchRange(r.lo, r.hi - 1);
      const u8 = new Uint8Array(buf);
      for (const it of r.items) data[it.k] = u8.subarray(it.s.offset - r.lo, it.s.offset - r.lo + it.s.size);
    }));
    if (this.closed) return null;
    const frames = Math.round(BLOCK_SEC * this.sampleRate);
    const out = this.ctx.createBuffer(this.channels, frames, this.sampleRate);
    const planes = Array.from({ length: this.channels }, (_, c) => out.getChannelData(c));
    await new Promise<void>((resolve, reject) => {
      const dec = new AudioDecoder({
        output: (ad) => {
          try {
            const at = Math.round((ad.timestamp / 1e6 - start) * this.sampleRate);
            const n = ad.numberOfFrames;
            const from = Math.max(0, -at);
            const to = Math.min(n, frames - at);
            if (to > from) {
              const tmp = new Float32Array(n);
              for (let c = 0; c < this.channels; c++) {
                const srcPlane = Math.min(c, ad.numberOfChannels - 1);
                ad.copyTo(tmp, { planeIndex: srcPlane, format: 'f32-planar' });
                planes[c].set(tmp.subarray(from, to), at + from);
              }
            }
          } finally {
            ad.close();
          }
        },
        error: (e) => reject(e),
      });
      dec.configure(this.decoderConfig());
      for (let k = 0; k < want.length; k++) {
        const s = want[k];
        dec.decode(new EncodedAudioChunk({ type: 'key', timestamp: Math.round(s.pt * 1e6), duration: Math.round(s.dur * 1e6), data: data[k] }));
      }
      dec.flush().then(() => { dec.close(); resolve(); }, (e) => { try { dec.close(); } catch { /* noop */ } reject(e); });
    });
    return out;
  }

  private lowerBound(t: number): number {
    let lo = 0, hi = this.samples.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (this.samples[m].pt < t) lo = m + 1; else hi = m; }
    return lo;
  }

  /** 素材の時刻 [s0, s1] を鳴らすための解読済みの区間。まだ解読できていない所があれば、その手前まで */
  segments(s0: number, s1: number): { segs: AudioSegment[]; complete: boolean } {
    if (this.whole) {
      const a = Math.max(0, s0), z = Math.min(this.whole.duration, s1);
      return { segs: z > a ? [{ buffer: this.whole, bufOffset: a, srcStart: a, srcEnd: z }] : [], complete: true };
    }
    const segs: AudioSegment[] = [];
    if (this.failed || this.silent || s1 <= s0) return { segs, complete: true };
    let t = Math.max(0, s0);
    while (t < s1 - 1e-6) {
      const b = Math.floor(t / BLOCK_SEC);
      const buf = this.blocks.get(b);
      if (!buf) return { segs, complete: false };
      const bs = b * BLOCK_SEC;
      const z = Math.min(s1, bs + BLOCK_SEC);
      segs.push({ buffer: buf, bufOffset: t - bs, srcStart: t, srcEnd: z });
      t = z;
    }
    return { segs, complete: true };
  }

  /** 解読の区切りの長さ（丸ごとの素材は全体で1つ） */
  blockLen(): number {
    return this.whole ? this.whole.duration + 1 : BLOCK_SEC;
  }

  /** 区切り b の解読済みの音（まだなら null）。丸ごとの素材は b=0 だけ */
  blockBuffer(b: number): AudioBuffer | null {
    if (this.whole) return b === 0 ? this.whole : null;
    return this.blocks.get(b) || null;
  }

  private stretched = new Map<string, { buffer: AudioBuffer; srcDur: number }>();

  /** 区切り b（STRETCH_BLOCK_SEC ずつ）を rate 倍速に縮めた音（声の高さはそのまま）。srcDur はその区切りの素材の長さ。
   *  解読がまだなら null。作った物は覚えておく */
  stretchedBlock(b: number, rate: number): { buffer: AudioBuffer; srcDur: number } | null {
    const key = `${b}|${rate}`;
    const have = this.stretched.get(key);
    if (have) return have;
    const S = STRETCH_BLOCK_SEC;
    let src: AudioBuffer | null = null;
    let from = 0, len = 0;
    if (this.whole) {
      src = this.whole;
      from = Math.round(b * S * src.sampleRate);
      len = Math.min(src.length, Math.round((b + 1) * S * src.sampleRate)) - from;
    } else {
      src = this.blocks.get(b) || null;
      len = src ? src.length : 0;
    }
    if (!src || len <= 0) return null;
    const chans = Array.from({ length: src.numberOfChannels }, (_, c) => src!.getChannelData(c).subarray(from, from + len));
    const outCh = stretchChannels(chans, src.sampleRate, rate);
    const buffer = this.ctx.createBuffer(outCh.length, outCh[0].length, src.sampleRate);
    outCh.forEach((d, c) => buffer.getChannelData(c).set(d));
    const got = { buffer, srcDur: len / src.sampleRate };
    this.stretched.set(key, got);
    while (this.stretched.size > MAX_STRETCHED) this.stretched.delete(this.stretched.keys().next().value as string);
    return got;
  }

  /** 倍速の区切り b の音がもう縮めてあるか */
  hasStretched(b: number, rate: number): boolean {
    return this.stretched.has(`${b}|${rate}`);
  }

  /** 鳴らす物が無い（音の無い素材・壊れた素材） */
  get mute(): boolean {
    return this.failed || this.silent;
  }

  /** この時刻の音が鳴らせる状態か（解読済み・音が無い・壊れた、のどれか＝待たなくてよい） */
  hasAt(s: number): boolean {
    if (this.failed || this.silent || this.whole) return true;
    if (!this.samples.length) return false;
    // 素材の終わりより先は無音（待っても読めない。待つと再生を押すたびに6秒止まる）
    if (this.duration > 0 && s >= this.duration - 0.02) return true;
    return this.blocks.has(Math.floor(Math.max(0, s) / BLOCK_SEC));
  }

  close() {
    this.closed = true;
    this.blocks.clear();
    this.stretched.clear();
    this.whole = null;
  }
}

/** 素材ごとに1つ。AudioContext も持つ（最初の操作の時に作る） */
export class AudioSourceManager {
  readonly ctx: AudioContext;
  readonly master: GainNode;
  private sources = new Map<string, AssetAudioSource>();

  constructor() {
    this.ctx = new AudioContext({ latencyHint: 'interactive' });
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
  }

  get(url: string): AssetAudioSource | null {
    if (!url) return null;
    let s = this.sources.get(url);
    if (!s) { s = new AssetAudioSource(url, this.ctx); this.sources.set(url, s); }
    return s;
  }

  retain(urls: Set<string>) {
    for (const [url, s] of this.sources) if (!urls.has(url)) { s.close(); this.sources.delete(url); }
  }

  close() {
    for (const s of this.sources.values()) s.close();
    this.sources.clear();
    void this.ctx.close().catch(() => {});
  }
}
