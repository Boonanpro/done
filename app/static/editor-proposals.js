/* Local proposal playback. No generated video file or paid API is needed. */
let vimeoPlayerLibrary;
function loadVimeoPlayer(){
 if(window.Vimeo?.Player)return Promise.resolve(window.Vimeo.Player);
 if(!vimeoPlayerLibrary)vimeoPlayerLibrary=new Promise((resolve,reject)=>{
  const script=document.createElement('script');script.src='/api/v1/editor-assistant/vimeo-player.js';
  script.onload=()=>resolve(window.Vimeo.Player);script.onerror=()=>{script.remove();vimeoPlayerLibrary=null;reject(Error('Vimeo player unavailable'));};document.head.append(script);
 });
 return vimeoPlayerLibrary;
}
window.createProposalPlayer=function(item){
 const host=document.createElement('div');host.className='proposal-player';host.dataset.proposalItemId=item.id;
 const resources=[];let timer=0,disposed=false;
 const element=(tag,cls)=>{const e=document.createElement(tag);if(cls)e.className=cls;return e;};
 const kind=item.kind;
 if(kind==='scene')return window.createScenePreview(item,host);
 if(kind==='composition'){
  const c=item.composition,viewport=element('div','proposal-viewport'),canvas=element('div','proposal-canvas');
  viewport.style.aspectRatio=c.width+'/'+c.height;canvas.style.width=c.width+'px';canvas.style.height=c.height+'px';canvas.style.background=c.background;
  viewport.append(canvas);host.append(viewport);
  const animations=[];const videos=[];
  for(const l of c.layers){
   const e=element(l.type==='image'?'img':l.type==='video'?'video':'div','proposal-layer');
   Object.assign(e.style,{left:l.x+'px',top:l.y+'px',width:l.width+'px',height:l.height+'px',fontSize:l.fontSize+'px',color:l.color,background:l.background,fontFamily:l.fontFamily,fontWeight:l.fontWeight,textAlign:l.textAlign,borderRadius:l.borderRadius+'px',objectFit:l.objectFit});
   if(l.letterSpacing!==undefined)e.style.letterSpacing=l.letterSpacing+'px';
   if(l.lineHeight!==undefined)e.style.lineHeight=String(l.lineHeight);
   if(l.textShadow!==undefined)e.style.textShadow=l.textShadow;
   if(l.fontStyle!==undefined)e.style.fontStyle=l.fontStyle;
   if(l.strokeWidth!==undefined){e.style.webkitTextStroke=l.strokeWidth+'px '+(l.strokeColor||'#000');e.style.paintOrder='stroke fill';}
   if(l.type==='text'){e.textContent=l.text;e.style.justifyContent=l.textAlign==='left'?'flex-start':l.textAlign==='right'?'flex-end':'center';}
   if(l.url)e.src=l.url;
   if(l.type==='video'){e.muted=true;e.playsInline=true;e.preload='metadata';videos.push({e,l});resources.push(e);}
   e.onerror=()=>{e.dataset.failed='true';e.title='素材を読み込めませんでした';};
   canvas.append(e);
   const keys=(l.keyframes.length?l.keyframes:[{offset:0,opacity:1},{offset:1,opacity:1}]).map(k=>({offset:k.offset,opacity:k.opacity??1,transform:`translate(${k.x||0}px,${k.y||0}px) scale(${k.scale??1})`}));
   const a=e.animate(keys,{duration:(l.end-l.start)*1000,fill:'both'});a.pause();animations.push({e,l,a});
  }
  const resize=new ResizeObserver(()=>{const scale=Math.min(viewport.clientWidth/c.width,viewport.clientHeight/c.height);canvas.style.transform=`translate(${(viewport.clientWidth-c.width*scale)/2}px,${(viewport.clientHeight-c.height*scale)/2}px) scale(${scale})`;});resize.observe(viewport);
  const controls=element('div','proposal-controls'),play=element('button'),seek=element('input'),clock=element('span'),repeat=element('button');
  play.textContent='再生';play.type='button';seek.type='range';seek.min=0;seek.max=c.duration;seek.step=.01;seek.value=0;seek.setAttribute('aria-label','試作の再生位置');
  let looping=true;
  repeat.type='button';repeat.textContent='↻';repeat.setAttribute('aria-label','見本を繰り返し再生');repeat.setAttribute('aria-pressed','true');
  repeat.onclick=()=>{looping=!looping;repeat.setAttribute('aria-pressed',String(looping));repeat.blur();};
  controls.append(play,seek,clock,repeat);host.append(controls);
  let visible=false;
  let t=0,running=!matchMedia('(prefers-reduced-motion: reduce)').matches,last=0;
  function draw(){
   for(const {e,l,a} of animations){e.style.visibility=t>=l.start&&(t<l.end||(t===c.duration&&l.end===c.duration))?'visible':'hidden';a.currentTime=Math.max(0,Math.min(t-l.start,l.end-l.start))*1000;}
   for(const {e,l} of videos){
    const active=t>=l.start&&(t<l.end||(t===c.duration&&l.end===c.duration));const source=l.source_start+Math.max(0,t-l.start);
    if(e.readyState&&Math.abs(e.currentTime-source)>.15)e.currentTime=source;
    if(active&&running&&visible)e.play().catch(()=>{});else e.pause();
   }
   seek.value=t;clock.textContent=t.toFixed(1)+' / '+c.duration.toFixed(1)+'秒';play.textContent=running?'停止':'再生';
  }
  function schedule(){cancelAnimationFrame(timer);if(!disposed&&visible&&running)timer=requestAnimationFrame(tick);}
  function tick(now){if(disposed||!visible||!running)return;t+=last?(now-last)/1000:0;if(t>=c.duration){if(looping)t%=c.duration;else{t=c.duration;running=false;}}last=now;draw();schedule();}
  play.onclick=()=>{if(t>=c.duration)t=0;running=!running;last=0;draw();schedule();play.blur();};seek.oninput=()=>{t=Number(seek.value);draw();};
  host.control=async action=>{if(!['play','pause'].includes(action))return false;if(action==='play'&&t>=c.duration)t=0;running=action==='play';last=0;draw();schedule();return true;};
  const visibility=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;last=0;draw();schedule();});visibility.observe(host);
  draw();
  host.dispose=()=>{disposed=true;cancelAnimationFrame(timer);visibility.disconnect();resize.disconnect();animations.forEach(({a})=>a.cancel());videos.forEach(({e})=>e.pause());};
 }else if(kind==='text'){
  const text=element('div','proposal-text');text.textContent=item.text;host.append(text);
 }else if(kind==='link'){
  const link=element('a','proposal-link');link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';
  link.textContent=item.title+' ↗';host.append(link);
  const address=element('p');address.textContent=new URL(item.url).hostname;host.append(address);
  link.onclick=e=>{if(window.ipc){e.preventDefault();nativeCommand('external:'+item.url);}};
 }else if(kind==='model'){
  const model=element('model-viewer');model.setAttribute('camera-controls','');model.setAttribute('touch-action','pan-y');model.setAttribute('alt',item.title);model.setAttribute('loading','lazy');model.src=item.url;host.append(model);
  import('/api/v1/editor-assistant/model-viewer.js').catch(()=>mediaFailure(model,()=>location.reload()));
  model.addEventListener('error',()=>mediaFailure(model,()=>{model.src='';model.src=item.url;}));
 }else if(kind==='image'){
  const img=element('img');const localReference=item.url.startsWith('/api/v1/editor-assistant/reference-library/media/');img.loading=localReference?'eager':'lazy';img.decoding='async';img.fetchPriority=localReference?'high':'auto';img.alt=item.title;img.style.objectFit='contain';
  img.addEventListener('load',()=>{img.decode().catch(()=>{}).then(()=>requestAnimationFrame(()=>requestAnimationFrame(()=>{if(!disposed)window.dispatchEvent(new CustomEvent('dan-reference-visible',{detail:{item_id:item.id,url:item.url,at:performance.now()}}));})));},{once:true});
  img.onerror=()=>mediaFailure(img,()=>{img.src=item.url;});
  img.src=item.url;host.append(img);
 }else{
  const embed=kind==='video'?referenceEmbed(item):null;
  if(embed){
   const frame=element('iframe');frame.src=embed;frame.title=item.title;frame.allow='fullscreen; encrypted-media';frame.referrerPolicy='strict-origin-when-cross-origin';host.append(frame);
   if(new URL(embed).hostname==='player.vimeo.com'){
    let player=null,resetting=false;
    const ready=loadVimeoPlayer().then(async Player=>{
     if(disposed)return null;
     player=new Player(frame);await Promise.race([player.ready(),new Promise((_,reject)=>setTimeout(()=>reject(Error('Vimeo player timed out')),12000))]);
     if(disposed)return null;
     player.on('timeupdate',async ({seconds})=>{
      if(!item.end||seconds<item.end||resetting)return;
      resetting=true;
      try{await player.pause();await player.setCurrentTime(item.start||0);}catch{}finally{resetting=false;}
     });
     return player;
    });
    ready.catch(()=>mediaFailure(frame,()=>{frame.src=embed;}));
    host.control=async action=>{if(!['play','pause'].includes(action))return false;const p=await ready;if(!p||disposed)return false;await Promise.race([p[action](),new Promise((_,reject)=>setTimeout(()=>reject(Error('Vimeo control timed out')),8000))]);return true;};
    host.dispose=()=>{disposed=true;player?.destroy().catch(()=>{});};
   }
  }else{
   const video=element(kind==='audio'?'audio':'video');video.src=item.url;video.controls=true;video.preload=item.url.startsWith('/api/v1/editor-assistant/reference-library/media/')?'auto':'metadata';video.playsInline=true;resources.push(video);host.append(video);
   video.onloadedmetadata=()=>{video.currentTime=item.start||0;};
   video.ontimeupdate=()=>{if(item.end&&video.currentTime>=item.end){video.pause();video.currentTime=item.start||0;}};
   video.onplay=()=>{if(item.end&&video.currentTime>=item.end)video.currentTime=item.start||0;};
   video.onerror=()=>mediaFailure(video,()=>video.load());
   host.control=async action=>{if(action==='play'){await video.play();return true;}if(action==='pause'){video.pause();return video.paused;}return false;};
   if(kind==='video'&&item.library_id&&item.url.startsWith('/api/v1/editor-assistant/reference-library/media/')){
    // Motion references must show their motion without a separate click. Keep
    // offscreen history quiet and respect an explicit pause by the user.
    video.muted=true;video.loop=!item.end;
    let visible=false,autoEnabled=true;
    video.addEventListener('pause',()=>{if(visible)autoEnabled=false;});
    video.addEventListener('play',()=>{autoEnabled=true;});
    const visibility=new IntersectionObserver(entries=>{
      visible=entries[0].isIntersecting;
      if(visible&&autoEnabled)video.play().catch(()=>{});
      else if(!visible)video.pause();
    },{threshold:.2});
    visibility.observe(host);
    host.dispose=()=>visibility.disconnect();
   }
  }
  if(item.end){const label=element('div','proposal-range');label.textContent=`${item.start}〜${item.end}秒の区間`;host.append(label);}
 }
 function mediaFailure(media,retry){
  if(host.querySelector('.media-error'))return;
  const error=element('div','media-error'),label=element('span'),again=element('button'),close=element('button');
  label.textContent='読み込めませんでした';again.textContent='再試行';close.textContent='閉じる';
  again.onclick=()=>{error.remove();retry();};close.onclick=()=>error.remove();error.append(label,again,close);host.append(error);
  media.addEventListener('load',()=>error.remove(),{once:true});media.addEventListener('loadeddata',()=>error.remove(),{once:true});
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
