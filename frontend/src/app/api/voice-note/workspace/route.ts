import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { parseEnv } from 'node:util';
import { NextRequest, NextResponse } from 'next/server';
import { KIND, ROOM_ID } from '../../../artifacts/voice-note/model';

export const runtime='nodejs';
const backend=process.env.BACKEND_URL||'http://127.0.0.1:8000';
const fields=['title','transcript','free','paid','price','audio','status','noteUrl','scheduledAt','purchases','gross','received','salesMonth','checkedAt','questions','transcribedAudio','editorialNotes','editorial','images','aiResult','editorLayout','xDraft'];
export async function GET(req:NextRequest) {
 const respond=(body:unknown,status=200)=>NextResponse.json(body,{status,headers:{'Cache-Control':'private, no-store'}});
 const cookie=req.cookies.get('done_access_token')?.value;
 const authorization=cookie?`Bearer ${cookie}`:req.headers.get('authorization');
 if(!authorization?.startsWith('Bearer '))return respond({error:'ログインが必要です。'},401);
 try {
  // Existing backend verifies the token and returns only this owner's workspaces.
  const response=await fetch(`${backend}/api/v1/dan-notion/pages`,{headers:{Authorization:authorization},cache:'no-store',signal:AbortSignal.timeout(15000)});
  if(!response.ok)return respond({error:'編集室の接続を確認できません。'},response.status);
  const pages=await response.json();
  const root=pages.find((r:{properties:Record<string,unknown>})=>r.properties.kind===KIND&&r.properties.room_id===ROOM_ID);
  if(!root)return respond({error:'本人アカウントで編集室を開いてください。'},404);
  const local=await readFile(path.resolve(process.cwd(),'../.env'),'utf8').then(parseEnv).catch(()=>({} as Record<string,string>));
  const db=process.env.SUPABASE_URL||local.SUPABASE_URL;
  const key=process.env.SUPABASE_SERVICE_ROLE_KEY||local.SUPABASE_SERVICE_ROLE_KEY;
  if(!db||!key)return respond({error:'編集室の保存先設定を読み込めません。'},503);
  const url=new URL('/rest/v1/blocks',db);
  url.search=new URLSearchParams({select:'id,updated_at,'+fields.map(k=>`${k}:properties->article->${k}`).join(','),user_id:`eq.${root.user_id}`,parent_id:`eq.${root.id}`,'properties->>kind':'eq.voice_note_article',deleted_at:'is.null',order:'order_key.asc'}).toString();
  const result=await fetch(url,{headers:{apikey:key,Authorization:`Bearer ${key}`},cache:'no-store',signal:AbortSignal.timeout(15000)});
  if(!result.ok)return respond({error:'記事を読み込めませんでした。再試行してください。'},502);
  const records=await result.json();
  const rows=records.map((record:Record<string,unknown>)=>({id:record.id,updated_at:record.updated_at,content:[],properties:{kind:'voice_note_article',history_omitted:true,article:Object.fromEntries(fields.filter(k=>record[k]!=null).map(k=>[k,record[k]]))}}));
  return respond({root,rows});
 }catch{return respond({error:'記事の読み込みに失敗しました。接続を確認して再試行してください。'},502);}
}
