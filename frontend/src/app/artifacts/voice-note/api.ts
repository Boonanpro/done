import { useAuthStore } from '@/stores/auth-store';
import { KIND, ROOM_ID, type Row, type Article, validArticle } from './model';
export async function call<T>(path: string, method='GET', body?: unknown): Promise<T> {
  const token=useAuthStore.getState().token;
  const response=await fetch('/api/v1'+path,{method,credentials:'include',headers:{...(body?{'Content-Type':'application/json'}:{}),...(token?{Authorization:`Bearer ${token}`}:{})},body:body?JSON.stringify(body):undefined});
  if(!response.ok) throw new Error(response.status===401?'ダンへのログインが必要です。':response.status===403?'この記事を開く権限がありません。':`保存先に接続できません（${response.status}）。入力内容を残して再試行してください。`);
  return response.json();
}
export async function findWorkspace(): Promise<Row | undefined> {
  const rows=await call<Row[]>('/dan-notion/pages');
  return rows.find(r=>r.properties.kind===KIND && r.properties.room_id===ROOM_ID);
}
export async function saveArticle(row: Row, article: Article): Promise<Row> {
  const error=validArticle(article); if(error) throw new Error(error);
  const current=await call<Row>('/dan-notion/blocks/'+row.id);
  if(current.updated_at!==row.updated_at) throw new Error('別の画面でこの記事が更新されました。入力内容を控えてから、更新して最新の記事を確認してください。');
  const previous=current.properties.article as Article | undefined;
  if(previous&&previous.title!==article.title&&(previous.free||previous.paid)) article={...article,revisions:[...(previous.revisions||[]),{savedAt:Date.now(),title:previous.title,free:previous.free,paid:previous.paid,price:previous.price,editorialNotes:previous.editorialNotes}]};
  const history={...(current.properties.monthly_history as Record<string, unknown> || {})};
  if(previous?.checkedAt&&previous.salesMonth!==article.salesMonth) history[previous.salesMonth]={purchases:previous.purchases,gross:previous.gross,received:previous.received,checkedAt:previous.checkedAt};
  return call<Row>('/dan-notion/blocks/'+row.id,'PATCH',{properties:{...current.properties,monthly_history:history,title:article.title,article},content:[{type:'text',text:[article.title,article.free,article.paid].filter(Boolean).join('\n\n')}]});
}
export async function uploadAudio(file: File): Promise<{name:string;url:string}> {
  if(file.size>500*1024*1024) throw new Error('音声は500MB以下にしてください。');
  const data=new FormData();data.append('file',file);
  const token=useAuthStore.getState().token;
  const r=await fetch('/api/v1/files/upload',{method:'POST',credentials:'include',headers:token?{Authorization:`Bearer ${token}`}:{},body:data});
  if(!r.ok)throw new Error('音声を保存できませんでした。もう一度お試しください。');
  const value=await r.json();return {name:file.name,url:value.url};
}

export async function startEditorial(id:string,mode?:'title'):Promise<Row> {
 const token=useAuthStore.getState().token;
 const r=await fetch('/api/voice-note/editorial',{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify({id,mode})});
 const data=await r.json();if(!r.ok)throw new Error(data.error||'記事作成を開始できませんでした。');return data.row;
}
