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

import { createFile, DataStream, type MP4File, type MP4ArrayBuffer } from 'mp4box';

export function webCodecsSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.VideoDecoder !== 'undefined';
}


type Sample = {
  cts: number;        // presentation time, seconds
  dur: number;        // seconds
  ctsUs: number;      // presentation time, microseconds (matches VideoFrame.timestamp)
  isSync: boolean;
  offset: number;     // byte offset of the encoded frame in the file
  size: number;       // encoded frame size in bytes
};

const MAX_CACHED_FRAMES = 96; // ~3s at 30fps; bounded so a 13-min proxy never blows memory

// RANGE LOADING (2026-11-12): the proxy used to be fetched WHOLE into memory before the first
// frame. That was fine for an 18MB proxy, but an 83-min recording's proxy is 14GB — the tab sat
// on "素材を準備中" forever and Chrome died of out-of-memory, taking other tabs with it. Now we
// read only the index (moov, a few MB) up front and fetch encoded frames by HTTP Range in
// ~3-second blocks around the playhead, keeping a bounded number of blocks. Memory no longer
// depends on the recording's length.
const BLOCK_SAMPLES = 90;                      // ~3s at 30fps per Range request
const MAX_BLOCK_BYTES = 96 * 1024 * 1024;      // encoded bytes kept in memory per asset
const HEAD_BYTES = 64 * 1024;                  // first request: top-level box headers
const WHOLE_FILE_LIMIT = 160 * 1024 * 1024;    // server ignored Range: accept only small files

type Block = { data: Uint8Array; lo: number; bytes: number };

export class AssetFrameSource {
  readonly url: string;
  ready: Promise<void>;
  width = 0;
  height = 0;
  duration = 0;
  failed = false;

  // Samples in DECODE order (as mp4box lists them). For B-frames, decode order ≠
  // presentation order, so we keep a separate cts-sorted index for time lookups, and we map
  // decoder outputs back to a sample by their (unique) cts in microseconds.
  private samples: Sample[] = [];
  private presOrder: number[] = []; // decode indices sorted by cts ascending
  private ctsToIndex = new Map<number, number>();
  private codec = '';
  private description?: Uint8Array;

  // Encoded bytes: either the whole (small) file when the server ignored Range, or blocks.
  private wholeFile: Uint8Array | null = null;
  private blocks = new Map<number, Block>();          // block number -> bytes (Map order = LRU)
  private blockLoads = new Map<number, Promise<void>>();
  private blockBytes = 0;
  private pinnedBlocks = new Set<number>();           // blocks the current decode run needs

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
  private prefetching = false;

  constructor(url: string) {
    this.url = url;
    this.ready = this.init().catch((e) => {
      this.failed = true;
      // Leave the source unusable; the preview falls back to black for this asset.
      console.warn('[frame-source] init failed for', url, e);
    });
  }

  private async fetchRange(lo: number, hi: number): Promise<{ buf: ArrayBuffer; total: number; partial: boolean }> {
    const ctl = new AbortController();
    const res = await fetch(this.url, { headers: { Range: `bytes=${lo}-${hi}` }, signal: ctl.signal });
    if (!res.ok) throw new Error(`fetch ${res.status}`);
    if (res.status === 206) {
      const m = /\/(\d+)\s*$/.exec(res.headers.get('Content-Range') || '');
      return { buf: await res.arrayBuffer(), total: m ? Number(m[1]) : 0, partial: true };
    }
    // 200: the server sent the whole file. Only acceptable when it's small.
    const len = Number(res.headers.get('Content-Length') || 0);
    if (!len || len > WHOLE_FILE_LIMIT) { ctl.abort(); throw new Error(`no range support (size ${len || '?'})`); }
    const buf = await res.arrayBuffer();
    return { buf, total: buf.byteLength, partial: false };
  }

  private async init(): Promise<void> {
    // 1) Find ftyp + moov by walking top-level box headers (moov may sit before or after mdat).
    const head = await this.fetchRange(0, HEAD_BYTES - 1);
    if (!head.partial) this.wholeFile = new Uint8Array(head.buf);
    const total = head.total;
    const headBytes = new Uint8Array(head.buf);
    const readAt = async (pos: number, len: number): Promise<Uint8Array> => {
      if (this.wholeFile) return this.wholeFile.subarray(pos, pos + len);
      if (pos + len <= headBytes.byteLength) return headBytes.subarray(pos, pos + len);
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

    // 2) Parse only ftyp+moov with mp4box (sample offsets in stco/co64 are absolute file offsets,
    //    so the synthetic buffer's layout doesn't matter).
    const idx = new Uint8Array((ftyp?.byteLength || 0) + moov.byteLength);
    if (ftyp) idx.set(ftyp, 0);
    idx.set(moov, ftyp?.byteLength || 0);
    const ab = idx.buffer as MP4ArrayBuffer;
    ab.fileStart = 0;
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
      file.appendBuffer(ab);
      file.flush();
      setTimeout(() => reject(new Error('moov parse timeout')), 5000);
    });
    this.codec = trackInfo.codec;
    for (const s of file.getTrackSamplesInfo(trackInfo.id) || []) {
      this.samples.push({
        cts: s.cts / s.timescale, dur: s.duration / s.timescale,
        ctsUs: Math.round((s.cts / s.timescale) * 1e6), isSync: s.is_sync,
        offset: s.offset, size: s.size,
      });
    }

    if (!this.samples.length) throw new Error('no samples');
    this.presOrder = this.samples.map((_, i) => i).sort((a, b) => this.samples[a].cts - this.samples[b].cts);
    this.samples.forEach((s, i) => this.ctsToIndex.set(s.ctsUs, i));
    if (!this.duration) {
      const last = this.samples[this.presOrder[this.presOrder.length - 1]];
      this.duration = last.cts + last.dur;
    }
    this.configureDecoder();
  }

  // --- encoded bytes on demand ------------------------------------------------

  private loadBlock(b: number): Promise<void> {
    if (this.wholeFile || this.blocks.has(b)) {
      const blk = this.blocks.get(b);
      if (blk) { this.blocks.delete(b); this.blocks.set(b, blk); } // touch (LRU)
      return Promise.resolve();
    }
    const inflight = this.blockLoads.get(b);
    if (inflight) return inflight;
    const from = b * BLOCK_SAMPLES;
    const to = Math.min(this.samples.length, from + BLOCK_SAMPLES) - 1;
    let lo = Infinity, hi = -1;
    for (let i = from; i <= to; i++) {
      const s = this.samples[i];
      if (s.offset < lo) lo = s.offset;
      if (s.offset + s.size > hi) hi = s.offset + s.size;
    }
    const p = (async () => {
      try {
        const { buf } = await this.fetchRange(lo, hi - 1);
        if (this.closed) return;
        this.blocks.set(b, { data: new Uint8Array(buf), lo, bytes: buf.byteLength });
        this.blockBytes += buf.byteLength;
        this.evictBlocks();
      } finally {
        this.blockLoads.delete(b);
      }
    })();
    this.blockLoads.set(b, p);
    return p;
  }

  private evictBlocks() {
    for (const [b, blk] of this.blocks) {
      if (this.blockBytes <= MAX_BLOCK_BYTES) break;
      if (this.pinnedBlocks.has(b)) continue;
      this.blocks.delete(b);
      this.blockBytes -= blk.bytes;
    }
  }

  /** Make sure encoded bytes for decode-order samples [from..to] are in memory. */
  private async ensureData(from: number, to: number): Promise<void> {
    if (this.wholeFile) return;
    const b0 = Math.floor(from / BLOCK_SAMPLES), b1 = Math.floor(to / BLOCK_SAMPLES);
    const need: number[] = [];
    for (let b = b0; b <= b1; b++) need.push(b);
    this.pinnedBlocks = new Set(need);
    await Promise.all(need.map((b) => this.loadBlock(b)));
  }

  private sampleData(i: number): Uint8Array | null {
    const s = this.samples[i];
    if (!s) return null;
    if (this.wholeFile) return this.wholeFile.subarray(s.offset, s.offset + s.size);
    const blk = this.blocks.get(Math.floor(i / BLOCK_SAMPLES));
    if (!blk) return null;
    return blk.data.subarray(s.offset - blk.lo, s.offset - blk.lo + s.size);
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
    // Decoding a GOP to reach one seek target emits ~all of its frames, but we only WANT the ones
    // near the playhead. Turning every emitted frame into an ImageBitmap is async, and each frame
    // stays alive (holding a decoder output buffer) until its bitmap resolves — on a hardware
    // (GPU) decoder that backlog EXHAUSTS the small output-buffer pool and the decoder STALLS
    // mid-scrub (the headed-Chrome repro: cache full, q=0, frame never emitted). So we only
    // bitmap-copy frames that are wanted (a waiter is parked on them, or they're near the current
    // target); every other frame is closed IMMEDIATELY, freeing its buffer so decode keeps flowing.
    const wanted = this.frameWaiters.has(idx) || Math.abs(idx - this.protectedIndex) <= 6;
    if (!wanted) { frame.close(); return; }
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

  /** True when the decoder's current run already covers up to (at least) the frame before `key`,
   *  so feeding on from fedThrough+1 reaches `key`'s GOP without decoding a gap. */
  private runReaches(key: number): boolean {
    return this.fedFrom >= 0 && this.fedFrom <= key && this.fedThrough >= key - 1;
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
    this.lastShownTime = -1;
    if (this.failed || !this.samples.length) return null;
    const pos = this.presPosAtTime(timeSec);
    if (pos < 0) return null;
    const idx = this.presOrder[pos];
    const f = this.cache.get(idx);
    if (f) { this.protectedIndex = idx; this.touch(idx); this.lastShownTime = this.samples[idx].cts; return f; }
    // Fallback: nearest cached frame, but ONLY within a tiny staleness window AND within the
    // clip's source bounds. The tiny window is the key fix — a wide fallback returned a frame far
    // from the playhead (showing a frozen, stale frame while the head moved on, especially when
    // GPU decode lagged behind a scrub). Beyond the window we return null so the compositor HOLDS
    // the last good frame instead — never a wrong/old frame masquerading as the current one.
    const MAX_STALE = 0.18; // seconds
    for (let back = pos - 1; back >= 0; back--) {
      const di = this.presOrder[back];
      const cts = this.samples[di].cts;
      if (cts < rangeLo - 1e-6 || timeSec - cts > MAX_STALE) break;
      const cf = this.cache.get(di);
      if (cf) { this.lastShownTime = cts; return cf; }
    }
    for (let fwd = pos + 1; fwd < this.presOrder.length; fwd++) {
      const di = this.presOrder[fwd];
      const cts = this.samples[di].cts;
      if (cts > rangeHi + 1e-6 || cts - timeSec > MAX_STALE) break;
      const cf = this.cache.get(di);
      if (cf) { this.lastShownTime = cts; return cf; }
    }
    return null;
  }

  /** Source time (seconds) of the frame the LAST peek() returned (-1 if none) — for diagnostics. */
  lastShownTime = -1;

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
    this.protectedIndex = target; // mark the target NOW so onFrame keeps it (and its neighbours)

    const key = this.keyframeFor(target);
    // Feed several frames PAST the target so it falls out of the decoder's reorder buffer without a
    // flush(). This is generous because, with the bitmap-throttle in onFrame, the extra frames are
    // decode-only (closed immediately) — cheap.
    const REORDER = 12;
    const end = Math.min(this.samples.length - 1, target + REORDER);
    // Decide the feed range without ever re-feeding chunks already in the current run (duplicate
    // timestamps stall the decoder). The current run is only worth continuing when it already
    // reaches this GOP's keyframe; any further back (a jump forward across a gap) we start a fresh
    // run at the keyframe instead. (2026-11-12: "continue" used to also cover big gaps, so a jump
    // from 3:00 to 40:00 fetched and decoded every frame in between — ~100MB and 1.3-2s even
    // locally, far worse through the tunnel.)
    //  - target already inside the fed run  -> feed only the tail past fedThrough (for REORDER)
    //  - contiguous forward extension        -> continue from fedThrough+1
    //  - backward / gap seek                 -> start a fresh run at the keyframe (IDR resync)
    const continues = this.runReaches(key);
    const start = continues ? this.fedThrough + 1 : key;
    // Bring in only the encoded bytes this run needs (Range blocks).
    try { await this.ensureData(Math.min(start, end), end); } catch (e) {
      console.warn('[frame-source] range fetch failed', this.url, e); return;
    }
    if (this.closed || this.decoder !== dec || !this.configured) return;
    // State may have moved while bytes were in flight (prefetch fed more): re-check.
    let from: number;
    if (this.runReaches(key)) from = this.fedThrough + 1;
    else { from = key; this.fedFrom = key; this.fedThrough = key - 1; }
    if (from < start) { try { await this.ensureData(from, end); } catch { return; } }
    if (this.closed || this.decoder !== dec || !this.configured) return;
    const start2 = from;
    let fedTo = start2 - 1;
    for (let i = start2; i <= end; i++) { if (!this.feed(i)) break; fedTo = i; }
    this.fedThrough = Math.max(this.fedThrough, fedTo);
    // The waiter resolves the instant onFrame() caches the target.
    await Promise.race([this.waitForFrame(target), delay(450)]);
    // STALL RECOVERY: hardware (GPU) decoders sometimes wedge mid-scrub — input drained but the
    // frame never emitted (the headed-Chrome repro). If the target still isn't cached, rebuild the
    // decoder and re-feed once from the keyframe; a fresh decoder reliably emits.
    if (!this.cache.has(target) && !this.closed) {
      this.recover();
      const dec2 = this.decoder;
      if (dec2 && this.configured) {
        this.fedFrom = key;
        for (let i = key; i <= end; i++) this.feed(i);
        this.fedThrough = end;
        await Promise.race([this.waitForFrame(target), delay(900)]);
      }
    }
    this.protectedIndex = target;
  }

  /** Lightweight status for the on-screen diagnostic (why a frame might not be showing). */
  status(): string {
    if (this.failed) return 'FAILED';
    if (!this.samples.length) return 'loading';
    const mb = (this.wholeFile ? this.wholeFile.byteLength : this.blockBytes) / 1048576;
    return `cache=${this.cache.size} q=${this.decoder?.decodeQueueSize ?? '?'} dec=${this.decoder?.state ?? '?'}${this.draining ? ' drain' : ''} shown=${this.lastShownTime >= 0 ? this.lastShownTime.toFixed(2) : '—'} mem=${mb.toFixed(0)}MB`;
  }

  /** Keep decoding forward from the playhead so upcoming frames are ready during playback.
   *  Non-blocking; feeds a window ahead without flushing (frames emit as refs arrive). */
  prefetch(timeSec: number, aheadSec: number): void {
    if (this.failed || !this.decoder || !this.configured) return;
    if (this.draining || this.prefetching) return; // don't fight an in-flight scrub decode for the same decoder
    const target = this.indexAtTime(timeSec + aheadSec);
    if (target < 0) return;
    const from = this.indexAtTime(timeSec);
    const key = this.keyframeFor(from);
    if (this.fedFrom >= 0 && this.fedFrom <= key && this.fedThrough >= target) return; // already fed
    this.prefetching = true;
    const lo = this.runReaches(key) ? this.fedThrough + 1 : key;
    this.ensureData(lo, Math.min(target, lo + 60))
      .then(() => {
        // State may have moved while bytes were in flight: decide the range NOW.
        if (this.closed || this.draining || !this.decoder || !this.configured) return;
        let start: number;
        if (this.runReaches(key) && this.fedThrough < target) {
          start = this.fedThrough + 1; // contiguous forward extension
        } else if (this.runReaches(key) && this.fedThrough >= target) {
          return; // already fed past the window (no duplicate feeds)
        } else {
          start = key; this.fedFrom = key; this.fedThrough = key - 1; // new run at the keyframe (IDR resync)
        }
        // Cap in-flight work so we never queue thousands of chunks at once.
        const end = Math.min(target, start + 60);
        if (end < start) return;
        for (let i = start; i <= end; i++) if (!this.feed(i)) { this.fedThrough = i - 1; return; }
        this.fedThrough = Math.max(this.fedThrough, end);
      })
      .catch((e) => console.warn('[frame-source] prefetch fetch failed', this.url, e))
      .finally(() => { this.prefetching = false; });
  }

  private feed(i: number): boolean {
    const dec = this.decoder;
    const s = this.samples[i];
    if (!dec || !s || dec.state !== 'configured') return false;
    const data = this.sampleData(i);
    if (!data) return false; // bytes not loaded (evicted) — caller stops the run here
    // Always feed in a contiguous run (never skip a cached frame) — the decoder needs every
    // chunk in sequence to produce the frames that follow. onFrame() de-dupes the output.
    try {
      dec.decode(new EncodedVideoChunk({
        type: s.isSync ? 'key' : 'delta',
        timestamp: s.ctsUs,
        duration: Math.round(s.dur * 1e6),
        data,
      }));
    } catch { /* decoder reset under us */ }
    return true;
  }

  close() {
    this.closed = true;
    if (this.decoder) { try { this.decoder.close(); } catch { /* noop */ } this.decoder = null; }
    for (const f of this.cache.values()) f.close();
    this.cache.clear();
    this.lru = [];
    this.frameWaiters.clear();
    this.blocks.clear();
    this.blockBytes = 0;
    this.wholeFile = null;
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
