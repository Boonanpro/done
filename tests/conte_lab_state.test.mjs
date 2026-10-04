import test from 'node:test';
import assert from 'node:assert/strict';
import {initial,edit,poseAt} from '../app/static/conte-lab/state.mjs';
test('atomic edits preserve other objects, reject stale and malformed batches',()=>{
 const s=initial(),car=structuredClone(s.objects[1]);
 const next=edit(s,{base_revision:0,operations:[{op:'transform',id:'man',position:[4,0,2]}]});
 assert.deepEqual(next.objects[1],car);assert.deepEqual(s.objects[0].position,[-3,0,1.5]);
 assert.throws(()=>edit(next,{base_revision:0,operations:[{op:'remove',id:'car'}]}));
 assert.throws(()=>edit(s,{base_revision:0,operations:[{op:'remove',id:'car'},{op:'transform',id:'absent'}]}));
 assert.equal(s.objects.length,3);
});
test('seeking and retiming are deterministic',()=>{
 let s=edit(initial(),{base_revision:0,operations:[{op:'sequence',id:'man',actions:[{type:'walk',start:0,duration:4,to:[-3,0,-1.2]},{type:'crouch',start:4,duration:1}]}]});
 assert.equal(poseAt(s.objects[0],5).crouch,1);
 assert.deepEqual(poseAt(s.objects[0],0).position,[-3,0,1.5]);
 const p=poseAt(s.objects[0],2);
 s=edit(s,{base_revision:1,operations:[{op:'retime',id:'man',factor:.5}]});
 assert.deepEqual(poseAt(s.objects[0],1).position,p.position);
 assert.equal(poseAt(s.objects[0],2.5).crouch,1);
});
