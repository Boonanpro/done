import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { NextRequest } from 'next/server';
import { backendUrl } from '@/lib/backend-url';
const root = process.env.DAN_ENVATO_SHELF || path.join(homedir(), '.dan/workspace/envato-shelf');

export async function checkOwner(request: NextRequest) {
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
