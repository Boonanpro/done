import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { backendUrl } from '@/lib/backend-url';
import { NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
const root = process.env.DAN_ENVATO_SHELF || path.join(homedir(), '.dan/workspace/envato-shelf');
const removed = path.join(root, 'removed');

async function checkOwner(request: NextRequest) {
  const token = request.cookies.get('done_access_token')?.value;
  const authorization = token ? `Bearer ${token}` : request.headers.get('authorization');
  if (!authorization) return new Response(null, { status: 401 });
  const me = await fetch(`${backendUrl('core')}/api/v1/chat/me`, {
    headers: { authorization }, cache: 'no-store', signal: AbortSignal.timeout(10000),
  });
  if (!me.ok) return new Response(null, { status: me.status });
  const user = await me.json();
  const owner = (await readFile(path.join(root, 'owner'), 'utf8')).trim();
  if (!owner || user.id !== owner) return new Response(null, { status: 403 });
}

export async function GET(request: NextRequest) {
  try {
    const denied = await checkOwner(request);
    if (denied) return denied;
    const ids = await readdir(removed).catch((err: NodeJS.ErrnoException) => {
      if (err.code === 'ENOENT') return [];
      throw err;
    });
    const hidden = new Set(ids);
    const items: {id: string}[] = JSON.parse(await readFile(path.join(root, 'gallery.json'), 'utf8'));
    return NextResponse.json(items.filter(item => !hidden.has(item.id)), {
      headers: { 'Cache-Control': 'private, no-store' },
    });
  } catch {
    return NextResponse.json({ error: '一覧を読み込めませんでした。' }, { status: 503 });
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const denied = await checkOwner(request);
    if (denied) return denied;
    const id = request.nextUrl.searchParams.get('id');
    if (!id || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id)) return new Response(null, { status: 400 });
    const items: {id: string}[] = JSON.parse(await readFile(path.join(root, 'catalog.json'), 'utf8'));
    if (!items.some(item => item.id === id)) return new Response(null, { status: 404 });
    // Independent markers avoid lost deletes from two open editors and survive catalog updates.
    await mkdir(removed, { recursive: true, mode: 0o700 });
    await writeFile(path.join(removed, id), '', { mode: 0o600 });
    return new Response(null, { status: 204 });
  } catch {
    return NextResponse.json({ error: '棚から削除できませんでした。' }, { status: 503 });
  }
}
