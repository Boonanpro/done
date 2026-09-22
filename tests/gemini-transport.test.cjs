const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('../frontend/node_modules/typescript');
const context={exports:{},setTimeout,clearTimeout,performance,WebSocket:{OPEN:1}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('frontend/src/components/voice/gemini-transport.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
function setup(){
 const messages=[],events=[];
 const destination={disconnect(){},stream:{getTracks:()=>[]}};
 const t=new context.exports.GeminiTransport({createMediaStreamDestination:()=>destination},{token:'private',session:{id:'test'}},e=>events.push(e),()=>events.push('interrupt'),()=>{});
 t.socket={readyState:1,send:x=>messages.push(JSON.parse(x)),close(){}};
 t.connectionState='connected';
 return {t,messages,events};
}
test('utterance completion does not end background reasoning or the connection',()=>{
 const {t}=setup();t.connectionState='connected';
 t.receive({serverContent:{turnComplete:true},interactionStatus:'IN_PROGRESS'});
 assert.equal(t.connectionState,'connected');assert.equal(t.interactionStatus,'IN_PROGRESS');
 t.receive({interactionStatus:'IDLE'});assert.equal(t.interactionStatus,'IDLE');
});
test('tool results retain IDs and canceled/replayed calls do not produce speech',()=>{
 const {t,messages,events}=setup();
 const call={toolCall:{functionCalls:[{id:'a',name:'ask_dan',args:{request:'調べて'}}]}};
 t.receive(call);t.receive(call);assert.equal(events.length,1);
 t.complete('a','調査結果');assert.equal(messages[0].toolResponse.functionResponses[0].id,'a');
 t.complete('a','重複');assert.equal(messages.length,1);
 t.receive({toolCall:{functionCalls:[{id:'b',name:'ask_dan'}]}});
 t.receive({toolCallCancellation:{ids:['b']}});t.complete('b','古い結果');assert.equal(messages.length,1);
});
test('interruption stops scheduled audio and clears Atom output',()=>{
 const {t,events}=setup();let stopped=0;
 t.sources.add({stop(){stopped++},disconnect(){}});t.at=10;
 t.receive({serverContent:{interrupted:true}});
 assert.equal(stopped,1);assert.equal(t.at,0);assert.ok(events.includes('interrupt'));
});
test('new delegation settles the previous function and reconnect retains a late result',()=>{
 const {t,messages}=setup();
 t.receive({toolCall:{functionCalls:[{id:'a',name:'ask_dan'}]}});
 t.receive({toolCall:{functionCalls:[{id:'b',name:'ask_dan'}]}});
 assert.equal(messages[0].toolResponse.functionResponses[0].response.status,'superseded');
 t.connectionState='connecting';t.complete('b','new result');
 assert.equal(messages.length,1);assert.equal(t.outgoing.length,1);
});
test('close suppresses late results and queued notifications',async()=>{
 const {t,messages}=setup();
 t.append({type:'session.commentary.append',content:'late'});t.close();
 t.complete('unknown','late');await new Promise(r=>setTimeout(r,5));assert.equal(messages.length,0);
});
test('microphone worklet emits 20 ms PCM packets across render blocks',()=>{
 let Processor;const packets=[];
 const c={AudioWorkletProcessor:class{constructor(){this.port={postMessage:b=>packets.push(b)}}},registerProcessor:(_name,p)=>Processor=p};
 vm.runInNewContext(fs.readFileSync('frontend/public/gemini-mic-worklet.js','utf8'),c);
 const mic=new Processor();for(let i=0;i<15;i++)mic.process([[new Float32Array(128).fill(.5)]],[[new Float32Array(128)]]);
 assert.equal(packets.length,2);assert.equal(new Int16Array(packets[0]).length,320);
 assert.equal(new Int16Array(packets[0])[0],16384);
});
