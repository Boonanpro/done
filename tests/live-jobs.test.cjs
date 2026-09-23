const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const ts=require('../frontend/node_modules/typescript');
const code=ts.transpileModule(fs.readFileSync('frontend/src/components/voice/live-jobs.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const mod={exports:{}};new Function('module','exports',code)(mod,mod.exports);
const {LiveJobs}=mod.exports;

test('coalesces progress, preserves confirmation and delivers each event once',()=>{
 const tracker=new LiveJobs(0),job={id:'a',task:'train',state:'running',created_at:new Date().toISOString(),seq:3,
 events:[{seq:1,kind:'progress',text:'search'},{seq:2,kind:'progress',text:'14 car'},{seq:3,kind:'confirmation',text:'buy?'}]};
 assert.deepEqual(tracker.updates([job]).map(x=>x.event.text),['14 car','buy?']);
 assert.deepEqual(tracker.updates([job]),[]);
});
test('reconnection suppresses old completed work but retains active confirmation',()=>{
 const tracker=new LiveJobs(1000),base={task:'train',created_at:new Date(0).toISOString(),seq:1,events:[{seq:1,kind:'confirmation',text:'buy?'}]};
 assert.equal(tracker.updates([{...base,id:'old',state:'completed'},{...base,id:'active',state:'awaiting_confirmation'}]).length,1);
});
