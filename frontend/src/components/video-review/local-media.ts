// 素材の写しを、エディターを開いているパソコン（Windows の Chrome など）の保存場所に取り込む。
//
// 素材は Mac mini にあり、家の外の住所（dan.paina.info）から開くと、1回取りに行くたびに Cloudflare を
// 回って 0.1〜0.2 秒かかる。クリップの切れ目ごとにこの待ちが入ってカクついていた。
// 作品を開いた時に、使っている素材の画面用の写し（映像）と音だけの写しを、ブラウザの保存場所
// （Origin Private File System）へ1回だけ写し、以後の読み込み（Range の読み・<video> の再生）は
// そこから読む。取り込みが終わるまでは今までどおり Mac mini から読む。
//
// - 写す物は Range で読める物だけ（画面用の写し・音だけの写し・短い素材の写し）。書き出しには関係しない。
// - 中身が変わっていないかは、開くたびに先頭1バイトを頼んで、大きさと ETag で確かめる。
// - 同じ素材を複数のタブで同時に写さないよう、素材ごとに Web Locks を取る。
// - 保存場所が足りなければ、最近使っていない写しから消す。

const META_KEY = 'dan-local-media-v1';
const DIR_NAME = 'dan-media';
const CHUNK = 16 * 1024 * 1024;          // 1回に取りに行く大きさ
const MAX_FILE = 6 * 1024 * 1024 * 1024; // これより大きい写しは取り込まない
const MAX_BUDGET = 40 * 1024 * 1024 * 1024;

type Meta = { url: string; size: number; tag: string; used: number };
type MetaMap = Record<string, Meta>;

export type LocalMediaProgress = {
  /** 取り込む物の数・終わった数（前から写してあった物も終わりに数える） */
  total: number;
  done: number;
  bytesTotal: number;
  bytesDone: number;
  /** 写している最中 */
  active: boolean;
  /** 取り込めなかった数（保存場所が足りない・回線が切れた） */
  failed: number;
};

function hashKey(url: string): string {
  // FNV-1a 64bit 相当（32bit を2つ）で住所から写しのファイル名を作る
  let h1 = 0x811c9dc5, h2 = 0x01000193;
  for (let i = 0; i < url.length; i++) {
    const c = url.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x0100019d) >>> 0;
  }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0');
}

function readMeta(): MetaMap {
  try { return JSON.parse(localStorage.getItem(META_KEY) || '{}') || {}; } catch { return {}; }
}
function writeMeta(fn: (m: MetaMap) => void) {
  const m = readMeta();
  fn(m);
  try { localStorage.setItem(META_KEY, JSON.stringify(m)); } catch { /* 入らなければ次回また確かめる */ }
}

/** この画面で取り込みを使うか。Mac mini の上で直接開いている時は回線が速いので使わない。スマホでも使わない。
 *  ?localmedia=1 で強制的に使う（試し）、?localmedia=0 で使わない。 */
export function localMediaEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  const q = new URLSearchParams(window.location.search).get('localmedia');
  if (q === '0') return false;
  if (!navigator.storage?.getDirectory || typeof FileSystemFileHandle === 'undefined'
      || !('createWritable' in FileSystemFileHandle.prototype)) return false;
  if (q === '1') return true;
  // スマホ（アプリ・ブラウザ）では写さない: 1作品で数GBになり、通信量と保存場所を食う
  if (/Android|iPhone|iPad|Mobile/i.test(navigator.userAgent)) return false;
  const h = window.location.hostname;
  return !(h === 'localhost' || h === '127.0.0.1' || h === '[::1]');
}

class LocalMediaStore {
  /** この画面で確かめ終わって使える写し */
  private files = new Map<string, File>();
  private objectUrls = new Map<string, string>();
  private listeners = new Set<(p: LocalMediaProgress) => void>();
  private progress: LocalMediaProgress = { total: 0, done: 0, bytesTotal: 0, bytesDone: 0, active: false, failed: 0 };
  private runId = 0;
  private dir: Promise<FileSystemDirectoryHandle> | null = null;

  private getDir(): Promise<FileSystemDirectoryHandle> {
    if (!this.dir) this.dir = navigator.storage.getDirectory().then((root) => root.getDirectoryHandle(DIR_NAME, { create: true }));
    return this.dir;
  }

  /** 確かめの道具用: 使える写しの数と取り込みの進み */
  status() { return { ready: this.files.size, ...this.progress }; }

  /** 取り込み済みの写し（無ければ null） */
  file(url: string): File | null { return this.files.get(url) || null; }

  /** <video> に渡す住所: 取り込み済みならこのパソコンの写し、まだなら元の住所 */
  playSrc(url: string): string {
    const f = this.files.get(url);
    if (!f) return url;
    let u = this.objectUrls.get(url);
    if (!u) { u = URL.createObjectURL(f); this.objectUrls.set(url, u); }
    return u;
  }

  /** 取り込み済みなら写しから lo..hi（両端を含む）を読む。まだなら null */
  async readRange(url: string, lo: number, hi: number): Promise<{ buf: ArrayBuffer; total: number; partial: boolean } | null> {
    const f = this.files.get(url);
    if (!f) return null;
    try {
      const buf = await f.slice(lo, Math.min(hi + 1, f.size)).arrayBuffer();
      return { buf, total: f.size, partial: true };
    } catch {
      // 写しが消された（保存場所の掃除など）: 以後は元の住所から読む
      this.files.delete(url);
      return null;
    }
  }

  subscribe(fn: (p: LocalMediaProgress) => void): () => void {
    this.listeners.add(fn);
    fn({ ...this.progress });
    return () => { this.listeners.delete(fn); };
  }

  private emit(patch: Partial<LocalMediaProgress>) {
    this.progress = { ...this.progress, ...patch };
    for (const fn of this.listeners) fn({ ...this.progress });
  }

  /** 先頭1バイトを頼み、全体の大きさと中身の印（ETag か更新時刻）を知る */
  private async probe(url: string): Promise<{ size: number; tag: string } | null> {
    const res = await fetch(url, { headers: { Range: 'bytes=0-0' }, cache: 'no-store' });
    if (res.status !== 206) { try { await res.body?.cancel(); } catch { /* noop */ } return null; }
    const m = /\/(\d+)\s*$/.exec(res.headers.get('Content-Range') || '');
    await res.arrayBuffer();
    if (!m) return null;
    return { size: Number(m[1]), tag: res.headers.get('X-Content-Version') || res.headers.get('ETag') || res.headers.get('Last-Modified') || '' };
  }

  private async evictFor(need: number, keep: Set<string>): Promise<boolean> {
    let est: StorageEstimate = {};
    try { est = await navigator.storage.estimate(); } catch { /* noop */ }
    const quota = est.quota || 0;
    const budget = Math.min(MAX_BUDGET, quota * 0.6);
    const meta = readMeta();
    let used = Object.values(meta).reduce((s, x) => s + (x.size || 0), 0);
    if (used + need <= budget) return true;
    const dir = await this.getDir();
    const old = Object.entries(meta).filter(([k]) => !keep.has(k)).sort((a, b) => a[1].used - b[1].used);
    for (const [k, x] of old) {
      if (used + need <= budget) break;
      try { await dir.removeEntry(k); } catch { /* 無ければよい */ }
      writeMeta((m) => { delete m[k]; });
      used -= x.size || 0;
    }
    return used + need <= budget;
  }

  private async download(url: string, key: string, size: number, run: number, onBytes: (n: number) => void): Promise<File | null> {
    const dir = await this.getDir();
    const handle = await dir.getFileHandle(key, { create: true });
    // createWritable は別の一時ファイルに書いて close の時に置き換えるので、途中で止まっても半端な写しは残らない
    const w = await handle.createWritable({ keepExistingData: false });
    try {
      for (let lo = 0; lo < size; lo += CHUNK) {
        if (!this.stillWanted(url, run)) { await w.abort(); return null; }
        const hi = Math.min(size, lo + CHUNK) - 1;
        let buf: ArrayBuffer | null = null;
        for (let attempt = 0; attempt < 3 && !buf; attempt++) {
          try {
            const res = await fetch(url, { headers: { Range: `bytes=${lo}-${hi}` }, cache: 'no-store' });
            if (res.status !== 206) throw new Error(`status ${res.status}`);
            buf = await res.arrayBuffer();
            if (buf.byteLength !== hi - lo + 1) throw new Error('short read');
          } catch (e) {
            buf = null;
            if (attempt === 2) throw e;
            await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
          }
        }
        await w.write(buf!);
        onBytes(buf!.byteLength);
      }
      await w.close();
    } catch (e) {
      try { await w.abort(); } catch { /* noop */ }
      throw e;
    }
    const f = await handle.getFile();
    return f.size === size ? f : null;
  }

  // 取り込む物の一覧（先に要る順）。編集で素材が増減すると ensure が差し替える。
  private wanted: string[] = [];
  private wantedSet = new Set<string>();
  private probed = new Map<string, { size: number; tag: string } | null>();
  private failedUrls = new Set<string>();
  private copied = new Map<string, number>();   // この画面で写した物の大きさ（進みの表示用）
  private working = false;

  private stillWanted(url: string, run: number) { return run === this.runId && this.wantedSet.has(url); }

  private report() {
    const total = this.wanted.length;
    let done = 0, bytesTotal = 0, bytesDone = 0;
    for (const u of this.wanted) {
      const info = this.probed.get(u);
      const isDone = this.files.has(u) || this.failedUrls.has(u) || (this.probed.has(u) && (!info || !info.size || info.size > MAX_FILE));
      if (isDone) done++;
      if (this.copied.has(u)) { bytesTotal += this.copied.get(u)!; if (isDone) bytesDone += this.copied.get(u)!; }
      else if (info && !isDone) bytesTotal += info.size;
    }
    this.emit({ total, done, bytesTotal, bytesDone, failed: this.wanted.filter((u) => this.failedUrls.has(u)).length });
    return { bytesDone };
  }

  /** 作品で使う素材を取り込む（urls は先に要る順）。写している途中の素材が一覧に残っていれば、そのまま続ける。 */
  async ensure(urls: string[]): Promise<void> {
    this.wanted = Array.from(new Set(urls.filter(Boolean)));
    this.wantedSet = new Set(this.wanted);
    this.report();
    if (this.working) return;          // 動いている係が次の1つを選ぶ時に新しい一覧を見る
    const run = this.runId;
    this.working = true;
    this.emit({ active: true });
    try { await navigator.storage.persist?.(); } catch { /* 断られても使える */ }
    try {
      const dir = await this.getDir();
      while (run === this.runId) {
        // 1) まだ大きさを確かめていない物をまとめて確かめる（前に写した物はここで使えるようになる）
        const unprobed = this.wanted.filter((u) => !this.files.has(u) && !this.probed.has(u));
        for (let i = 0; i < unprobed.length && run === this.runId; i += 6) {
          await Promise.all(unprobed.slice(i, i + 6).map(async (url) => {
            const key = hashKey(url);
            let info: { size: number; tag: string } | null = null;
            try { info = await this.probe(url); } catch { /* 回線が切れた */ }
            this.probed.set(url, info);
            if (!info || !info.size) return;
            const m = readMeta()[key];
            if (m && m.size === info.size && m.tag === info.tag) {
              try {
                const f = await (await dir.getFileHandle(key)).getFile();
                if (f.size === info.size) {
                  this.files.set(url, f);
                  writeMeta((mm) => { if (mm[key]) mm[key].used = Date.now(); });
                }
              } catch { /* 写しが消えていた */ }
            }
          }));
          this.report();
        }
        if (run !== this.runId) break;
        // 2) 要る順で、まだの物を1つ写す
        const url = this.wanted.find((u) => {
          if (this.files.has(u) || this.failedUrls.has(u)) return false;
          const info = this.probed.get(u);
          return !!info && info.size > 0 && info.size <= MAX_FILE;
        });
        if (!url) break;
        const info = this.probed.get(url)!;
        const key = hashKey(url);
        try {
          if (!(await this.evictFor(info.size, new Set(this.wanted.map(hashKey))))) { this.failedUrls.add(url); this.report(); continue; }
          const got = async (): Promise<File | null> => {
            // 別のタブが同じ物を写し終えていれば、それを使う
            const m = readMeta()[key];
            if (m && m.size === info.size && m.tag === info.tag) {
              try { const f = await (await dir.getFileHandle(key)).getFile(); if (f.size === info.size) return f; } catch { /* noop */ }
            }
            const base = this.report().bytesDone;
            let mine = 0;
            const f = await this.download(url, key, info.size, run, (n) => { mine += n; this.emit({ bytesDone: base + mine }); });
            if (f) writeMeta((mm) => { mm[key] = { url, size: info.size, tag: info.tag, used: Date.now() }; });
            return f;
          };
          const f = navigator.locks ? await navigator.locks.request(`dan-media:${key}`, got) : await got();
          if (f) { this.files.set(url, f); this.copied.set(url, info.size); }
          else if (this.stillWanted(url, run)) this.failedUrls.add(url);
        } catch (e) {
          this.failedUrls.add(url);
          console.warn('[local-media] copy failed', url, e);
        }
        this.report();
      }
    } finally {
      this.working = false;
      if (run === this.runId) this.emit({ active: false });
      // 止めた直後に別の作品が開かれていたら、その一覧で続ける
      else if (this.wanted.length) void this.ensure(this.wanted);
    }
  }

  /** 取り込みを止める（作品を閉じた） */
  stop() {
    this.runId++;
    this.wanted = [];
    this.wantedSet = new Set();
    this.probed.clear();
    this.failedUrls.clear();
    this.emit({ active: false });
  }
}

let store: LocalMediaStore | null = null;
export function localMedia(): LocalMediaStore {
  if (!store) {
    store = new LocalMediaStore();
    (window as unknown as { __localMedia?: LocalMediaStore }).__localMedia = store;
  }
  return store;
}

/** 取り込みが有効なら写しから、無ければ null（呼び出し側が元の住所から読む） */
export async function readLocalRange(url: string, lo: number, hi: number) {
  if (!store) return null;
  return store.readRange(url, lo, hi);
}

/** <video> に渡す住所 */
export function localPlaySrc(url: string): string {
  return store ? store.playSrc(url) : url;
}
