// WebCodecs-based frame source: the heart of the "DaVinci-style" preview engine.
//
// Why this exists: the old preview composited from a pool of HTML5 <video> elements
// (one per clip). <video> is built for streaming playback, not frame-accurate random
// access — every edit (a split makes new clip ids, a ripple shifts every clip) forced
// elements to reload / re-seek, and during that async reload the canvas had no decoded
// frame to draw, so it went BLACK and stayed black for seconds on heavy timelines.
//
// A native NLE (DaVinci / Premiere) instead keeps DECODED FRAMES in a cache and composites
// the current frame from that cache; edits only touch the data model, never the media. This
// module is that cache: one decoder per ASSET (not per clip), demuxed with mp4box and decoded
// with WebCodecs into a bounded LRU of GPU ImageBitmaps keyed by frame index. Editing reshuffles
// which cached frame is drawn where — it never reloads media, so no black, no stall, and
// scrubbing is frame-accurate.

import { createFile, DataStream, type MP4File, type MP4Sample, type MP4ArrayBuffer } from 'mp4box';

export function webCodecsSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.VideoDecoder !== 'undefined';
}


type Sample = {
  cts: number;        // presentation time, seconds
  dur: number;        // seconds
  ctsUs: number;      // presentation time, microseconds (matches VideoFrame.timestamp)
  isSync: boolean;
  data: Uint8Array;   // encoded frame bytes (decode order)
};

const MAX_CACHED_FRAMES = 96; // ~3s at 30fps; bounded so a 13-min proxy never blows memory

export class AssetFrameSource {
  readonly url: string;
  ready: Promise<void>;
  width = 0;
  height = 0;
  duration = 0;
  failed = false;

  // Samples in DECODE order (as mp4box delivers them). For B-frames, decode order ≠
  // presentation order, so we keep a separate cts-sorted index for time lookups, and we map
  // decoder outputs back to a sample by their (unique) cts in microseconds.
  private samples: Sample[] = [];
  private presOrder: number[] = []; // decode indices sorted by cts ascending
  private ctsToIndex = new Map<number, number>();
  private codec = '';
  private description?: Uint8Array;

  private decoder: VideoDecoder | null = null;
  private cache = new Map<number, ImageBitmap>(); // decodeIndex -> decoded frame (GPU bitmap)
  private lru: number[] = [];                      // decodeIndex, most-recent last
  private protectedIndex = -1;                     // never evict the frame at/around the playhead
  private closed = false;

  // Decoder feed cursor: the current contiguous run spans samples [fedFrom .. fedThrough] in
  // decode order, starting at a keyframe. -1 = nothing fed yet. We never re-feed a chunk that's
  // already in this run — re-feeding duplicate-timestamp chunks restarts the decoder at the
  // keyframe and stalls it (it never reaches later frames).
  private fedFrom = -1;
  private fedThrough = -1;
  private configured = false;
  // Coalescing scrub seeks: requests collect here and a single drain loop decodes them,
  // LATEST-FIRST and dropping stale intermediates, so fast scrubbing jumps straight to where
  // the playhead landed instead of grinding through every frame it swept past.
  private pendingTargets = new Set<number>();
  private draining = false;
  private drainPromise: Promise<void> = Promise.resolve();

  constructor(url: string) {
    this.url = url;
    this.ready = this.init().catch((e) => {
      this.failed = true;
      // Leave the source unusable; the preview falls back to black for this asset.
      console.warn('[frame-source] init failed for', url, e);
    });
  }

  private async init(): Promise<void> {
    const res = await fetch(this.url);
    if (!res.ok) throw new Error(`fetch ${res.status}`);
    const buf = (await res.arrayBuffer()) as MP4ArrayBuffer;
    buf.fileStart = 0;

    const file: MP4File = createFile();
    const trackInfo = await new Promise<{ id: number; codec: string }>((resolve, reject) => {
      file.onError = (e) => reject(new Error(String(e)));
      file.onReady = (info) => {
        const vt = info.videoTracks?.[0];
        if (!vt) return reject(new Error('no video track'));
        this.duration = info.duration / (info.timescale || 1);
        this.width = vt.track_width;
        this.height = vt.track_height;
        this.description = extractDescription(file, vt.id);
        resolve({ id: vt.id, codec: vt.codec });
      };
      file.appendBuffer(buf);
      file.flush();
    });
    this.codec = trackInfo.codec;

    // Pull every sample's metadata + encoded bytes (one pass; the proxy is small, ~18MB).
    await new Promise<void>((resolve) => {
      file.onSamples = (_id, _user, samples: MP4Sample[]) => {
        for (const s of samples) {
          const cts = s.cts / s.timescale;
          const ctsUs = Math.round((s.cts / s.timescale) * 1e6);
          this.samples.push({ cts, dur: s.duration / s.timescale, ctsUs, isSync: s.is_sync, data: s.data });
        }
        if (this.samples.length >= 0 && samples.length === 0) resolve();
      };
      file.setExtractionOptions(trackInfo.id, null, { nbSamples: Number.POSITIVE_INFINITY });
      file.start();
      file.flush();
      // mp4box delivers all samples synchronously within start()/flush() for a fully-appended
      // file; resolve on the next microtask once they've landed.
      Promise.resolve().then(resolve);
    });

    if (!this.samples.length) throw new Error('no samples');
    this.presOrder = this.samples.map((_, i) => i).sort((a, b) => this.samples[a].cts - this.samples[b].cts);
    this.samples.forEach((s, i) => this.ctsToIndex.set(s.ctsUs, i));
    if (!this.duration) {
      const last = this.samples[this.presOrder[this.presOrder.length - 1]];
      this.duration = last.cts + last.dur;
    }
    this.configureDecoder();
  }

  private configureDecoder() {
    if (this.decoder) { try { this.decoder.close(); } catch { /* already closed */ } }
    this.decoder = new VideoDecoder({
      output: (frame) => this.onFrame(frame),
      error: (e) => { console.warn('[frame-source] decoder error', this.url, e); this.recover(); },
    });
    this.decoder.configure({
      codec: this.codec,
      codedWidth: this.width,
      codedHeight: this.height,
      ...(this.description ? { description: this.description } : {}),
      optimizeForLatency: true,
    });
    this.configured = true;
    this.fedFrom = -1;
    this.fedThrough = -1;
  }

  private recover() {
    // Decoder fell over (corrupt chunk / context loss): rebuild it and let the next request
    // re-feed from a keyframe. Cached frames stay valid.
    this.configured = false;
    try { this.configureDecoder(); } catch { this.failed = true; }
  }

  private frameWaiters = new Map<number, Array<() => void>>();
  private onFrame(frame: VideoFrame) {
    const idx = this.ctsToIndex.get(frame.timestamp);
    if (idx == null) { frame.close(); return; }
    // CRITICAL: copy into a GPU ImageBitmap and close the VideoFrame immediately. A decoder has
    // a SMALL pool of output buffers; holding decoded VideoFrames in the cache exhausts it and
    // the decoder STALLS (it stops emitting after ~16-20 frames). ImageBitmaps are detached from
    // that pool, so the decoder keeps flowing while we cache as many frames as we like.
    createImageBitmap(frame).then((bmp) => {
      frame.close();
      if (this.closed) { bmp.close(); return; }
      const existing = this.cache.get(idx);
      if (existing) existing.close();
      this.cache.set(idx, bmp);
      this.touch(idx);
      this.evict();
      const waiters = this.frameWaiters.get(idx);
      if (waiters) { this.frameWaiters.delete(idx); for (const w of waiters) w(); }
    }).catch(() => { try { frame.close(); } catch { /* already closed */ } });
  }

  private waitForFrame(idx: number): Promise<void> {
    if (this.cache.has(idx)) return Promise.resolve();
    return new Promise((resolve) => {
      const arr = this.frameWaiters.get(idx) || [];
      arr.push(resolve);
      this.frameWaiters.set(idx, arr);
    });
  }

  private touch(idx: number) {
    const at = this.lru.indexOf(idx);
    if (at >= 0) this.lru.splice(at, 1);
    this.lru.push(idx);
  }

  private evict() {
    while (this.cache.size > MAX_CACHED_FRAMES && this.lru.length) {
      const victim = this.lru[0];
      if (victim === this.protectedIndex) {
        // don't evict the on-screen frame; rotate it to the back and stop if it's the only one
        if (this.lru.length === 1) break;
        this.lru.push(this.lru.shift()!);
        continue;
      }
      this.lru.shift();
      const f = this.cache.get(victim);
      if (f) { f.close(); this.cache.delete(victim); }
    }
  }

  // --- time <-> frame index -------------------------------------------------

  // Presentation-order POSITION of the last sample whose cts <= timeSec (-1 if none).
  private presPosAtTime(timeSec: number): number {
    const po = this.presOrder;
    if (!po.length) return -1;
    let lo = 0, hi = po.length - 1, ans = 0;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.samples[po[mid]].cts <= timeSec + 1e-6) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  }

  private indexAtTime(timeSec: number): number {
    const pos = this.presPosAtTime(timeSec);
    return pos < 0 ? -1 : this.presOrder[pos];
  }

  private keyframeFor(decodeIndex: number): number {
    for (let i = decodeIndex; i >= 0; i--) if (this.samples[i].isSync) return i;
    return 0;
  }

  // --- public draw/seek API -------------------------------------------------

  /** Best cached frame to display at `timeSec`, or null if not decoded yet. Synchronous — safe
   *  to call inside the rAF draw loop. `rangeLo`/`rangeHi` are the CLIP's source-time bounds:
   *  the fallback (when the exact frame isn't decoded yet) only returns a frame WITHIN that
   *  range. This is the cut-frame fix — a clip can never display another clip's / a trimmed-out
   *  region's footage, but it also won't go black as long as any of its own frames are cached
   *  (showing a slightly stale frame of the SAME clip while the exact one decodes). */
  peek(timeSec: number, rangeLo: number, rangeHi: number): ImageBitmap | null {
    if (this.failed || !this.samples.length) return null;
    const pos = this.presPosAtTime(timeSec);
    if (pos < 0) return null;
    const idx = this.presOrder[pos];
    const f = this.cache.get(idx);
    if (f) { this.protectedIndex = idx; this.touch(idx); return f; }
    // Nearest cached frame within [rangeLo, rangeHi] — walk outward from `pos`, preferring the
    // previous frame, then a slightly-later one, never crossing the clip's source bounds.
    for (let back = pos - 1; back >= 0; back--) {
      const di = this.presOrder[back];
      if (this.samples[di].cts < rangeLo - 1e-6) break;
      const cf = this.cache.get(di);
      if (cf) return cf;
    }
    for (let fwd = pos + 1; fwd < this.presOrder.length; fwd++) {
      const di = this.presOrder[fwd];
      if (this.samples[di].cts > rangeHi + 1e-6) break;
      const cf = this.cache.get(di);
      if (cf) return cf;
    }
    return null;
  }

  /** Decode the exact frame for `timeSec` (frame-accurate scrub). Resolves once it's cached.
   *  Single-flight: repeat calls for the same target share one decode; different targets queue. */
  seekTo(timeSec: number): Promise<void> {
    const target = this.indexAtTime(timeSec);
    if (target < 0) return Promise.resolve();
    if (this.cache.has(target)) { this.protectedIndex = target; this.touch(target); return Promise.resolve(); }
    // Drop stale scrub intermediates: while a drag is in flight, only the few most-recent
    // targets matter (one per active clip). Capping prevents a fast sweep from queueing dozens.
    if (this.pendingTargets.size >= 4) this.pendingTargets.clear();
    this.pendingTargets.add(target);
    if (!this.draining) this.drainPromise = this.drainSeeks();
    return this.drainPromise;
  }

  private async drainSeeks(): Promise<void> {
    this.draining = true;
    try {
      while (this.pendingTargets.size) {
        const arr = [...this.pendingTargets];
        const t = arr[arr.length - 1]; // latest-added first = where the playhead is now
        this.pendingTargets.delete(t);
        if (!this.cache.has(t)) await this.decodeExact(t);
      }
    } finally {
      this.draining = false;
    }
  }

  private async decodeExact(target: number): Promise<void> {
    if (this.failed || target < 0 || this.cache.has(target)) { if (target >= 0) this.protectedIndex = target; return; }
    const dec = this.decoder;
    if (!dec || !this.configured) return;

    const key = this.keyframeFor(target);
    const REORDER = 3; // feed a few frames past the target so B-frames can be reordered out
    const end = Math.min(this.samples.length - 1, target + REORDER);
    // Decide the feed range without ever re-feeding chunks already in the current run (duplicate
    // timestamps stall the decoder). Three cases:
    //  - target already inside the fed run  -> feed only the tail past fedThrough (for REORDER)
    //  - contiguous forward extension        -> continue from fedThrough+1
    //  - backward / gap seek                 -> start a fresh run at the keyframe (IDR resync)
    let start: number;
    if (this.fedFrom >= 0 && this.fedFrom <= key && this.fedThrough >= target) {
      start = this.fedThrough + 1; // already fed through target; just top up the reorder tail
    } else if (this.fedFrom >= 0 && this.fedFrom <= key && this.fedThrough < target) {
      start = this.fedThrough + 1; // contiguous forward
    } else {
      start = key; this.fedFrom = key; // new run
    }
    const wait = this.waitForFrame(target);
    for (let i = start; i <= end; i++) this.feed(i);
    this.fedThrough = Math.max(this.fedThrough, end);
    // The waiter resolves the instant onFrame() caches the target. The timeout is a safety cap.
    await Promise.race([wait, delay(4000)]);
    this.protectedIndex = target;
  }

  /** Lightweight status for the on-screen diagnostic (why a frame might not be showing). */
  status(): string {
    if (this.failed) return 'FAILED';
    if (!this.samples.length) return 'loading';
    return `cache=${this.cache.size} q=${this.decoder?.decodeQueueSize ?? '?'} dec=${this.decoder?.state ?? '?'}${this.draining ? ' drain' : ''}`;
  }

  /** Keep decoding forward from the playhead so upcoming frames are ready during playback.
   *  Non-blocking; feeds a window ahead without flushing (frames emit as refs arrive). */
  prefetch(timeSec: number, aheadSec: number): void {
    if (this.failed || !this.decoder || !this.configured) return;
    if (this.draining) return; // don't fight an in-flight scrub decode for the same decoder
    const target = this.indexAtTime(timeSec + aheadSec);
    if (target < 0) return;
    const from = this.indexAtTime(timeSec);
    const key = this.keyframeFor(from);
    let start: number;
    if (this.fedFrom >= 0 && this.fedFrom <= key && this.fedThrough < target) {
      start = this.fedThrough + 1; // contiguous forward extension
    } else if (this.fedFrom >= 0 && this.fedFrom <= key && this.fedThrough >= target) {
      return; // already fed past the window (no duplicate feeds)
    } else {
      start = key; this.fedFrom = key; // new run at the keyframe (IDR resync)
    }
    // Cap in-flight work so we never queue thousands of chunks at once.
    const end = Math.min(target, start + 60);
    if (end < start) return;
    for (let i = start; i <= end; i++) this.feed(i);
    this.fedThrough = Math.max(this.fedThrough, end);
  }

  private feed(i: number) {
    const dec = this.decoder;
    const s = this.samples[i];
    if (!dec || !s || dec.state !== 'configured') return;
    // Always feed in a contiguous run (never skip a cached frame) — the decoder needs every
    // chunk in sequence to produce the frames that follow. onFrame() de-dupes the output.
    try {
      dec.decode(new EncodedVideoChunk({
        type: s.isSync ? 'key' : 'delta',
        timestamp: s.ctsUs,
        duration: Math.round(s.dur * 1e6),
        data: s.data,
      }));
    } catch { /* decoder reset under us */ }
  }

  close() {
    this.closed = true;
    if (this.decoder) { try { this.decoder.close(); } catch { /* noop */ } this.decoder = null; }
    for (const f of this.cache.values()) f.close();
    this.cache.clear();
    this.lru = [];
    this.frameWaiters.clear();
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// Extract the codec-private description (avcC / hvcC / ...) mp4box parsed, stripped of its
// 8-byte box header — exactly what VideoDecoderConfig.description wants for avc1/hvc1.
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

// ---------------------------------------------------------------------------

/** Owns one AssetFrameSource per asset URL; created/destroyed as the asset set changes. */
export class FrameSourceManager {
  private sources = new Map<string, AssetFrameSource>();

  get(url: string): AssetFrameSource | null {
    if (!url) return null;
    let s = this.sources.get(url);
    if (!s) { s = new AssetFrameSource(url); this.sources.set(url, s); }
    return s;
  }

  /** Drop sources whose url is no longer present, freeing their decoders/frames. */
  retain(urls: Set<string>) {
    for (const [url, s] of this.sources) {
      if (!urls.has(url)) { s.close(); this.sources.delete(url); }
    }
  }

  closeAll() {
    for (const s of this.sources.values()) s.close();
    this.sources.clear();
  }
}
