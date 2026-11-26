import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { NextRequest, NextResponse } from 'next/server';
import { checkOwner } from '@/lib/check-editor-owner';

export const dynamic = 'force-dynamic';
const jobs = path.join(homedir(), '.dan/workspace/ae-typography/jobs');
const uuid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
export async function POST(req: NextRequest) {
  const denied = await checkOwner(req);
  if (denied) return denied;
  const data = await req.json();
  if (!uuid.test(data.room) || !uuid.test(data.content) || typeof data.clip !== 'string'
    || typeof data.asset !== 'string' || !Array.isArray(data.values) || data.values.length < 1
    || data.values.length > 100 || data.values.some((v: unknown) => typeof v !== 'string' || !v.trim() || v.length > 300)) {
    return NextResponse.json({error:'入力した文字を確認してください'}, {status:400});
  }
  const id = randomUUID(), dir = path.join(jobs,id);
  await mkdir(dir,{recursive:true,mode:0o700});
  await writeFile(path.join(dir,'request.json'),JSON.stringify(data),{mode:0o600});
  const worker = spawn(process.env.DAN_PYTHON || path.join(homedir(),'dan-venv/bin/python'),
    [path.resolve(process.cwd(),'../scripts/ae_typography/render.py'),dir],{detached:true,stdio:'ignore'});
  worker.once('error',() => { void writeFile(path.join(dir,'result.json'),JSON.stringify({ok:false,error:'文字の描画を開始できませんでした'})); });
  worker.unref();
  return NextResponse.json({id},{status:202});
}
export async function GET(req: NextRequest) {
  const denied = await checkOwner(req);
  if (denied) return denied;
  const id = req.nextUrl.searchParams.get('id') || '';
  if (!uuid.test(id)) return new Response(null,{status:400});
  const dir = path.join(jobs,id);
  try {
    return NextResponse.json(JSON.parse(await readFile(path.join(dir,'result.json'),'utf8')));
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== 'ENOENT') throw err;
    const {stat} = await import('node:fs/promises');
    const info = await stat(path.join(dir,'request.json')).catch(() => null);
    if (!info) return new Response(null,{status:404});
    if (Date.now()-info.mtimeMs > 35*60_000) return NextResponse.json({ok:false,error:'描画に時間がかかっています。作品を開き直して確認してください'});
    return NextResponse.json({pending:true});
  }
}
