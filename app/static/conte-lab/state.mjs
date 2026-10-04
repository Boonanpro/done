export const initial=()=>({revision:0,objects:[
 {id:'man',kind:'person',position:[-3,0,1.5],rotation:Math.PI/2,scale:1,actions:[]},
 {id:'car',kind:'car',position:[1,0,0],rotation:0,scale:1,actions:[]},
 {id:'table',kind:'table',position:[-3,0,-2.5],rotation:0,scale:1,actions:[]}],
 camera:{position:[10,7,12],target:[0,1,0],fov:45}});
const finite=(v,a,b)=>typeof v==='number'&&Number.isFinite(v)&&v>=a&&v<=b;
const vector=v=>Array.isArray(v)&&v.length===3&&v.every(n=>finite(n,-40,40));
export function edit(state,batch){
 if(batch.base_revision!==state.revision)throw Error('画面が更新されました。現在の状態で指示し直してください。');
 if(!Array.isArray(batch.operations)||!batch.operations.length||batch.operations.length>20)throw Error('Invalid operations');
 const next=structuredClone(state);
 for(const o of batch.operations){
  if(o.op==='camera'){
   for(const k of ['position','target'])if(o[k]!==undefined){if(!vector(o[k]))throw Error('Invalid camera');next.camera[k]=o[k];}
   if(o.fov!==undefined){if(!finite(o.fov,15,100))throw Error('Invalid lens');next.camera.fov=o.fov;}
   if(Math.hypot(...next.camera.position.map((v,i)=>v-next.camera.target[i]))<.1)throw Error('Camera must be away from target');
   continue;
  }
  let obj=next.objects.find(x=>x.id===o.id);
  if(o.op==='add'){
   if(obj||next.objects.length>=20||typeof o.id!=='string'||!/^[a-zA-Z0-9_-]{1,32}$/.test(o.id)||!['person','car','table','box'].includes(o.kind))throw Error('Invalid new object');
   obj={id:o.id,kind:o.kind,position:[0,0,0],rotation:0,scale:1,actions:[]};next.objects.push(obj);
  }
  if(!obj)throw Error('Unknown object: '+o.id);
  if(['add','transform'].includes(o.op)){
   if(o.position!==undefined){if(!vector(o.position))throw Error('Invalid position');const delta=o.position.map((v,i)=>v-obj.position[i]);obj.actions=obj.actions.map(a=>a.to?{...a,to:a.to.map((v,i)=>v+delta[i])}:a);obj.position=o.position;}
   if(o.rotation!==undefined){if(!finite(o.rotation,-100,100))throw Error('Invalid rotation');obj.rotation=o.rotation;}
   if(o.scale!==undefined){if(!finite(o.scale,.2,4))throw Error('Invalid scale');obj.scale=o.scale;}
  }else if(o.op==='remove'){next.objects=next.objects.filter(x=>x.id!==o.id);}
  else if(o.op==='sequence'){
   if(obj.kind!=='person'||!Array.isArray(o.actions)||o.actions.length>30)throw Error('Invalid actor sequence');
   let end=0;
   for(const a of o.actions){
    if(!['walk','crouch','stand','work','wait'].includes(a.type)||!finite(a.start,0,600)||!finite(a.duration,.1,120)||a.start<end||a.type==='walk'&&!vector(a.to))throw Error('Invalid or overlapping action');
    end=a.start+a.duration;
   }
   obj.actions=structuredClone(o.actions);
  }else if(o.op==='retime'){
   if(!finite(o.factor,.1,10))throw Error('Invalid duration factor');
   obj.actions=obj.actions.map(a=>({...a,start:a.start*o.factor,duration:a.duration*o.factor}));
  }else throw Error('Unsupported operation: '+o.op);
 }
 next.revision++;return next;
}
export function poseAt(obj,time){
 let position=[...obj.position],rotation=obj.rotation,crouch=0,walk=0,work=0;
 for(const a of obj.actions){
  if(time<a.start)break;
  const p=Math.min(1,Math.max(0,(time-a.start)/a.duration));
  if(a.type==='walk'){
   const from=position;const dx=a.to[0]-from[0],dz=a.to[2]-from[2];
   if(Math.hypot(dx,dz)>.001)rotation=Math.atan2(dx,dz);
   position=from.map((v,i)=>v+(a.to[i]-v)*p);crouch=0;
   if(p<1)walk=(time-a.start)*Math.max(.4,Math.hypot(dx,dz)/a.duration)*7;
  }else if(a.type==='crouch')crouch+=(1-crouch)*p;
  else if(a.type==='stand')crouch*=1-p;
  else if(a.type==='work'&&p<1)work=(time-a.start)*5+.001;
 }
 return {position,rotation,crouch,walk,work};
}
