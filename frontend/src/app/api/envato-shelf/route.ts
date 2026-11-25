import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export async function GET(request: NextRequest) {
  const token = request.cookies.get('done_access_token')?.value;
  const authorization = token ? `Bearer ${token}` : request.headers.get('authorization');
  if (!authorization) return new Response(null, { status: 401 });
  const root = path.join(homedir(), '.dan/workspace/envato-shelf');
  const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  try {
    const me = await fetch(`${backend}/api/v1/chat/me`, { headers: { authorization }, cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!me.ok) return new Response(null, { status: me.status });
    const user = await me.json();
    const owner = (await readFile(path.join(root, 'owner'), 'utf8')).trim();
    if (!owner || user.id !== owner) return new Response(null, { status: 403 });
    return new NextResponse(await readFile(path.join(root, 'gallery.json'), 'utf8'), {
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'private, no-store' },
    });
  } catch {
    return NextResponse.json({ error: '部品の一覧を読み込めませんでした。' }, { status: 503 });
  }
}
