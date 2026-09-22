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
  if(e.data?.type==='dan-scene-ready'){ready=true;complete(true);send();schedule();}
  else if(e.data?.type==='dan-scene-error'){ready=false;running=false;cancelAnimationFrame(timer);complete(false,String(e.data.error||'描画エラー'));host.dataset.failed='true';host.sceneError=String(e.data.error||'描画エラー');}
 }
 window.addEventListener('message',message);
 const observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;last=0;schedule();});observer.observe(host);
 play.onclick=()=>{running=!running;last=0;send();schedule();play.blur();};seek.oninput=()=>{t=Number(seek.value);last=0;send();};
 host.control=async action=>{if(!ready||!['play','pause'].includes(action))return false;running=action==='play';last=0;send();schedule();return true;};
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
  frame.srcdoc=`<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' ${vendor}gsap.min.js; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'">${styles}<style>html,body{width:100%!important;height:100%!important;margin:0!important;overflow:hidden!important}#dan-html-stage{position:absolute;width:${width}px;height:${height}px;transform-origin:0 0}</style><script>
   window.danParams=${parameters};
   const report=e=>parent.postMessage({type:'dan-scene-error',error:String(e?.message||e)},'*');
   addEventListener('error',e=>report(e.error||e.message));addEventListener('unhandledrejection',e=>report(e.reason));
  </script><script src="${vendor}gsap.min.js"></script></head><body><div id="dan-html-stage">${doc.body.innerHTML}</div>
  ${scripts.map(s=>'<script>'+s+'<\/script>').join('')}
  <script>
  document.fonts.ready.then(()=>{
   const timelines=Object.values(window.__timelines||{});
   if(timelines.length!==1||typeof timelines[0]?.seek!=='function')throw Error('単一の再生可能なタイムラインが必要です');
   const timeline=timelines[0];timeline.pause();
   function fit(){const box=document.getElementById('dan-html-stage'),s=Math.min(innerWidth/${width},innerHeight/${height});box.style.transform='scale('+s+')';box.style.left=(innerWidth-${width}*s)/2+'px';box.style.top=(innerHeight-${height}*s)/2+'px';}
   addEventListener('resize',fit);fit();timeline.seek(0);
   addEventListener('message',e=>{if(e.source===parent&&e.data?.type==='dan-scene-frame')try{timeline.seek(Math.max(0,Math.min(${Number(c.duration)},Number(e.data.time)||0)));}catch(err){report(err);}});
   requestAnimationFrame(()=>parent.postMessage({type:'dan-scene-ready'},'*'));
  }).catch(report);
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
