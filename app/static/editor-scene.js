/* Untrusted preview code runs in an opaque origin, without Dan credentials. */
window.createScenePreview=function(item,host){
 const c=item.scene,frame=document.createElement('iframe');
 frame.title=item.title;frame.setAttribute('sandbox','allow-scripts');
 frame.style.cssText=`width:min(100%,calc(max(160px,100vh - 460px) * ${c.width/c.height}));aspect-ratio:${c.width}/${c.height};margin-inline:auto;border:0;display:block`;
 const controls=document.createElement('div');controls.className='proposal-controls';
 const play=document.createElement('button'),seek=document.createElement('input'),clock=document.createElement('span');
 play.type='button';play.style.minWidth='4em';seek.type='range';seek.min=0;seek.max=c.duration;seek.step=.01;seek.value=0;seek.setAttribute('aria-label','見本の再生位置');
 controls.append(play,seek,clock);host.append(frame,controls);
 let settled=false,ready=false,disposed=false,visible=false,running=!matchMedia('(prefers-reduced-motion: reduce)').matches,t=0,timer=0,last=0;
 let finish;host.ready=new Promise(resolve=>finish=resolve);
 const timeout=setTimeout(()=>complete(false,'見本の描画を確認できませんでした'),12000);
 function complete(ok,error){if(settled)return;settled=true;clearTimeout(timeout);finish({ok,error});if(!ok){host.dataset.failed='true';play.textContent='表示失敗';play.disabled=true;}}
 function send(){if(ready)frame.contentWindow.postMessage({type:'dan-scene-frame',time:t},'*');seek.value=t;clock.textContent=t.toFixed(1)+' / '+c.duration+'秒';play.textContent=running?'停止':'再生';}
 function schedule(){cancelAnimationFrame(timer);if(!disposed&&ready&&visible&&running)timer=requestAnimationFrame(tick);}
 function tick(now){t=(t+(last?(now-last)/1000:0))%c.duration;last=now;send();schedule();}
 function message(e){
  if(e.source!==frame.contentWindow)return;
  if(e.data?.type==='dan-scene-ready'){ready=true;host.items=Array.isArray(e.data.items)?e.data.items:[];complete(true);send();schedule();host.onitems?.(host.items);}
  else if(e.data?.type==='dan-scene-seeked'){host.seekedTime=Number(e.data.time);host.onseeked?.(host.seekedTime);}
  else if(e.data?.type==='dan-scene-error'){ready=false;running=false;cancelAnimationFrame(timer);complete(false,String(e.data.error||'描画エラー'));host.dataset.failed='true';host.sceneError=String(e.data.error||'描画エラー');}
 }
 window.addEventListener('message',message);
 const observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;last=0;schedule();});observer.observe(host);
 play.onclick=()=>{running=!running;last=0;send();schedule();play.blur();};seek.oninput=()=>{t=Number(seek.value);last=0;send();};
 host.control=async action=>{if(!ready||!['play','pause'].includes(action))return false;running=action==='play';last=0;send();schedule();return true;};
 host.setTime=value=>{t=Math.max(0,Math.min(c.duration,Number(value)||0));if(ready)frame.contentWindow.postMessage({type:'dan-scene-frame',time:t},'*');};
 host.seek=value=>{running=false;cancelAnimationFrame(timer);t=Math.max(0,Math.min(c.duration,Number(value)||0));last=0;send();};
 host.dispose=()=>{disposed=true;cancelAnimationFrame(timer);clearTimeout(timeout);observer.disconnect();window.removeEventListener('message',message);if(!settled)complete(false,'closed');frame.srcdoc='';};
 // Own CSP restricts even generated fetch/import code to these public modules.
 const vendor=location.origin+'/api/v1/editor-assistant/scene-vendor/';
 const code=(c.code||'').replace(/<\/script/gi,'<\\/script');
 const parameters=JSON.stringify(c.params||{}).replace(/</g,'\\u003c');
 if(c.html){
  // Parse inertly; untrusted source never executes in the editor's origin.
  const doc=new DOMParser().parseFromString(c.html,'text/html');
  const scripts=[...doc.querySelectorAll('script')].filter(s=>!s.src&&(!s.type||s.type==='text/javascript')).map(s=>s.textContent.replace(/<\/script/gi,'<\\/script'));
  const styles=[...doc.querySelectorAll('style')].map(s=>s.outerHTML).join('');
  doc.querySelectorAll('script,style,link,meta,base,iframe,object,embed').forEach(e=>e.remove());
  const width=Number(c.width),height=Number(c.height);
  // Registered fonts (bundled + the owner's own, e.g. a client's Mincho): served with CORS from the
  // vendor route so the opaque-origin frame can load them; declared lazily (a face loads only if used).
  const faces=(window.DAN_SCENE_FONTS||[]).map(f=>`@font-face{font-family:'${f.family}';src:url('${vendor}fonts/${encodeURIComponent(f.file)}');font-display:block;${f.weight?'font-weight:'+f.weight+';':''}}`).join('');
  frame.style.colorScheme='light'; // with the document's own 'normal' this keeps the frame transparent on dark pages too
  frame.srcdoc=`<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' ${vendor}gsap.min.js; style-src 'unsafe-inline'; font-src data: ${vendor}fonts/; img-src data: blob: ${vendor}; connect-src 'none'; base-uri 'none'; form-action 'none'"><style>${faces}</style>${styles}<style>:root{color-scheme:normal}html,body{width:100%!important;height:100%!important;margin:0!important;overflow:hidden!important;background:transparent}#dan-html-stage{position:absolute;width:${width}px;height:${height}px;transform-origin:0 0}</style><script>
   window.danParams=${parameters};
   const report=e=>parent.postMessage({type:'dan-scene-error',error:String(e?.message||e)},'*');
   addEventListener('error',e=>report(e.error||e.message));addEventListener('unhandledrejection',e=>report(e.reason));
  </script><script src="${vendor}gsap.min.js"></script></head><body><div id="dan-html-stage">${doc.body.innerHTML}</div>
  <script>
  // Edits the owner made on the timeline (text / colour / font / size / position), applied BEFORE
  // the scene's own code runs, so per-character animation splits the edited text.
  (function(){const E=(window.danParams&&window.danParams.edits)||{};
   for(const el of document.querySelectorAll('[data-edit]')){const o=E[el.dataset.edit];if(!o)continue;
    if(o.text!=null)el.textContent=String(o.text);
    if(o.color){el.style.color=o.color;el.style.webkitTextFillColor=o.color;el.style.backgroundImage='none';}
    if(o.font)el.style.fontFamily="'"+o.font+"'";
    if(o.scale&&o.scale!==1)el.style.fontSize=(parseFloat(getComputedStyle(el).fontSize)*o.scale)+'px';
    if(o.dx||o.dy)el.style.translate=((o.dx||0)*${width})+'px '+((o.dy||0)*${height})+'px';}})();
  </script>
  ${scripts.map(s=>'<script>'+s+'<\/script>').join('')}
  <script>
  (async()=>{
   const fams=new Set();for(const el of document.querySelectorAll('#dan-html-stage *')){const f=getComputedStyle(el).fontFamily.split(',')[0].trim();if(f)fams.add(f);}
   await Promise.all([...fams].map(f=>document.fonts.load('48px '+f).catch(()=>null)));await document.fonts.ready;
   const timelines=Object.values(window.__timelines||{});
   if(timelines.length!==1||typeof timelines[0]?.seek!=='function')throw Error('単一の再生可能なタイムラインが必要です');
   const timeline=timelines[0];timeline.pause();
   const E=(window.danParams&&window.danParams.edits)||{};
   const tweens=timeline.getChildren(true,true,false);
   const at=tw=>{let s=tw.startTime(),p=tw.parent;while(p&&p!==timeline){s+=p.startTime();p=p.parent;}return s;};
   const hits=(tw,el)=>{try{return tw.targets().some(x=>x&&x.nodeType===1&&(x===el||el.contains(x)));}catch{return false;}};
   for(const el of document.querySelectorAll('[data-edit]')){const sh=Number(E[el.dataset.edit]?.shift)||0;if(sh)for(const tw of tweens)if(hits(tw,el))tw.startTime(tw.startTime()+sh);}
   const items=[...document.querySelectorAll('[data-edit]')].map(el=>{let s=Infinity,e=-Infinity;for(const tw of tweens)if(hits(tw,el)){const a=at(tw);s=Math.min(s,a);e=Math.max(e,a+tw.totalDuration());}
    const cs=getComputedStyle(el);return {key:el.dataset.edit,label:el.dataset.label||'',text:el.textContent,start:Number.isFinite(s)?s:0,end:Number.isFinite(e)?Math.max(e,s):${Number(c.duration)},font:cs.fontFamily.split(',')[0].replace(/['"]/g,'').trim(),color:cs.color,size:parseFloat(cs.fontSize)};});
   function fit(){const box=document.getElementById('dan-html-stage'),s=Math.min(innerWidth/${width},innerHeight/${height});box.style.transform='scale('+s+')';box.style.left=(innerWidth-${width}*s)/2+'px';box.style.top=(innerHeight-${height}*s)/2+'px';}
   addEventListener('resize',fit);fit();timeline.seek(0);
   addEventListener('message',e=>{if(e.source===parent&&e.data?.type==='dan-scene-frame')try{const t=Math.max(0,Math.min(${Number(c.duration)},Number(e.data.time)||0));timeline.seek(t,false);requestAnimationFrame(()=>parent.postMessage({type:'dan-scene-seeked',time:Number(e.data.time)||0},'*'));}catch(err){report(err);}});
   requestAnimationFrame(()=>parent.postMessage({type:'dan-scene-ready',items},'*'));
  })().catch(report);
  </script></body></html>`;
  send();return host;
 }
 frame.srcdoc=`<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' ${vendor}; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'"><style>html,body,#stage{width:100%;height:100%;margin:0;overflow:hidden;background:#15171b}canvas{display:block}</style></head><body><div id="stage"></div><script>
 const report=e=>parent.postMessage({type:'dan-scene-error',error:String(e?.message||e)},'*');
 addEventListener('error',e=>report(e.error||e.message));addEventListener('unhandledrejection',e=>report(e.reason));
 </script><script type="module">
 import * as THREE from '${vendor}three.module.min.js';
 const stage=document.getElementById('stage'),params=${parameters};let renderFrame=null,current=0;
 const setFrame=fn=>{if(typeof fn!=='function')throw Error('setFrame expects a function');renderFrame=fn;fn(0);requestAnimationFrame(()=>parent.postMessage({type:'dan-scene-ready'},'*'));};
 addEventListener('message',e=>{if(e.source===parent&&e.data?.type==='dan-scene-frame'&&renderFrame){current=Number(e.data.time)||0;try{renderFrame(current);}catch(err){report(err);}}});
 new ResizeObserver(()=>{if(renderFrame)try{renderFrame(current);}catch(err){report(err);}}).observe(stage);
 try{${code}\n}catch(err){report(err);}
 </script></body></html>`;
 send();return host;
};
