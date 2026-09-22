const { test } = require('node:test');
const assert = require('node:assert/strict');
const ts = require('../frontend/node_modules/typescript');
const fs = require('node:fs'), vm = require('node:vm');
const out = ts.transpileModule(fs.readFileSync('frontend/src/components/voice/live-backend.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const context = { exports: {}, crypto: require('node:crypto').webcrypto, TextEncoder, TextDecoder, Error };
vm.runInNewContext(out, context);

test('completed tool result advances while the HTTP stream remains open',async()=>{
  let cancelled=false;
  const response=new Response(new ReadableStream({
    start(c){c.enqueue(new TextEncoder().encode('data: {"type":"completed","output":[]}\n\n'));},
    cancel(){cancelled=true;},
  }));
  let timer;
  try {
    const result=await Promise.race([context.exports.readLiveBackendStream(response),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('waited for transport EOF')),500);})]);
    assert.equal(result.output.length,0);assert.equal(cancelled,true);
  } finally {clearTimeout(timer);}
});
const { LiveBackend, appendLive, readLiveBackendStream } = context.exports;
const tick = () => new Promise(r => setImmediate(r));
test('all search excerpts precede one spoken result without source rejection',()=>{
 const sent=[];
 appendLive(e=>sent.push(e),'commentary',JSON.stringify({evidence_type:'search_excerpts',
  evidence_context:['公式資料: 24時間。30日1〜6時は閉店。','口コミ: 月曜は閉店。'],spoken_evidence:'取得した店舗資料'}),'lookup');
 assert.deepEqual(sent.map(e=>e.type),['session.thinking.append','session.thinking.append','session.commentary.append']);
 assert.ok(sent.every(e=>e.delegation_id==='lookup'));
 assert.ok(sent[0].content.includes('30日1〜6時'));
});
const call = name => ({ type: 'function_call', name, call_id: name, arguments: '{}' });
const reply = text => ({ output: [{ type: 'message', content: [{ type: 'output_text', text }] }] });

test('empty routing answer releases thinking state instead of leaving hold audio on',async()=>{
 const states=[];const reports=[];
 const loop=new LiveBackend(async()=>({output:[]}),async()=>assert.fail('no tool'),text=>reports.push(text),assert.fail,()=>{},undefined,state=>states.push(state.state));
 loop.delegateSpeech('smalltalk',1,8,()=>[]);await tick();await tick();
 assert.equal(states.at(-1),'complete');assert.equal(reports.length,0);
});

test('a deferred approval is reconsidered once the same spoken turn is final',async()=>{
 let requests=0;
 const loop=new LiveBackend(async()=>{requests++;return {output:[],awaiting_final_input:requests===1};},async()=>({}),()=>{},assert.fail);
 loop.delegateSpeech('early',1,10,()=>[]);await tick();await tick();
 loop.followupSpeech(1,10,()=>[]);await tick();await tick();
 assert.equal(requests,2);
 loop.followupSpeech(1,10,()=>[]);await tick();assert.equal(requests,2);
});

test('a final transcript arriving before the defer reply is retained',async()=>{
 let release,requests=0;
 const loop=new LiveBackend(async()=>{requests++;return requests===1?await new Promise(r=>release=r):{output:[]};},async()=>({}),()=>{},assert.fail);
 loop.delegateSpeech('early',1,10,()=>[]);await tick();
 loop.followupSpeech(1,10,()=>[]);
 release({output:[],awaiting_final_input:true});await tick();await tick();
 assert.equal(requests,2);
});

test('tool dispatch retains the originating Live delegation for delayed reports', async () => {
  let count=0; const ids=[];
  const loop=new LiveBackend(async () => ++count===1 ? {output:[call('work')]} : reply('accepted'),
    async (_name,_args,id) => {ids.push(id);return {accepted:true};}, () => {}, assert.fail);
  loop.delegate('live-original-request',()=>[]);
  await tick();await tick();
  assert.deepEqual(ids,['live-original-request']);
});

test('parallel tools finish before one continuation; duplicate delegation executes once', async () => {
  const inputs = [], reports = [], finish = {};
  const loop = new LiveBackend(async input => {
    inputs.push(input);return inputs.length === 1 ? { output: [call('a'),call('b')] } : reply('found');
  }, name => new Promise(r => finish[name] = r), text => reports.push(text), assert.fail);
  loop.delegate('d', () => [{ text: 'question' }]);loop.delegate('d', () => [{ text: 'duplicate' }]);await tick();
  finish.b({ ok: true });await tick();assert.equal(inputs.length,1);
  finish.a({ ok: true });await tick();assert.equal(inputs.length,2);assert.equal(inputs[1].length,2);
  assert.equal(reports.join(),'found');
});

test('failure goes back to backend and close suppresses a late spoken result', async () => {
  const inputs=[],reports=[];let finish;
  const loop=new LiveBackend(async input=>{inputs.push(input);return inputs.length===1?{output:[call('read')]}:new Promise(r=>finish=r);},
    async()=>{throw new Error('offline');},text=>reports.push(text),assert.fail);
  loop.delegate('d',()=>[{text:'question'}]);await tick();
  assert.equal(JSON.parse(inputs[1][0].output).error,'offline');
  loop.close();finish(reply('late'));await tick();assert.equal(reports.length,0);
});

test('superseded query does not execute newly proposed actions', async () => {
  let finish;let n=0;const actions=[],reports=[];
  const loop=new LiveBackend(async()=>{n++;if(n===1)return new Promise(r=>finish=r);return reply(n===2?'old':'new');},
    async name=>{actions.push(name);return {ok:true};},text=>reports.push(text),assert.fail);
  loop.delegate('old',()=>[{text:'old'}]);await tick();loop.delegate('new',()=>[{text:'new'}]);
  finish({output:[call('publish')]});await tick();await tick();
  assert.equal(actions.length,0);assert.equal(reports.join(),'new');
});

test('append bounds preserve content and delegation ID',()=>{
  const sent=[],text='確認しました。'.repeat(100);appendLive(e=>sent.push(e),'commentary',text,'item_1');
  assert.equal(sent.map(e=>e.content).join(''),text);
  assert.ok(sent.every(e=>Buffer.byteLength(e.content)<=480&&e.delegation_id==='item_1'));
});

test('steering reaches an active request without waiting and suppresses stale actions', async () => {
  let finish, n=0; const steers=[], actions=[], reports=[];
  const loop=new LiveBackend(async()=>++n===1?new Promise(r=>finish=r):reply('changed'),
    async name=>{actions.push(name);return {};},(text,id)=>reports.push([text,id]),assert.fail,()=>{},
    async input=>{steers.push(input);return {accepted:true};});
  loop.delegate('old',()=>[{text:'buy'}]);await tick();
  loop.delegate('new',()=>[{text:'stop'}]);await tick();
  assert.equal(steers.length,1); assert.equal(n,1);
  finish({output:[call('purchase')]});await tick();await tick();
  assert.equal(actions.length,0);assert.deepEqual(reports,[['changed','new']]);
});

test('a rejected late steer runs as a new turn exactly once', async()=>{
  let finish,n=0;const reports=[];
  const loop=new LiveBackend(async()=>++n===1?new Promise(r=>finish=r):reply('new'),
    async()=>({}),t=>reports.push(t),assert.fail,()=>{},async()=>({accepted:false}));
  loop.delegate('old',()=>[{text:'old'}]);await tick();
  loop.delegate('new',()=>[{text:'new'}]);await tick();finish(reply('old'));await tick();await tick();
  assert.equal(n,2);assert.deepEqual(reports,['new']);
});

test('a follow-up does not discard the pending read-only lookup',async()=>{
  let finish,n=0;const actions=[],reports=[];
  const loop=new LiveBackend(async()=>++n===1?new Promise(r=>finish=r):reply('record found'),
    async name=>{actions.push(name);return {messages:['record']};},t=>reports.push(t),assert.fail,()=>{},async()=>({accepted:true}));
  loop.delegate('lookup',()=>[{text:'check reservation'}]);await tick();
  loop.delegate('status',()=>[{text:'what is happening?'}]);await tick();
  finish({output:[{...call('read_room_history'),arguments:'{"limit":10}'}]});await tick();await tick();
  assert.deepEqual(actions,['read_room_history']);assert.deepEqual(reports,['record found']);
});

test('a backend failure does not close the voice or replay an action',async()=>{
  let n=0,closed=0;const errors=[],reports=[];
  const loop=new LiveBackend(async()=>{if(++n===1)throw new Error('409');return reply('recovered');},
    async()=>assert.fail('no tools'),t=>reports.push(t),e=>errors.push(e),()=>closed++);
  loop.delegate('first',()=>[{text:'first'}]);await tick();
  assert.equal(n,1);assert.equal(closed,0);assert.equal(errors.length,1);
  loop.delegate('second',()=>[{text:'status'}]);await tick();assert.deepEqual(reports,['recovered']);
});

test('complete final sentences arrive before completion and are never repeated',async()=>{
  let finish;const reports=[];
  const loop=new LiveBackend(async(input,emit)=>{emit('記録では予約済み');emit('。現在は未確認');return new Promise(r=>finish=r);},
    async()=>({}),t=>reports.push(t),assert.fail);
  loop.delegate('d',()=>[]);await tick();
  assert.deepEqual(reports,['記録では予約済み。']);
  finish(reply('記録では予約済み。現在は未確認です。'));await tick();
  assert.deepEqual(reports,['記録では予約済み。','現在は未確認です。']);
});

test('SSE decoder preserves split Japanese bytes and rejects missing completion',async()=>{
  const bytes=new TextEncoder().encode('data: '+JSON.stringify({type:'text_delta',text:'確認済み。'})+'\n\ndata: '+JSON.stringify({type:'completed',output:[]})+'\n\n');
  const text=[];
  const response=new Response(new ReadableStream({start(c){for(const byte of bytes)c.enqueue(new Uint8Array([byte]));c.close();}}));
  await readLiveBackendStream(response,t=>text.push(t));assert.deepEqual(text,['確認済み。']);
  await assert.rejects(readLiveBackendStream(new Response('data: {"type":"text_delta","text":"途中"}\n\n')),/途中で切れ/);
});

test('a correction during a streamed answer delivers the revised final answer',async()=>{
  let finish,emit;const reports=[];
  const loop=new LiveBackend(async(input,onText)=>{emit=onText;emit('予約記録を見つけました。');return new Promise(r=>finish=r);},
    async()=>assert.fail('no actions'),(text,id)=>reports.push([text,id]),assert.fail,()=>{},async()=>({accepted:true}));
  loop.delegate('original',()=>[]);await tick();
  loop.delegate('correction',()=>[{text:'キャンセルの記録だけ確認して'}]);await tick();
  emit('これは古い続きです。');
  finish(reply('取消は接続エラーで完了していません。'));await tick();
  assert.deepEqual(reports,[['予約記録を見つけました。','original'],['取消は接続エラーで完了していません。','correction']]);
});

test('active-job fallback covers a missed delegation once, including a late Live event',async()=>{
 let calls=0;const reports=[];
 const backend=new LiveBackend(async()=>{calls++;return reply('updated');},async()=>({}),t=>reports.push(t),assert.fail);
 backend.followupSpeech(1,20,()=>[{text:'append checked'}]);await tick();
 backend.delegateSpeech('late-live',1,20,()=>[{text:'same request'}]);await tick();
 assert.equal(calls,1);assert.deepEqual(reports,['updated']);
 backend.delegateSpeech('next-live',2,10,()=>[{text:'another question'}]);await tick();assert.equal(calls,2);
});

test('normal delegation suppresses fallback but a continued utterance still reaches the worker',async()=>{
 let finish;const steering=[];
 const backend=new LiveBackend(async()=>new Promise(r=>finish=r),async()=>({}),()=>{},assert.fail,()=>{},async input=>{steering.push(input);return {accepted:true};});
 backend.delegateSpeech('live',1,10,()=>[{text:'create'}]);await tick();
 backend.followupSpeech(1,10,()=>[{text:'create'}]);await tick();assert.equal(steering.length,0);
 backend.followupSpeech(1,25,()=>[{text:'create with extra condition'}]);await tick();assert.equal(steering.length,1);
 finish(reply('accepted'));await tick();backend.close();
});

test('job acceptance is not spoken again or described as completed work',async()=>{
 let count=0;const reports=[],states=[];
 const backend=new LiveBackend(async(input,emit)=>{
  if(++count===1)return {output:[call('delegate_to_dan')]};
  emit('担当に依頼しました。');return reply('担当に依頼しました。');
 },async()=>({accepted:true,receipt:{id:'job'}}),t=>reports.push(t),assert.fail,()=>{},undefined,s=>states.push(s.state));
 backend.delegate('live',()=>[{text:'create memo'}]);await tick();await tick();
 assert.deepEqual(reports,[]);assert.equal(states.at(-1),'executing');
});


test('a complete search passage is spoken once without JSON fragments or interrupting instructions',()=>{
 const events=[];
 const passage='公式案内：土曜日は9時30分から20時まで。';
 const text=JSON.stringify({evidence_type:'search_excerpts',spoken_evidence:passage,results:[{snippet:'根拠となる本文。'.repeat(120)}]});
 context.exports.appendLive(e=>events.push(e),'commentary',text,'search-id');
 assert.equal(events.length,1);
 assert.equal(events[0].type,'session.commentary.append');
 assert.equal(events[0].delegation_id,'search-id');
 assert.equal(events[0].content,passage);
});

test('large history is silent context followed by one answer notification',()=>{
 const events=[],record=JSON.stringify({messages:[{role:'user',text:'以前伝えた記録。'.repeat(300)}]});
 context.exports.appendLive(e=>events.push(e),'commentary',record,'history-id');
 const thoughts=events.filter(e=>e.type==='session.thinking.append');
 assert.equal(thoughts.map(e=>e.content).join(''),record);
 assert.equal(events.filter(e=>e.type==='session.commentary.append').length,1);
 assert.equal(events.at(-1).type,'session.commentary.append');
 assert.ok(events.every(e=>Buffer.byteLength(e.content)<=480&&e.delegation_id==='history-id'));
});

test('phone and web final follow-up answers are not silently discarded',()=>{
 for(const file of ['mobile/voice.tsx','frontend/src/components/voice/voice-session.tsx']) {
  const source=fs.readFileSync(file,'utf8');
  assert.ok(!source.includes("id.startsWith('followup-') ? 'thinking' : 'commentary'"),file);
 }
});

test('a failed backend releases the working indicator and does not retry',async()=>{
 const states=[],errors=[];let count=0;
 const loop=new LiveBackend(async()=>{count++;throw Error('failed');},async()=>assert.fail('no replay'),
   ()=>{},e=>errors.push(e),()=>{},undefined,s=>states.push(s.state));
 loop.delegate('query',()=>[]);await tick();
 assert.deepEqual(states,['reasoning','failed']);assert.equal(count,1);assert.equal(errors.length,1);
});
