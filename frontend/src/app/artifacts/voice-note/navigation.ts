import { useAuthStore } from '@/stores/auth-store';
function previewKey(){const id=useAuthStore.getState().user?.id;return id?`voice-note-preview-location:${id}`:undefined;}
export function rememberPreviewLocation(){try{const url=new URL(window.location.href),key=previewKey();if(key&&url.searchParams.get('dan_preview')==='1')sessionStorage.setItem(key,JSON.stringify({article:url.searchParams.get('article'),view:url.searchParams.get('view'),x:url.searchParams.get('x'),hash:url.hash}));}catch{}}
export function restorePreviewLocation(){try{const url=new URL(window.location.href),key=previewKey();if(!key||url.searchParams.get('dan_preview')!=='1'||url.searchParams.has('article')||url.searchParams.has('view'))return;const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(!saved)return;for(const k of ['article','view','x'])if(typeof saved[k]==='string')url.searchParams.set(k,saved[k]);if(saved.hash==='#voice-note-x-drafts')url.hash=saved.hash;window.history.replaceState(null,'',url);}catch{}}
export const views = {'つくる':'write','記事一覧':'articles','実績':'results'} as const;
export function readLocation() {
  const url=new URL(window.location.href);
  const tab=Object.entries(views).find(([,v])=>v===url.searchParams.get('view'))?.[0]||'つくる';
  return {id:url.searchParams.get('article')||undefined,tab};
}
export function writeLocation(id:string|undefined,tab:string,replace=false) {
  const url=new URL(window.location.href);
  if(url.searchParams.get('article')!==(id||null)){url.searchParams.delete('x');url.hash='';}
  if(id)url.searchParams.set('article',id);else url.searchParams.delete('article');
  const view=views[tab as keyof typeof views];
  if(view&&view!=='write')url.searchParams.set('view',view);else url.searchParams.delete('view');
  if(url.href===window.location.href)return;
  window.history[replace?'replaceState':'pushState'](null,'',url);
  rememberPreviewLocation();
}
