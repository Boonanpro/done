const $=id=>document.getElementById(id);
let project=null,focus=null,live=null,polling=false,lastChat='',lastScenes='',busyText=false;
const shown=new Map();
window.referenceEmbed=item=>{try{const u=new URL(item.url);if(u.hostname.includes('youtube.com'))return 'https://www.youtube.com/embed/'+u.searchParams.get('v');if(u.hostname==='youtu.be')return 'https://www.youtube.com/embed/'+u.pathname.slice(1);}catch{}return null;};
async function api(path,body){const r=await fetch('/api/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let j;try{j=await r.json();}catch{throw Error('サーバーから正しい応答がありません');}if(!r.ok)throw Error(j.detail||'接続エラー');return j;}
function audit(body){return api('event',body).catch(()=>{});}
function status(text){$('status').textContent=text;}
function send(e){if(live?.dc.readyState==='open')live.dc.send(JSON.stringify({...e,event_id:crypto.randomUUID()}));}
function sharedContext(){if(!project)return {};return {sheet:project.sheet,film_plan:project.film_plan,recipes:project.recipes,look_frames:project.look_frames,selected_scene:focus,displayed:project.displayed,dialogue:project.dialogue.slice(-24),items:Object.fromEntries(Object.entries(project.items).map(([id,i])=>[id,{id,title:i.title,kind:i.kind,asset_id:i.asset_id}]))};}
function syncVoice(){if(live?.started)send({type:'session.update',session:{delegation:{type:'responses',responses:{instructions:live.instructions+'\nCurrent project: '+JSON.stringify(sharedContext())}}}});}
function render(s){project=s;
 const chatKey=JSON.stringify(s.dialogue);if(chatKey!==lastChat){lastChat=chatKey;$('chat').replaceChildren();for(const row of s.dialogue){const b=document.createElement('div');b.className='bubble '+row.role;const who=document.createElement('div');who.className='who';who.textContent=row.role==='user'?'あなた':'ダン';const text=document.createElement('div');text.textContent=row.text;b.append(who,text);$('chat').append(b);}$('chat').scrollTop=$('chat').scrollHeight;}
 const scenes=s.film_plan.scenes,key=JSON.stringify(scenes);if(key!==lastScenes){lastScenes=key;$('scenes').replaceChildren();for(const scene of scenes){const b=document.createElement('button');b.textContent=scene.title+' · '+scene.duration+'秒';b.dataset.id=scene.id;b.setAttribute('aria-pressed',String(focus===scene.id));b.onclick=()=>{focus=scene.id;for(const el of $('scenes').children)el.setAttribute('aria-pressed',String(el.dataset.id===focus));const id=[...scene.visual_ids].reverse().find(i=>shown.has(i));if(id)shown.get(id).card.scrollIntoView({block:'center',behavior:'smooth'});else status('この場面の絵や動きは、まだ提案されていません');syncVoice();b.blur();};$('scenes').append(b);}}
 for(const item of Object.values(s.items)){if(shown.has(item.id))continue;if(!['image','scene','composition','video','audio'].includes(item.kind))continue;
  $('visuals').querySelector('.welcome')?.remove();const card=document.createElement('section');card.className='visual';card.dataset.id=item.id;const heading=document.createElement('h2');heading.textContent=item.title||'';const player=window.createProposalPlayer(item);card.append(player,heading);$('visuals').append(card);shown.set(item.id,{card,player});
  card.onclick=()=>{const scene=scenes.find(x=>x.visual_ids.includes(item.id));if(scene){focus=scene.id;syncVoice();}};
  if(player.ready)player.ready.then(r=>audit({type:'display',id:item.id,ok:!!r.ok}));
  const image=player.querySelector('img');if(image){image.addEventListener('load',()=>audit({type:'display',id:item.id,ok:true}),{once:true});image.addEventListener('error',()=>audit({type:'display',id:item.id,ok:false}),{once:true});}
  card.scrollIntoView({block:'end',behavior:'smooth'});
 }
 const job=s.jobs.findLast(j=>['running','queued'].includes(j.status));
 if(job)status(job.label+' · '+Math.floor(Date.now()/1000-job.started_at)+'秒');
 else if(live?.pending)status('話の内容から提案を考えています');
 else if(s.jobs.length){const j=s.jobs.at(-1);status(j.status==='failed'?j.label:(live?.started?'聞いています':'相談内容を保存しました'));}
 $('sheetFields').replaceChildren();for(const [k,v]of Object.entries(s.sheet)){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;$('sheetFields').append(dt,dd);}
}
async function refresh(){if(polling)return;polling=true;try{render(await api('state'));}catch(e){status(e.message);}finally{polling=false;}}
$('sheetButton').onclick=()=>$('sheet').showModal();$('closeSheet').onclick=()=>$('sheet').close();
$('form').onsubmit=async e=>{e.preventDefault();const text=$('text').value.trim();if(!text||busyText)return;if(live){status('テキストで相談する時は、音声会話を終了してください');return;}busyText=true;$('send').disabled=true;try{const job=await api('message',{text,focus});$('text').value='';await refresh();while(true){await new Promise(r=>setTimeout(r,600));await refresh();const j=project.jobs.find(j=>j.id===job.id);if(j&&['completed','failed'].includes(j.status))break;}}catch(e){status(e.message);}finally{busyText=false;$('send').disabled=false;}};
async function closeVoice(){const s=live;if(!s)return;live=null;s.closing=true;clearTimeout(s.timer);s.stream?.getTracks().forEach(t=>t.stop());if(s.dc?.readyState==='open'){s.dc.send(JSON.stringify({type:'session.close',event_id:crypto.randomUUID()}));setTimeout(()=>s.pc.close(),1000);}else s.pc.close();$('audio').srcObject=null;$('voice').classList.remove('on');$('voiceLabel').textContent='ダンと話す';$('mute').hidden=true;status('音声会話を終了しました');audit({type:'voice_closed'});}
async function startVoice(){if(busyText){status('テキストの処理が終わってから接続してください');return;}const s={pc:new RTCPeerConnection(),calls:new Map(),completed:new Set(),started:false,transcripts:new Map()};live=s;
 try{status('音声につないでいます');s.stream=await navigator.mediaDevices.getUserMedia({audio:true});if(live!==s){s.stream.getTracks().forEach(t=>t.stop());return;}s.stream.getTracks().forEach(t=>s.pc.addTrack(t,s.stream));s.dc=s.pc.createDataChannel('oai-events');
 s.pc.ontrack=e=>{$('audio').srcObject=new MediaStream([e.track]);$('audio').play().catch(()=>status('音声の再生を許可してください'));};
 s.dc.onmessage=async({data})=>{if(live!==s)return;let e;try{e=JSON.parse(data);}catch{return;}
  if(e.type==='session.started'){s.started=true;clearTimeout(s.timer);$('voice').classList.add('on');$('voiceLabel').textContent='会話を終了';$('mute').hidden=false;status('聞いています');syncVoice();}
  if(['session.input_transcript.delta','session.output_transcript.delta'].includes(e.type)&&e.delta){
   const role=e.type.includes('input')?'user':'assistant';let row=s.transcripts.get(role);
   if(!row||e.start_ms-row.end>1600){row={id:crypto.randomUUID(),text:'',end:0};s.transcripts.set(role,row);}
   row.text+=e.delta;row.end=e.end_ms;
   await audit({type:'transcript_update',role,id:row.id,text:row.text});
  }
  if(e.type==='session.delegation.created'){s.pending=true;status('話の内容から提案を考えています');}
  if(e.type==='error'){status(e.error?.message||'音声エラー');audit({type:'live_error',error:e.error});}
  if(e.type==='session.closed'){await closeVoice();return;}
  if(e.type==='response.event'){const ev=e.event,key=e.delegation_id||'current';
   if(ev.type==='response.output_item.done'&&ev.item?.type==='function_call'){const rows=s.calls.get(key)||[];if(!rows.some(c=>c.call_id===ev.item.call_id))rows.push(ev.item);s.calls.set(key,rows);}
   if(['response.failed','response.incomplete'].includes(ev.type)){s.pending=false;status('提案の処理が中断しました。会話から続けられます');audit({type:'backend_failed',event:ev});}
   if(ev.type==='response.completed'){const rows=s.calls.get(key)||[];s.calls.delete(key);if(!rows.length)s.pending=false;for(const c of rows){if(s.completed.has(c.call_id))continue;s.completed.add(c.call_id);let result;try{result=await api('tool',{call_id:c.call_id,name:c.name,arguments:JSON.parse(c.arguments)});await refresh();}catch(err){result={ok:false,error:err.message};}if(live!==s)return;send({type:'response.item.create',item:{type:'function_call_output',call_id:c.call_id,output:JSON.stringify(result)}});}if(rows.length&&live===s){syncVoice();send({type:'response.create'});}}
  }
 };
 s.pc.onconnectionstatechange=()=>{if(live===s&&s.pc.connectionState==='failed'){closeVoice();status('音声接続が切れました。相談内容は保存されています');}};
 s.dc.onclose=()=>{if(live===s&&!s.closing)closeVoice();};
 await s.pc.setLocalDescription(await s.pc.createOffer());if(s.pc.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('接続準備がタイムアウトしました')),10000);s.pc.addEventListener('icegatheringstatechange',()=>{if(s.pc.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});});
 const result=await api('session',{sdp:s.pc.localDescription.sdp});if(live!==s)return;s.instructions=result.instructions;await s.pc.setRemoteDescription({type:'answer',sdp:result.transport.sdp});s.timer=setTimeout(()=>{if(!s.started){closeVoice();status('音声接続がタイムアウトしました');}},30000);
 }catch(e){await closeVoice();status(e.message);}
}
$('voice').onclick=()=>live?closeVoice():startVoice();$('mute').onclick=()=>{if(!live)return;const tracks=live.stream.getAudioTracks(),enabled=!tracks[0].enabled;tracks.forEach(t=>t.enabled=enabled);$('mute').textContent=enabled?'マイクをオフ':'マイクをオン';status(enabled?'聞いています':'入力をミュート中（音声接続は継続）');};
addEventListener('pagehide',closeVoice);setInterval(refresh,1000);refresh();
window.filmStudio={get project(){return project;},get live(){return live;},refresh};
