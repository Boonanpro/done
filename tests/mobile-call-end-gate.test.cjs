const {test}=require('node:test');
const assert=require('node:assert/strict');
const ts=require('../mobile/node_modules/typescript'),vm=require('node:vm'),fs=require('node:fs');
function load(file){const context={exports:{},require:()=>load('mobile/call-intent.ts')};vm.runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);return context.exports;}
const {CallEndGate}=load('mobile/call-end-gate.ts');
function silence(g,from,to){for(let t=from;t<=to;t+=200)g.microphone(0,t);}
test('clear request ends with measured silence without 2.5 second transcript flush',()=>{
 const g=new CallEndGate();g.microphone(.2,0);g.transcript('電話を切ってください',500);
 silence(g,200,800);assert.equal(g.shouldEnd(800),true);assert.equal(g.shouldEnd(900),false);
});
test('partial request while still speaking never closes',()=>{
 const g=new CallEndGate();g.microphone(.2,0);g.transcript('電話切って',200);
 for(let t=200;t<=1200;t+=200)g.microphone(.2,t);
 assert.equal(g.shouldEnd(1200),false);
 g.transcript('電話切ってほしくない',1300);silence(g,1400,2200);
 assert.equal(g.shouldEnd(2200),false);
});
test('missing microphone stats and stale sampling cannot mean silence',()=>{
 const g=new CallEndGate();g.microphone(.2,0);g.transcript('電話切って',200);
 g.microphone(null,1000);assert.equal(g.shouldEnd(1000),false);
 g.microphone(0,1100);assert.equal(g.shouldEnd(1100),false);
});
test('late transcript continuation cancels a pending ending',()=>{
 const g=new CallEndGate();g.microphone(.2,0);g.transcript('電話切って',500);silence(g,200,600);
 assert.equal(g.shouldEnd(600),false);
 g.transcript('電話切って。いや、まだ切らないで',700);silence(g,800,1600);
 assert.equal(g.shouldEnd(1600),false);
});

test('context review starts after real silence and is consumed once',()=>{
 const g=new CallEndGate();g.microphone(.2,0);g.transcript('じゃあまた呼ぶね',200);
 silence(g,200,800);const review=g.takeReview(800);
 assert.ok(review);assert.equal(g.takeReview(800),null);
 assert.equal(g.acceptReview(review.revision,800),true);
 assert.equal(g.acceptReview(review.revision,800),false);
});

test('new speech invalidates a decision even before the next transcript arrives',()=>{
 const g=new CallEndGate();g.microphone(.2,0);g.transcript('切って',200);
 silence(g,200,800);const review=g.takeReview(800);
 g.microphone(.2,900);silence(g,1000,1800);
 assert.equal(g.acceptReview(review.revision,1800),false);
 assert.equal(g.takeReview(1800),null,'old words must not be reclassified after new speech');
 g.transcript('いや、電話はまだ切らないで',1900);silence(g,2000,2400);
 assert.ok(g.takeReview(2400));
});

test('context review never treats absent microphone sampling as silence',()=>{
 const g=new CallEndGate();g.transcript('切って',0);
 assert.equal(g.takeReview(3000),null);
 g.microphone(.2,3100);silence(g,3300,3900);const review=g.takeReview(3900);
 assert.ok(review);assert.equal(g.acceptReview(review.revision,4400),false);
});
