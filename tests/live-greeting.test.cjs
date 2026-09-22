const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const ts=require('../frontend/node_modules/typescript');
const code=ts.transpileModule(fs.readFileSync('frontend/src/components/voice/live-greeting.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{}};vm.runInNewContext(code,context);
const {LiveGreeting}=context.exports;
function setup(){let time=0;const sent=[],events=[];const g=new LiveGreeting(e=>sent.push(e),e=>events.push(e),()=>time);return {g,sent,events,at:t=>time=t};}
test('only matching acknowledgement prompts speech; repeat start/ack does not duplicate',()=>{
 const {g,sent}=setup();g.start('one');g.start('two');
 g.observe({type:'session.instructions.appended',client_event_id:'other'});assert.equal(sent.length,1);
 g.observe({type:'session.instructions.appended',client_event_id:'one'});g.observe({type:'session.instructions.appended',client_event_id:'one'});
 assert.equal(sent.length,2);assert.equal(sent[1].type,'session.commentary.append');
});
test('silent session gets one bounded retry and reports failure',()=>{
 const {g,sent,events,at}=setup();g.start('one');g.observe({type:'session.instructions.appended',client_event_id:'one'});
 at(5000);g.tick();at(9000);g.tick();at(12000);g.tick();g.tick();
 assert.equal(sent.length,3);assert.equal(events.filter(e=>e==='greeting_no_output').length,1);
});
test('either user speech, model text, or actual audio cancels further nudges',()=>{
 for(const type of ['session.input_transcript.delta','session.output_transcript.delta','audio']){
  const {g,sent,at}=setup();g.start('one');
  if(type==='audio')g.audio();else g.observe({type,delta:'hello'});
  g.observe({type:'session.instructions.appended',client_event_id:'one'});at(6000);g.tick();assert.equal(sent.length,1);
 }
});
