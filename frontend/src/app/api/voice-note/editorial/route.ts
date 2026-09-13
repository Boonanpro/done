import { spawn } from 'node:child_process';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
const locks = new Set<string>();
export async function POST(req: NextRequest) {
  const origin = req.headers.get('origin');
  // The public tunnel forwards to localhost, so Host may be the internal server.
  const publicOrigin = process.env.DAN_PUBLIC_ORIGIN || 'https://dan.paina.info';
  if (origin && origin !== publicOrigin && new URL(origin).host !== req.headers.get('host')) return NextResponse.json({error:'この画面からは実行できません。'}, {status:403});
  const cookie = req.cookies.get('done_access_token')?.value;
  const authorization = cookie ? `Bearer ${cookie}` : req.headers.get('authorization');
  if (!authorization?.startsWith('Bearer ')) return NextResponse.json({error:'ログインが必要です。'}, {status:401});
  let id: string;
  try { ({id} = await req.json()); } catch { return NextResponse.json({error:'記事を選んでください。'}, {status:400}); }
  if (typeof id !== 'string' || !/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({error:'記事を選んでください。'}, {status:400});
  const url = `${backend}/api/v1/dan-notion/blocks/${id}`;
  const headers = {Authorization:authorization, 'Content-Type':'application/json'};
  const response = await fetch(url, {headers, cache:'no-store'});
  if (!response.ok) return NextResponse.json({error:'この記事を開けません。'}, {status:response.status});
  let row = await response.json();
  if (row.properties?.kind !== 'voice_note_article') return NextResponse.json({error:'対象の記事ではありません。'}, {status:400});
  if (locks.has(id)) return NextResponse.json({error:'この記事は作成中です。'}, {status:409});
  locks.add(id);
  try {
    const latest = await fetch(url, {headers, cache:'no-store'});
    if (!latest.ok) return NextResponse.json({error:'この記事を開けません。'}, {status:latest.status});
    row = await latest.json();
    const article = row.properties.article;
    if (article.editorial?.state === 'running' && Date.now()-article.editorial.updatedAt < 15*60_000) return NextResponse.json({row}, {status:202});
    if (!article.transcript?.trim() && !article.audio?.length) return NextResponse.json({error:'音声か話した内容を追加してください。'}, {status:400});
    const jobId = randomUUID();
    const editorial = {id:jobId, state:'running', message:'記事作成を開始しています。', updatedAt:Date.now()};
    const saved = await fetch(url, {method:'PATCH', headers, body:JSON.stringify({properties:{...row.properties,article:{...article,editorial}}})});
    if (!saved.ok) return NextResponse.json({error:'処理状況を保存できませんでした。'}, {status:502});
    const updated = await saved.json();
    const child = spawn(process.env.DAN_PYTHON || 'python', [path.join(process.cwd(),'src/app/artifacts/voice-note/editorial-worker.py')], {windowsHide:true, stdio:['pipe','ignore','ignore'], env:{...process.env,PYTHONIOENCODING:'utf-8'}});
    child.stdin.on('error', ()=>{});
    const reportExit = async()=>{
      try {
        const r = await fetch(url,{headers,cache:'no-store'});
        if (!r.ok) return;
        const current = await r.json();
        const a = current.properties.article;
        if (a.editorial?.id !== jobId || a.editorial.state !== 'running') return;
        await fetch(url,{method:'PATCH',headers,body:JSON.stringify({properties:{...current.properties,article:{...a,editorial:{...a.editorial,state:'error',message:'記事作成が中断しました。保存済みの素材から再試行できます。',updatedAt:Date.now()}}}})});
      } catch { /* Persisted running state expires, permitting recovery after a server outage. */ }
    };
    child.on('error', ()=>{void reportExit();});
    child.on('close', ()=>{void reportExit();});
    child.stdin.end(JSON.stringify({id,jobId,authorization,backend}));
    child.unref();
    return NextResponse.json({row:updated}, {status:202});
  } finally { locks.delete(id); }
}
