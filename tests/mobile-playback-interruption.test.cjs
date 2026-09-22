const {test}=require('node:test'),assert=require('node:assert/strict');
const ts=require('../mobile/node_modules/typescript'),vm=require('node:vm'),fs=require('node:fs');
const context={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('mobile/playback-interruption.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
const {PlaybackInterruption}=context.exports;

test('two microphone observations suppress continuing output within400ms',()=>{
 const g=new PlaybackInterruption();
 assert.equal(g.observe(0,.2,0),false);
 assert.equal(g.observe(.2,.2,200),false);
 assert.equal(g.observe(.2,.2,400),true);
});
test('a single noise peak or a sampling gap is not continuing speech',()=>{
 const g=new PlaybackInterruption();
 g.observe(0,.2,0);g.observe(.2,.2,200);
 assert.equal(g.observe(0,.2,400),false);
 g.observe(.2,.2,600);
 assert.equal(g.observe(.2,.2,1200),false);
});
test('assistant backchannel while user was already speaking does not trigger a new interruption',()=>{
 const g=new PlaybackInterruption();
 g.observe(.2,0,0);g.observe(.2,0,200);
 assert.equal(g.observe(.2,.2,400),false);
 assert.equal(g.observe(.2,.2,600),false);
});
test('release waits for user quiet, model input, and old output quiet',()=>{
 const g=new PlaybackInterruption();
 g.observe(0,.2,0);g.observe(.2,.2,200);assert.equal(g.observe(.2,.2,400),true);
 g.transcript();assert.equal(g.observe(.2,0,600),true);
 assert.equal(g.observe(0,0,800),true);
 assert.equal(g.observe(0,0,1000),false);
 assert.equal(g.observe(0,.2,1200),false,'the next response must be audible');
});
test('missing text and continuing model output cannot leave playback muted indefinitely',()=>{
 const g=new PlaybackInterruption();
 g.observe(0,.2,0);g.observe(.2,.2,200);g.observe(.2,.2,400);
 for(let t=600;t<1600;t+=200)assert.equal(g.observe(0,.2,t),true);
 assert.equal(g.observe(0,.2,1600),false);
});
