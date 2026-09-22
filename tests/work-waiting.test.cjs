const {test} = require('node:test');
const assert = require('node:assert/strict');
const ts = require('../mobile/node_modules/typescript');
const fs = require('node:fs'), vm = require('node:vm');
const context = {exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('frontend/src/components/voice/work-waiting.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
const {WorkWaiting,isWorking} = context.exports;
test('silence alone is quiet; real work waits, yields to speech, then stops on completion',()=>{
  const output=[];const cue=new WorkWaiting(v=>output.push(v));
  cue.update(1000,false,false);cue.update(3000,false,false);assert.deepEqual(output,[]);
  cue.update(4000,true,false);cue.update(5199,true,false);assert.deepEqual(output,[]);
  cue.update(5200,true,false);assert.deepEqual(output,[true]);
  cue.speech(5300);cue.update(5800,true,false);assert.deepEqual(output,[true,false]);
  cue.update(6100,true,false);cue.update(6200,false,false);assert.deepEqual(output,[true,false,true,false]);
  assert.equal(isWorking('executing',false),false); // confirmation/completed job isn't running
  assert.equal(isWorking('reading',false),true);
  assert.equal(isWorking('complete',true),true);
});
test('disconnect and caller speech never leave a waiting loop playing',()=>{
  const output=[];const cue=new WorkWaiting(v=>output.push(v));
  cue.update(1000,true,false);cue.update(3000,true,true);assert.deepEqual(output,[]);
  cue.update(4000,true,false);cue.close();assert.deepEqual(output,[true,false]);
  cue.update(5000,true,false,false);assert.deepEqual(output,[true,false]);
});
