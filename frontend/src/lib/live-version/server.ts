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
