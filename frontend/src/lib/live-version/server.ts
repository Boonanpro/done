// 成果物タブ（/preview/<slug>、開発サーバー 3001 が描く）の「今のファイルの版」。
//
// 2026-10-18: 本人の画面が、Cloudflare に4時間持たされた古い部品と、後から HMR で
// 届いた新しい部品が混ざった状態で動き、ダンが直したボタンが本人にだけ出なかった。
// 画面が自分の版をサーバーの版と比べられるように、src の中身から版を作って
// current.gen.ts に書く。画面のプログラムはこのファイルを読み込むので、版は部品の中に
// 焼き込まれる（古い部品なら古い版のまま）。比べる処理は ./guard.ts。
//
// 開発サーバーの next.config.ts だけが startLiveVersionWatcher を呼ぶ。本番ビルドと
// Vercel の専用サイトでは版は空（./stub.ts）で、比べる処理も動かない。
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const CODE_EXTS = new Set(['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.css', '.json', '.md', '.mdx']);
export const LIVE_VERSION_GEN = path.join('src', 'lib', 'live-version', 'current.gen.ts');

function genPath(frontendDir: string): string {
  return path.join(frontendDir, LIVE_VERSION_GEN);
}

/** src の下のコード（名前・大きさ・更新時刻）から版を作る。同じ中身なら何度作っても同じ値。 */
export function computeLiveVersion(frontendDir: string): string {
  const srcDir = path.join(frontendDir, 'src');
  const skip = path.resolve(genPath(frontendDir));
  const rows: string[] = [];
  const walk = (dir: string) => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) {
        // _server は成果物の Python。画面の部品にならない。
        if (e.name === 'node_modules' || e.name === '_server' || e.name.startsWith('.')) continue;
        walk(p);
      } else if (CODE_EXTS.has(path.extname(e.name)) && path.resolve(p) !== skip) {
        try {
          const st = fs.statSync(p);
          rows.push(`${path.relative(srcDir, p)}|${st.size}|${Math.floor(st.mtimeMs)}`);
        } catch {
          // 書き換えの途中で消えたファイルは次の計算に任せる
        }
      }
    }
  };
  walk(srcDir);
  rows.sort();
  return createHash('sha1').update(rows.join('\n')).digest('hex').slice(0, 12);
}

/** current.gen.ts に書いてある版。開発サーバー以外（ファイルが無い）では空。 */
export function readLiveVersion(frontendDir: string = process.cwd()): string {
  try {
    const text = fs.readFileSync(genPath(frontendDir), 'utf8');
    return /LIVE_VERSION = '([0-9a-f]*)'/.exec(text)?.[1] || '';
  } catch {
    return '';
  }
}

function writeLiveVersion(frontendDir: string): void {
  const version = computeLiveVersion(frontendDir);
  if (readLiveVersion(frontendDir) === version) return;
  const file = genPath(frontendDir);
  const body =
    '// 開発サーバーが書く（src/lib/live-version/server.ts）。git の対象外。手で直さない。\n' +
    `export const LIVE_VERSION = '${version}';\n`;
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, body);
  fs.renameSync(tmp, file);
}

/** 開発サーバーの起動時に1回呼ぶ。src が変わるたびに版を書き直す。 */
export function startLiveVersionWatcher(frontendDir: string): void {
  const g = globalThis as { __danLiveVersionWatcher?: boolean };
  if (g.__danLiveVersionWatcher) return;
  g.__danLiveVersionWatcher = true;
  // next dev は設定を親と子の2つのプロセスで読む。版は中身だけで決まるので、
  // 2つが同時に書いても同じ値になる。
  writeLiveVersion(frontendDir);
  const gen = path.resolve(genPath(frontendDir));
  let timer: NodeJS.Timeout | null = null;
  try {
    const watcher = fs.watch(path.join(frontendDir, 'src'), { recursive: true }, (_event, name) => {
      if (name && path.resolve(frontendDir, 'src', String(name)).startsWith(gen)) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        try {
          writeLiveVersion(frontendDir);
        } catch (err) {
          console.error('[live-version] write failed', err);
        }
      }, 300);
    });
    watcher.unref();
  } catch (err) {
    console.error('[live-version] watch failed', err);
  }
}

// 成果物の裏側（<slug>/_server、本番の sandbox 8000 が動かす Python）が今のファイルで動いているか。
// sandbox が app/services/artifact_backends.py で .tmp/artifact-backends.json に書く。版の数え方は
// 同じファイルの fingerprint() と同じ（相対パス＋中身の sha1。__pycache__ と .pyc は数えない）。
// 2026-10-18: 画面はすぐ新しくなるのに裏側は本体の再起動待ちのまま、という食い違いを画面に出すため。
export type BackendStatus = { current: boolean; state: string; reason: string };
const BACKEND_STALE_MS = 120_000;
const fpCache = new Map<string, { at: number; value: string }>();

export function backendFingerprint(frontendDir: string, slug: string): string {
  const hit = fpCache.get(slug);
  if (hit && Date.now() - hit.at < 2000) return hit.value;
  const base = path.join(frontendDir, 'src', 'app', 'artifacts', slug, '_server');
  const files: string[] = [];
  const walk = (dir: string) => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name !== '__pycache__') walk(p);
      } else if (!e.name.endsWith('.pyc')) {
        files.push(path.relative(base, p).split(path.sep).join('/'));
      }
    }
  };
  walk(base);
  files.sort();
  const h = createHash('sha1');
  for (const rel of files) {
    let data: Buffer;
    try {
      data = fs.readFileSync(path.join(base, rel));
    } catch {
      continue;
    }
    h.update(Buffer.from(rel, 'utf8'));
    h.update(Buffer.from([0]));
    h.update(data);
    h.update(Buffer.from([0]));
  }
  const value = h.digest('hex').slice(0, 12);
  fpCache.set(slug, { at: Date.now(), value });
  return value;
}

/** 裏側の無い成果物は null。 */
export function readBackendStatus(slug: string, frontendDir: string = process.cwd()): BackendStatus | null {
  if (!/^[\w-]+$/.test(slug)) return null;
  if (!fs.existsSync(path.join(frontendDir, 'src', 'app', 'artifacts', slug, '_server', 'routes.py'))) return null;
  const files = backendFingerprint(frontendDir, slug);
  let data: { heartbeat?: string; sites?: Record<string, { loaded?: string; state?: string; reason?: string }> } | null = null;
  try {
    data = JSON.parse(fs.readFileSync(path.resolve(frontendDir, '..', '.tmp', 'artifact-backends.json'), 'utf8'));
  } catch {
    data = null;
  }
  // 記録が無い・止まっている時は、画面には何も出さない（再起動前の本体や、止まった裏側の時。
  // それはダンの確認 scripts/artifact_seen.py が NG として拾う）。
  if (!data || !data.heartbeat || Date.now() - Date.parse(data.heartbeat) > BACKEND_STALE_MS) return null;
  const row = (data.sites || {})[slug] || {};
  if (row.loaded === files) return { current: true, state: 'current', reason: '' };
  return { current: false, state: row.state || 'reloading', reason: row.reason || '' };
}
