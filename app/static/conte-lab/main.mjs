import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {initial,edit,poseAt} from './state.mjs';
const $=id=>document.getElementById(id),copy=structuredClone;
let state=initial(),history=[],dialogue=[],time=0,playing=false,busy=false,live=null,style='solid';
try{const saved=JSON.parse(localStorage.getItem('dan-conte-lab-v1'));if(saved?.objects&&saved.camera)state=saved;}catch{}
const scene=new THREE.Scene();scene.background=new THREE.Color('#e7eade');scene.fog=new THREE.Fog('#e7eade',35,65);
const camera=new THREE.PerspectiveCamera(45,1,.05,150),renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
$('stage').appendChild(renderer.domElement);const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=false;
scene.add(new THREE.HemisphereLight(0xffffff,0x7c8972,2.3));const sun=new THREE.DirectionalLight(0xfff9ed,3);sun.position.set(4,10,5);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-15,right:15,top:15,bottom:-15});scene.add(sun);
const ground=new THREE.Mesh(new THREE.PlaneGeometry(70,70),new THREE.MeshStandardMaterial({color:0xe0e4d7,roughness:1}));ground.rotation.x=-Math.PI/2;ground.receiveShadow=true;ground.position.y=-.012;scene.add(ground);scene.add(new THREE.GridHelper(40,40,0xa4afa0,0xc7d0c0));
const models=new Map();
function mesh(parent,geometry,color,pos=[0,0,0]){const m=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,roughness:.9,wireframe:style==='wire'}));m.position.fromArray(pos);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
function box(parent,size,pos,color=0xa7b39d){return mesh(parent,new THREE.BoxGeometry(...size),color,pos);}
function joint(parent,pos){const g=new THREE.Group();g.position.fromArray(pos);parent.add(g);return g;}
function person(g){
 const hips=joint(g,[0,.93,0]);box(hips,[.33,.25,.23],[0,0,0],0x687960);const torso=joint(hips,[0,.1,0]);box(torso,[.47,.48,.25],[0,.24,0],0x839079);mesh(torso,new THREE.SphereGeometry(.16,16,12),0xb1bda5,[0,.68,0]);box(torso,[.1,.045,.04],[0,.69,.15],0x57664f);
 const legs=[],arms=[];for(const side of [-1,1]){const thigh=joint(hips,[side*.115,-.08,0]);box(thigh,[.14,.4,.15],[0,-.2,0],0x66785e);const knee=joint(thigh,[0,-.4,0]);box(knee,[.12,.38,.13],[0,-.19,0],0x829276);box(knee,[.16,.09,.29],[0,-.38,.07],0x46573e);legs.push({thigh,knee});const shoulder=joint(torso,[side*.29,.41,0]);box(shoulder,[.12,.29,.12],[0,-.145,0],0x8e9d81);const elbow=joint(shoulder,[0,-.29,0]);box(elbow,[.1,.27,.11],[0,-.135,0],0xa4b399);mesh(elbow,new THREE.SphereGeometry(.07,10,8),0xb1bda5,[0,-.29,0]);arms.push({shoulder,elbow});}
 return {hips,torso,legs,arms};
}
function build(o){const g=new THREE.Group();let rig=null;if(o.kind==='person')rig=person(g);
 if(o.kind==='car'){
  box(g,[2.1,.6,4],[0,.65,0],0x9da996);box(g,[1.6,.6,1.8],[0,1.2,-.1],0xbac3b2);box(g,[1.48,.43,.05],[0,1.22,.81],0x657669);
  for(const x of [-1.08,1.08])for(const z of [-1.25,1.25]){const w=mesh(g,new THREE.CylinderGeometry(.38,.38,.24,16),0x455444,[x,.39,z]);w.rotation.z=Math.PI/2;}
  for(const side of [-1,1]){const wing=box(g,[1.5,.09,1.1],[side*1.7,.83,.35],0xc3ccbc);wing.rotation.y=-side*.14;}box(g,[1.5,.1,.65],[0,1.05,-1.8],0x7e8f73);
 }else if(o.kind==='table'){box(g,[2.6,.13,1.2],[0,1,0],0x9f957c);for(const x of [-1.1,1.1])for(const z of [-.45,.45])box(g,[.1,1,.1],[x,.5,z],0x71816a);box(g,[.45,.2,.3],[.5,1.17,0],0x73836a);}
 else if(o.kind==='box')box(g,[1,1,1],[0,.5,0],0xa39b82);
 g.userData={id:o.id,rig};scene.add(g);models.set(o.id,g);return g;}
function dispose(g){scene.remove(g);g.traverse(m=>{m.geometry?.dispose();m.material?.dispose();});}
function duration(){return Math.max(12,...state.objects.flatMap(o=>o.actions.map(a=>a.start+a.duration)));}
function save(){localStorage.setItem('dan-conte-lab-v1',JSON.stringify(state));}
function snapshot(){return {...copy(state),playhead:time,visible_poses:Object.fromEntries(state.objects.map(o=>[o.id,poseAt(o,time)]))};}
function audit(data){fetch('/api/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).catch(()=>{});}
function status(s){$('status').textContent=s;}
function send(e){if(live?.dc.readyState==='open')live.dc.send(JSON.stringify({...e,event_id:crypto.randomUUID()}));}
function context(){if(live?.started)send({type:'session.update',session:{delegation:{type:'responses',responses:{instructions:live.instructions+'\nCurrent scene: '+JSON.stringify(snapshot())}}}});}
function sync(){
 for(const [id,g]of models)if(!state.objects.some(o=>o.id===id)){dispose(g);models.delete(id);}
 for(const o of state.objects){let g=models.get(o.id);if(!g)g=build(o);g.scale.setScalar(o.scale);}
 camera.position.fromArray(state.camera.position);camera.fov=state.camera.fov;camera.updateProjectionMatrix();controls.target.fromArray(state.camera.target);controls.update();
 $('objects').replaceChildren();$('tracks').replaceChildren();
 const names={person:'人物',car:'車',table:'作業台',box:'箱'},verbs={walk:'歩く',crouch:'しゃがむ',stand:'立つ',work:'作業',wait:'待つ'};
 for(const o of state.objects){const b=document.createElement('div');b.textContent=names[o.kind]+' / '+o.id;$('objects').append(b);if(o.actions.length){const row=document.createElement('div');row.className='track';row.append(o.id+'　');for(const a of o.actions){const span=document.createElement('span');span.className='action';span.textContent=verbs[a.type]+' '+a.start.toFixed(1)+'–'+(a.start+a.duration).toFixed(1)+'秒';row.append(span);}$('tracks').append(row);}}
 $('scrub').max=duration();save();context();
}
function apply(batch){const start=performance.now();if(batch.operations?.length===1&&batch.operations[0].op==='undo')return undo();const next=edit(state,batch);history.push(copy(state));if(history.length>80)history.shift();state=next;if(batch.operations.some(o=>['sequence','retime'].includes(o.op))){time=0;playing=true;$('play').textContent='停止';}sync();status(batch.summary||'変更しました');const result={ok:true,state:copy(state),apply_ms:performance.now()-start};requestAnimationFrame(()=>audit({type:'scene_painted',summary:batch.summary,revision:state.revision,apply_to_frame_ms:performance.now()-start}));return result;}
function undo(){if(!history.length)return{ok:false,error:'戻せる変更がありません',state};const revision=state.revision+1;state=history.pop();state.revision=revision;time=0;sync();status('一つ前に戻しました');return{ok:true,state:copy(state)};}
$('undo').onclick=undo;$('reset').onclick=()=>{history.push(copy(state));const revision=state.revision+1;state=initial();state.revision=revision;time=0;playing=false;sync();};
function toggle(){playing=!playing;if(time>=duration())time=0;$('play').textContent=playing?'停止':'再生';}$('play').onclick=toggle;
$('scrub').oninput=e=>{time=Number(e.target.value);playing=false;$('play').textContent='再生';};$('scrub').onchange=context;
document.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)){e.preventDefault();toggle();}});
controls.addEventListener('end',()=>{state.camera.position=camera.position.toArray();state.camera.target=controls.target.toArray();state.revision++;save();context();});
$('style').onchange=e=>{style=e.target.value;for(const g of models.values())g.traverse(m=>{if(m.material)m.material.wireframe=style==='wire';});};
new ResizeObserver(()=>{const r=$('stage').getBoundingClientRect();renderer.setSize(r.width,r.height);camera.aspect=r.width/r.height;camera.updateProjectionMatrix();}).observe($('stage'));
let last=performance.now();function frame(now){const dt=Math.min(.1,(now-last)/1000);last=now;if(playing){time=Math.min(duration(),time+dt);if(time>=duration()){playing=false;$('play').textContent='再生';}}
 for(const o of state.objects){const g=models.get(o.id),p=poseAt(o,time);g.position.fromArray(p.position);g.rotation.y=p.rotation;if(g.userData.rig){const r=g.userData.rig;r.hips.position.y=.93-p.crouch*.34;r.hips.position.z=-p.crouch*.12;r.torso.rotation.x=p.crouch*.18;for(let i=0;i<2;i++){const swing=p.walk?Math.sin(p.walk+i*Math.PI)*.65:0;r.legs[i].thigh.rotation.x=-p.crouch*.9+swing;r.legs[i].knee.rotation.x=p.crouch*1.65+Math.max(0,-swing)*.5;r.arms[i].shoulder.rotation.x=p.work?-1+Math.sin(p.work+i)*.18:-swing*.65-p.crouch*.25;r.arms[i].elbow.rotation.x=p.work?-.6:-.1;}}}
 $('scrub').value=time;$('clock').textContent=time.toFixed(1)+' / '+duration().toFixed(0)+'秒';renderer.render(scene,camera);requestAnimationFrame(frame);}
sync();requestAnimationFrame(frame);
async function api(path,body){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let j;try{j=await r.json();}catch{throw Error('接続先から正しい応答がありません');}if(!r.ok)throw Error(j.detail||'接続エラー');return j;}
async function command(text){if(busy)throw Error('前の指示を処理中です');busy=true;$('submit').disabled=true;status('指示を場面に反映しています…');const start=performance.now();try{const result=await api('command',{text,state:snapshot(),history:dialogue});for(const c of result.calls)apply(c);dialogue.push({user:text,result:result.calls.map(x=>x.summary).join(' / ')||result.text});if(!result.calls.length)status(result.text||'変更はありません');audit({type:'text_to_scene',text,elapsed_ms:performance.now()-start});return result;}catch(e){status(e.message);throw e;}finally{busy=false;$('submit').disabled=false;}}
$('command').onsubmit=e=>{e.preventDefault();const text=$('text').value.trim();if(text)command(text).catch(()=>{});};
async function closeVoice(){const s=live;live=null;if(!s)return;s.closing=true;clearTimeout(s.timer);s.stream?.getTracks().forEach(t=>t.stop());if(s.dc?.readyState==='open'){s.dc.send(JSON.stringify({type:'session.close',event_id:crypto.randomUUID()}));setTimeout(()=>s.pc.close(),1500);}else s.pc.close();$('audio').srcObject=null;$('voice').classList.remove('on');$('voice').textContent='LIVE1で話す';status('会話を終了しました');}
async function startVoice(){const s={pc:new RTCPeerConnection(),calls:new Map(),completed:new Set(),instructions:'',started:false};live=s;try{
 status('LIVE1に接続しています…');s.stream=await navigator.mediaDevices.getUserMedia({audio:true});if(live!==s){s.stream.getTracks().forEach(t=>t.stop());return;}s.stream.getTracks().forEach(t=>s.pc.addTrack(t,s.stream));s.dc=s.pc.createDataChannel('oai-events');s.pc.ontrack=e=>{$('audio').srcObject=new MediaStream([e.track]);$('audio').play().catch(()=>status('音声の再生を許可してください'));};
 s.dc.onmessage=async({data})=>{if(live!==s)return;const e=JSON.parse(data);
  if(e.type==='session.started'){s.started=true;clearTimeout(s.timer);context();$('voice').textContent='会話を終了';$('voice').classList.add('on');status('聞いています');}
  if(e.type==='session.input_transcript.delta'||e.type==='session.output_transcript.delta'){audit({type:e.type,event:e});$('speech').textContent=e.transcript||e.delta||'';}
  if(e.type==='session.delegation.created'){s.delegatedAt=performance.now();status('場面を変更しています…');}
  if(e.type==='session.closed'){await closeVoice();return;}
  if(e.type==='error'){window.conteLiveErrors.push(e.error);status(e.error?.message||'音声エラー');audit({type:'live_error',error:e.error});}
  if(e.type==='response.event'){
   const ev=e.event,key=e.delegation_id||'current';
   if(['response.failed','response.incomplete','error'].includes(ev.type)){status(ev.error?.message||ev.response?.error?.message||'変更を完了できませんでした。もう一度指示してください。');s.calls.delete(key);audit({type:'backend_error',event:ev});}
   if(ev.type==='response.output_item.done'&&ev.item?.type==='function_call'){const calls=s.calls.get(key)||[];if(!calls.some(c=>c.call_id===ev.item.call_id))calls.push(ev.item);s.calls.set(key,calls);}
   if(ev.type==='response.completed'){
    const calls=s.calls.get(key)||[];s.calls.delete(key);
    for(const c of calls){if(s.completed.has(c.call_id))continue;s.completed.add(c.call_id);let result;try{if(c.name!=='edit_scene')throw Error('Unknown tool');result=apply(JSON.parse(c.arguments));}catch(err){result={ok:false,error:err.message,state:copy(state)};status(err.message);}send({type:'response.item.create',item:{type:'function_call_output',call_id:c.call_id,output:JSON.stringify(result)}});audit({type:'voice_scene_edit',arguments:c.arguments,result,delegation_to_apply_ms:performance.now()-s.delegatedAt});}
    if(calls.length)send({type:'response.create'});
   }
  }
 };
 s.pc.onconnectionstatechange=()=>{if(live===s&&s.pc.connectionState==='failed'){closeVoice();status('音声接続が切れました。もう一度接続してください。');}};
 s.dc.onclose=()=>{if(live===s&&!s.closing){closeVoice();status('音声接続が終了しました');}};
 await s.pc.setLocalDescription(await s.pc.createOffer());
 if(s.pc.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('接続準備がタイムアウトしました')),10000);s.pc.addEventListener('icegatheringstatechange',()=>{if(s.pc.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});});
 const result=await api('session',{sdp:s.pc.localDescription.sdp,state});if(live!==s)return;s.instructions=result.backend_instructions;await s.pc.setRemoteDescription({type:'answer',sdp:result.transport.sdp});s.timer=setTimeout(()=>{if(!s.started){closeVoice();status('音声接続がタイムアウトしました');}},30000);
 }catch(e){await closeVoice();status(e.message);}}
$('voice').onclick=()=>live?closeVoice():startVoice();window.addEventListener('pagehide',closeVoice);
window.conteLiveErrors=[];window.conteLab={get state(){return copy(state)},apply,command,poseAt,setTime(t){time=t;playing=false},get live(){return !!live?.started}};
