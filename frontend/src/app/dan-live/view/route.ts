// 成果物タブの画面が「自分は今どの版で動いているか」を知らせる先（lib/live-version/guard.ts）。
// 誰の画面かはログインの cookie からダンコアに聞く。記録は .tmp/live-views.json に
// 画面（タブ）ごとに最新の1行だけ残し、ダンは scripts/artifact_seen.py で読む。
// ダンが成果物を直した後、「本人の画面が新しい版に替わったか」をここで確かめる。
import fs from 'node:fs';
import path from 'node:path';

import { readLiveVersion } from '@/lib/live-version/server';

export const dynamic = 'force-dynamic';

const CORE = (process.env.CORE_BACKEND_URL || 'http://127.0.0.1:9000').replace(/\/+$/, '');
const STORE = path.resolve(process.cwd(), '..', '.tmp', 'live-views.json');
const KEEP_MS = 24 * 3600_000;
const MAX_ROWS = 300;
const userCache = new Map<string, { id: string; email: string; at: number }>();
let writing: Promise<void> = Promise.resolve();

async function whoIs(token: string): Promise<{ id: string; email: string } | null> {
  const hit = userCache.get(token);
  if (hit && Date.now() - hit.at < 10 * 60_000) return hit;
  try {
    const res = await fetch(`${CORE}/api/v1/chat/me`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(3000),
      cache: 'no-store',
    });
    if (!res.ok) return null;
    const me = (await res.json()) as { id?: string; email?: string };
    if (!me.id) return null;
    const row = { id: me.id, email: me.email || '', at: Date.now() };
    userCache.set(token, row);
    return row;
  } catch {
    return null;
  }
}

function clip(value: unknown, n: number): string {
  return typeof value === 'string' ? value.slice(0, n) : '';
}

export async function POST(request: Request) {
  const token = request.headers.get('cookie')?.match(/(?:^|;\s*)done_access_token=([^;]+)/)?.[1];
  if (!token) return new Response(null, { status: 204 });
  let body: Record<string, unknown>;
  try {
    const text = await request.text();
    if (text.length > 4000) return new Response(null, { status: 413 });
    body = JSON.parse(text);
  } catch {
    return new Response(null, { status: 400 });
  }
  const user = await whoIs(decodeURIComponent(token));
  if (!user) return new Response(null, { status: 204 });
  const tab = clip(body.tab, 16);
  if (!tab) return new Response(null, { status: 400 });
  const row = {
    user_id: user.id,
    email: user.email,
    tab,
    slug: clip(body.slug, 80),
    path: clip(body.path, 300),
    frame: clip(body.frame, 8),
    loaded: typeof body.loaded === 'string' ? clip(body.loaded, 20) : null,
    client_server: clip(body.server, 20),
    server_now: readLiveVersion(),
    state: clip(body.state, 16),
    reason: clip(body.reason, 16),
    visible: body.visible === true,
    reloads: typeof body.reloads === 'number' ? body.reloads : 0,
    ua: clip(request.headers.get('user-agent'), 200),
    seen_at: new Date().toISOString(),
  };
  writing = writing.then(() => {
    let rows: Record<string, typeof row> = {};
    try {
      rows = JSON.parse(fs.readFileSync(STORE, 'utf8')).tabs || {};
    } catch {
      rows = {};
    }
    rows[`${row.user_id}:${row.tab}`] = row;
    const now = Date.now();
    const kept = Object.entries(rows)
      .filter(([, r]) => now - Date.parse(r.seen_at) < KEEP_MS)
      .sort((a, b) => Date.parse(b[1].seen_at) - Date.parse(a[1].seen_at))
      .slice(0, MAX_ROWS);
    fs.mkdirSync(path.dirname(STORE), { recursive: true });
    const tmp = `${STORE}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ tabs: Object.fromEntries(kept) }, null, 1));
    fs.renameSync(tmp, STORE);
  }).catch((err) => {
    console.error('[live-view] write failed', err);
  });
  await writing;
  return new Response(null, { status: 204 });
}
