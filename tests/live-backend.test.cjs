const { test } = require('node:test');
const assert = require('node:assert/strict');
const ts = require('../frontend/node_modules/typescript');
const fs = require('node:fs'), vm = require('node:vm');
const out = ts.transpileModule(fs.readFileSync('frontend/src/components/voice/live-backend.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const context = { exports: {}, crypto: require('node:crypto').webcrypto, TextEncoder, TextDecoder, Error };
vm.runInNewContext(out, context);
const { appendLive } = context.exports;

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

test('append bounds preserve content and delegation ID',()=>{
  const sent=[],text='確認しました。'.repeat(100);appendLive(e=>sent.push(e),'commentary',text,'item_1');
  assert.equal(sent.map(e=>e.content).join(''),text);
  assert.ok(sent.every(e=>Buffer.byteLength(e.content)<=480&&e.delegation_id==='item_1'));
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
