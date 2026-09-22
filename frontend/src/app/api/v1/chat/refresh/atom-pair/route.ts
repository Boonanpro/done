import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

// The refresh cookie is scoped to /api/v1/chat/refresh, so pairing lives below
// that path. Pair only from the local Dan UI; device secrets stay on the PC.
export async function POST(request: NextRequest) {
  const origin = request.headers.get('origin');
  const host = request.headers.get('host');
  if (!origin || !host || !['localhost:3000', 'localhost:3002', '127.0.0.1:3000', '127.0.0.1:3002'].includes(host)
      || origin !== `http://${host}`) {
    return NextResponse.json({ error: 'このPCのlocalhostで接続画面を開いてください。' }, { status: 403 });
  }
  try {
    const core = process.env.CORE_BACKEND_URL || 'http://127.0.0.1:9000';
    const refreshed = await fetch(`${core}/api/v1/chat/refresh`, {
      method: 'POST', headers: { cookie: request.headers.get('cookie') || '' },
      cache: 'no-store', signal: AbortSignal.timeout(15000),
    });
    if (!refreshed.ok) return NextResponse.json({
      error: refreshed.status === 401 ? 'ログインの有効期限が切れています。ダンにログインしてから再接続してください。' : 'ダンの認証サーバーに接続できません。少し待って再試行してください。',
    }, { status: refreshed.status === 401 ? 401 : 503 });
    const credentials = await refreshed.json();
    const pairing = JSON.parse(await readFile(path.resolve(process.cwd(), '../.tmp/atom-wifi-pairing.json'), 'utf8'));
    const stop = request.nextUrl.searchParams.get('action') === 'stop';
    const paired = await fetch(`http://127.0.0.1:48802/${stop ? 'command' : 'pair'}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(stop ? { key: pairing.key, action: 'stop' } : { key: pairing.key, token: credentials.access_token, refresh_token: credentials.refresh_token }),
      signal: AbortSignal.timeout(20000),
    });
    const result = NextResponse.json(paired.ok ? { ok: true } : { error: '音声サービスへの登録に失敗しました。' }, { status: paired.ok ? 200 : 503 });
    for (const cookie of refreshed.headers.getSetCookie()) result.headers.append('Set-Cookie', cookie);
    return result;
  } catch {
    return NextResponse.json({ error: '音声サービスに接続できません。PC側の起動状態を確認してください。' }, { status: 503 });
  }
}
