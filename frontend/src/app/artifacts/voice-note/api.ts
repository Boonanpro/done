import { useAuthStore } from '@/stores/auth-store';
import { ROOM_ID, type Row, type Article, validArticle } from './model';
type Workspace={root:Row;rows:Row[]};
function workspaceCacheKey(){const auth=useAuthStore.getState();return auth.token&&auth.user?.id?`voice-note-workspace-v1:${ROOM_ID}:${auth.user.id}`:undefined;}
export function cachedWorkspace():Workspace|undefined {
 try{const key=workspaceCacheKey();if(!key)return;const value=JSON.parse(sessionStorage.getItem(key)||'null');if(value&&Date.now()-value.at<24*60*60_000&&value.data.root.user_id===useAuthStore.getState().user?.id)return value.data;}catch{}
}
export function cacheWorkspace(data:Workspace){try{const key=workspaceCacheKey();if(!key)return;const rows=data.rows.map(row=>{const article={...(row.properties.article as Record<string,unknown>)};delete article.revisions;return {...row,content:[],properties:{...row.properties,article,history_omitted:true}};});sessionStorage.setItem(key,JSON.stringify({at:Date.now(),data:{root:data.root,rows}}));}catch{}}
export function clearWorkspaceCache(){try{const key=workspaceCacheKey();if(key)sessionStorage.removeItem(key);}catch{}}
export async function call<T>(path: string, method='GET', body?: unknown): Promise<T> {
  const token=useAuthStore.getState().token;
  const response=await fetch('/api/v1'+path,{method,credentials:'include',headers:{...(body?{'Content-Type':'application/json'}:{}),...(token?{Authorization:`Bearer ${token}`}:{})},body:body?JSON.stringify(body):undefined});
  if(!response.ok) throw new Error(response.status===401?'ダンへのログインが必要です。':response.status===403?'この記事を開く権限がありません。':`保存先に接続できません（${response.status}）。入力内容を残して再試行してください。`);
  return response.json();
}
let workspaceRequest: {token:string|null; task:Promise<{root:Row;rows:Row[]}>} | undefined;
export async function findWorkspace():Promise<Row|undefined> {return (await loadWorkspace()).root;}
export function loadWorkspace():Promise<{root:Row;rows:Row[]}> {
 const token=useAuthStore.getState().token;
 if(workspaceRequest?.token===token)return workspaceRequest.task;
 const task=(async()=>{
  const response=await fetch('/api/voice-note/workspace',{credentials:'include',cache:'no-store',headers:token?{Authorization:`Bearer ${token}`}:{}});
  const data=await response.json();
  if(useAuthStore.getState().token!==token)throw new Error('ログイン状態が変わりました。編集室を開き直してください。');
  if(!response.ok){if(response.status===401||response.status===403||response.status===404)clearWorkspaceCache();throw new Error(data.error||'編集室を読み込めませんでした。');}
  return data as {root:Row;rows:Row[]};
 })();
 workspaceRequest={token,task};
 void task.finally(()=>{if(workspaceRequest?.task===task)workspaceRequest=undefined;}).catch(()=>{});
 return task;
}
export async function saveArticle(row: Row, article: Article): Promise<Row> {
  const error=validArticle(article); if(error) throw new Error(error);
  const current=await call<Row>('/dan-notion/blocks/'+row.id);
  const version=(value:string)=>value.replace(/\+00:00$/,'Z').replace(/(?:\.(\d+))?Z$/,(_,digits:string|undefined)=>'.'+(digits||'').padEnd(6,'0')+'Z');
  if(version(current.updated_at)!==version(row.updated_at)) throw new Error('別の画面でこの記事が更新されました。入力内容を控えてから、更新して最新の記事を確認してください。');
  const previous=current.properties.article as Article | undefined;
  // A lightweight read omits history; saving must never erase it.
  article={...previous,...article,revisions:previous?.revisions};
  if(previous&&(previous.title!==article.title||previous.free!==article.free||previous.paid!==article.paid)&&(previous.free||previous.paid)) article={...article,revisions:[...(previous.revisions||[]),{savedAt:Date.now(),title:previous.title,free:previous.free,paid:previous.paid,price:previous.price,editorialNotes:previous.editorialNotes}]};
  const history={...(current.properties.monthly_history as Record<string, unknown> || {})};
  if(previous?.checkedAt&&previous.salesMonth!==article.salesMonth) history[previous.salesMonth]={purchases:previous.purchases,gross:previous.gross,received:previous.received,checkedAt:previous.checkedAt};
  return call<Row>('/dan-notion/blocks/'+row.id,'PATCH',{properties:{...current.properties,monthly_history:history,title:article.title,article},content:[{type:'text',text:[article.title,article.free,article.paid].filter(Boolean).join('\n\n')}]});
}
export async function uploadImage(file: File): Promise<string> {
  if(!/^image\/(png|jpeg|gif|webp|avif|bmp)$/i.test(file.type))throw new Error('PNG・JPEG・GIF・WebP・AVIF・BMPの画像を使ってください。');
  if(file.size>20*1024*1024)throw new Error('画像は20MB以下にしてください。');
  const data=new FormData();data.append('file',file);
  const token=useAuthStore.getState().token;
  const response=await fetch('/api/v1/files/upload',{method:'POST',credentials:'include',headers:token?{Authorization:`Bearer ${token}`}:{},body:data});
  if(!response.ok)throw new Error('画像を保存できませんでした。もう一度貼り付けてください。');
  const value=await response.json();
  if(typeof value.url!=='string'||!value.url)throw new Error('画像の保存先を取得できませんでした。');
  return value.url;
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
