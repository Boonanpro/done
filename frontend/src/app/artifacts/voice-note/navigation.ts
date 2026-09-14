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
}
