/* A work-scoped view of real story decisions; no fabricated progress. */
window.renderFilmPlan=function(result,owner){
 const key=owner.room_id+'/'+owner.content_id,plan=result.film_plan;
 if(window.danFilmVisuals?.owner!==key)window.danFilmVisuals={owner:key,items:{}};
 Object.assign(window.danFilmVisuals.items,result.visuals||{});
 let root=document.getElementById('film-plan');
 if(!root){
  root=document.createElement('details');root.id='film-plan';root.setAttribute('aria-label','物語と場面');
  root.style.cssText='width:100%;max-width:760px;margin:0 auto 24px;padding:16px;box-sizing:border-box;border:1px solid #ffffff20;border-radius:16px;background:#17191d';
  document.getElementById('references').prepend(root);
 }
 if(root.dataset.owner===key&&root.dataset.revision===String(plan.revision))return;
 root.querySelectorAll('.proposal-player').forEach(p=>p.dispose?.());
 root.replaceChildren();root.dataset.owner=key;root.dataset.revision=String(plan.revision);
 root.hidden=!plan.story&&!plan.scenes.length;
 if(root.hidden)return;
 document.body.classList.add('has-references');
 const heading=document.createElement('summary');heading.textContent='物語と場面 · '+plan.scenes.length+'場面';root.append(heading);
 if(plan.story){const story=document.createElement('p');story.textContent=plan.story;story.style.cssText='white-space:pre-wrap;font-size:14px;line-height:1.7;margin:12px 0';root.append(story);}
 const strip=document.createElement('div');strip.style.cssText='display:flex;gap:8px;overflow:auto;padding:8px 0';
 strip.setAttribute('aria-label','場面の順番');root.append(strip);
 const detail=document.createElement('div');root.append(detail);
 let selected=window.danFilmSelection?.owner===key?window.danFilmSelection.id:null;
 function show(scene){
  selected=scene.id;window.danFilmSelection={owner:key,id:scene.id};
  detail.querySelectorAll('.proposal-player').forEach(p=>p.dispose?.());detail.replaceChildren();
  for(const b of strip.children)b.setAttribute('aria-pressed',String(b.dataset.scene===selected));
  const title=document.createElement('p');title.textContent=scene.title||scene.id;detail.append(title);
  const ids=scene.visual_ids||[];
  for(const id of ids){const item=window.danFilmVisuals.items[id];if(item){
   const button=document.createElement('button');button.type='button';button.textContent=item.title||'この場面の見本を見る';
   button.onclick=()=>{const card=document.querySelector('[data-item-id="'+CSS.escape(id)+'"]');if(card)card.scrollIntoView({block:'center',behavior:'smooth'});else if(!detail.querySelector('.proposal-player'))detail.append(window.createProposalPlayer(item));button.blur();};detail.append(button);
  }}
  if(!ids.length){const p=document.createElement('p');p.textContent=scene.action||'この場面の演出はこれから相談します';p.style.cssText='color:#bec3cc;white-space:pre-wrap;line-height:1.6';detail.append(p);}
 }
 let start=0;
 for(const scene of plan.scenes){
  const button=document.createElement('button');button.type='button';button.dataset.scene=scene.id;
  button.style.cssText='flex:0 0 auto;min-width:100px;max-width:240px;white-space:normal;text-align:left;padding:10px 14px';
  button.textContent=(scene.title||scene.id)+' · '+scene.duration+'秒';
  button.title=start+'秒〜'+(start+scene.duration)+'秒';start+=scene.duration;
  button.onclick=()=>{show(scene);button.blur();};strip.append(button);
 }
 if(plan.scenes.length)show(plan.scenes.find(s=>s.id===selected)||plan.scenes[0]);
};
document.addEventListener('DOMContentLoaded',()=>{
 let ownerKey='',loading=false;
 const timer=setInterval(async()=>{
  if(typeof context==='undefined'||!context?.room_id||!context?.content_id)return;
  const owner={room_id:context.room_id,content_id:context.content_id},key=owner.room_id+'/'+owner.content_id;
  if(ownerKey===key||loading)return;
  const old=document.getElementById('film-plan');if(old){old.querySelectorAll('.proposal-player').forEach(p=>p.dispose?.());old.remove();}
  window.danFilmSelection=null;loading=true;
  try{
   const result=await api('/film-plan',owner);
   if(context?.room_id===owner.room_id&&context?.content_id===owner.content_id){window.renderFilmPlan(result,owner);ownerKey=key;}
  }catch(e){ownerKey=key;}finally{loading=false;}
 },700);
 window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
},{once:true});
