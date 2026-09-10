/* Local proposal playback. No generated video file or paid API is needed. */
window.createProposalPlayer=function(item){
 const host=document.createElement('div');host.className='proposal-player';
 const resources=[];let timer=0,disposed=false;
 const element=(tag,cls)=>{const e=document.createElement(tag);if(cls)e.className=cls;return e;};
 const kind=item.kind;
 if(kind==='composition'){
  const c=item.composition,viewport=element('div','proposal-viewport'),canvas=element('div','proposal-canvas');
  viewport.style.aspectRatio=c.width+'/'+c.height;canvas.style.width=c.width+'px';canvas.style.height=c.height+'px';canvas.style.background=c.background;
  viewport.append(canvas);host.append(viewport);
  const animations=[];const videos=[];
  for(const l of c.layers){
   const e=element(l.type==='image'?'img':l.type==='video'?'video':'div','proposal-layer');
   Object.assign(e.style,{left:l.x+'px',top:l.y+'px',width:l.width+'px',height:l.height+'px',fontSize:l.fontSize+'px',color:l.color,background:l.background,fontFamily:l.fontFamily,fontWeight:l.fontWeight,textAlign:l.textAlign,borderRadius:l.borderRadius+'px',objectFit:l.objectFit});
   if(l.type==='text'){e.textContent=l.text;e.style.justifyContent=l.textAlign==='left'?'flex-start':l.textAlign==='right'?'flex-end':'center';}
   if(l.url)e.src=l.url;
   if(l.type==='video'){e.muted=true;e.playsInline=true;e.preload='metadata';videos.push({e,l});resources.push(e);}
   e.onerror=()=>{e.dataset.failed='true';e.title='素材を読み込めませんでした';};
   canvas.append(e);
   const keys=(l.keyframes.length?l.keyframes:[{offset:0,opacity:1},{offset:1,opacity:1}]).map(k=>({offset:k.offset,opacity:k.opacity??1,transform:`translate(${k.x||0}px,${k.y||0}px) scale(${k.scale??1})`}));
   const a=e.animate(keys,{duration:(l.end-l.start)*1000,fill:'both'});a.pause();animations.push({e,l,a});
  }
  const resize=new ResizeObserver(()=>{const scale=Math.min(viewport.clientWidth/c.width,viewport.clientHeight/c.height);canvas.style.transform=`translate(${(viewport.clientWidth-c.width*scale)/2}px,${(viewport.clientHeight-c.height*scale)/2}px) scale(${scale})`;});resize.observe(viewport);
  const controls=element('div','proposal-controls'),play=element('button'),seek=element('input'),clock=element('span');
  play.textContent='再生';play.type='button';seek.type='range';seek.min=0;seek.max=c.duration;seek.step=.01;seek.value=0;seek.setAttribute('aria-label','試作の再生位置');
  controls.append(play,seek,clock);host.append(controls);
  let t=0,running=!matchMedia('(prefers-reduced-motion: reduce)').matches,last=0;
  function draw(){
   for(const {e,l,a} of animations){e.style.visibility=t>=l.start&&(t<l.end||(t===c.duration&&l.end===c.duration))?'visible':'hidden';a.currentTime=Math.max(0,Math.min(t-l.start,l.end-l.start))*1000;}
   for(const {e,l} of videos){
    const active=t>=l.start&&(t<l.end||(t===c.duration&&l.end===c.duration));const source=l.source_start+Math.max(0,t-l.start);
    if(e.readyState&&Math.abs(e.currentTime-source)>.15)e.currentTime=source;
    if(active&&running)e.play().catch(()=>{});else e.pause();
   }
   seek.value=t;clock.textContent=t.toFixed(1)+' / '+c.duration.toFixed(1)+'秒';play.textContent=running?'停止':'再生';
  }
  function tick(now){if(disposed)return;if(running){t+=last?(now-last)/1000:0;if(t>=c.duration){t=c.duration;running=false;}draw();}last=now;timer=requestAnimationFrame(tick);}
  play.onclick=()=>{if(t>=c.duration)t=0;running=!running;last=0;draw();play.blur();};seek.oninput=()=>{t=Number(seek.value);draw();};
  draw();timer=requestAnimationFrame(tick);
  host.dispose=()=>{disposed=true;cancelAnimationFrame(timer);resize.disconnect();animations.forEach(({a})=>a.cancel());videos.forEach(({e})=>e.pause());};
 }else if(kind==='text'){
  const text=element('div','proposal-text');text.textContent=item.text;host.append(text);
 }else if(kind==='image'){
  const img=element('img');img.src=item.url;img.alt=item.title;host.append(img);
 }else{
  const embed=kind==='video'?referenceEmbed(item):null;
  if(embed){
   const frame=element('iframe');frame.src=embed;frame.title=item.title;frame.allow='fullscreen; encrypted-media';frame.referrerPolicy='strict-origin-when-cross-origin';host.append(frame);
  }else{
   const video=element(kind==='audio'?'audio':'video');video.src=item.url;video.controls=true;video.preload='metadata';video.playsInline=true;resources.push(video);host.append(video);
   video.onloadedmetadata=()=>{video.currentTime=item.start||0;};
   video.ontimeupdate=()=>{if(item.end&&video.currentTime>=item.end){video.pause();video.currentTime=item.start||0;}};
   video.onplay=()=>{if(item.end&&video.currentTime>=item.end)video.currentTime=item.start||0;};
   video.onerror=()=>{const error=element('p');error.textContent='この素材を読み込めませんでした。';host.append(error);};
  }
  if(item.end){const label=element('div','proposal-range');label.textContent=`${item.start}〜${item.end}秒の区間`;host.append(label);}
 }
 const zoom=element('button','proposal-zoom');zoom.textContent='拡大';zoom.type='button';zoom.setAttribute('aria-label','提案を大きく見る');
 let closeExpanded=null;
 zoom.onclick=()=>{
  const placeholder=document.createComment('proposal'),overlay=element('dialog','proposal-overlay'),close=element('button','proposal-close');
  close.textContent='戻る';close.type='button';overlay.setAttribute('aria-label',item.title||'提案');host.before(placeholder);overlay.append(close,host);document.body.append(overlay);
  const restore=()=>{if(!closeExpanded)return;closeExpanded=null;placeholder.replaceWith(host);overlay.close();overlay.remove();zoom.blur();};
  closeExpanded=restore;close.onclick=restore;overlay.oncancel=e=>{e.preventDefault();restore();};overlay.showModal();
 };
 host.append(zoom);
 const cleanup=host.dispose;host.dispose=()=>{closeExpanded?.();cleanup?.();resources.forEach(e=>{e.pause();e.removeAttribute('src');e.load();});host.querySelectorAll('iframe').forEach(e=>e.src='about:blank');};
 return host;
};
