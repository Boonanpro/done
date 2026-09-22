const {test}=require('node:test');
const assert=require('node:assert/strict');
const ts=require('../mobile/node_modules/typescript');
const fs=require('node:fs'),vm=require('node:vm');
const context={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('mobile/voice-quality.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
const {voiceQuality}=context.exports;

test('reports only the selected path and upstream loss, without addresses',()=>{
 const q=context.exports.voiceTransport([
  {type:'transport',selectedCandidatePairId:'selected'},
  {id:'unused',type:'candidate-pair',nominated:true,currentRoundTripTime:9},
  {id:'selected',type:'candidate-pair',state:'succeeded',currentRoundTripTime:.2,localCandidateId:'local',remoteCandidateId:'remote'},
  {id:'local',type:'local-candidate',candidateType:'srflx',protocol:'udp',address:'private',port:1234},
  {id:'remote',type:'remote-candidate',candidateType:'host',protocol:'udp',address:'secret'},
  {type:'remote-inbound-rtp',kind:'audio',packetsLost:12,fractionLost:.1},
 ]);
 assert.equal(q.pair.rtt,.2);assert.equal(q.upstream[0].packetsLost,12);
 assert.equal(q.pair.local.type,'srflx');assert.equal(q.pair.local.address,undefined);
 assert.ok(!JSON.stringify(q).includes('secret'));assert.ok(!JSON.stringify(q).includes('1234'));
 assert.equal(context.exports.voiceTransport([]).pair,null);
});
test('unsupported counters remain unknown, not a false perfect connection',()=>{
 const q=voiceQuality([{type:'inbound-rtp',kind:'audio',audioLevel:.2}]);
 assert.equal(q.inbound[0].concealedSamples,null);
 assert.equal(q.inbound[0].packetsLost,null);
 assert.equal(q.outputLevel,.2);
});
test('keeps concealment evidence and excludes video and identifying fields',()=>{
 const q=voiceQuality([
  {type:'media-source',kind:'audio',audioLevel:.1},
  {type:'inbound-rtp',mediaType:'audio',concealedSamples:4800,packetsLost:2,jitter:.02,ssrc:123,ip:'private'},
  {type:'inbound-rtp',kind:'video',packetsLost:500},
 ]);
 assert.equal(q.inputLevel,.1);
 assert.equal(q.inbound.length,1);
 assert.equal(q.inbound[0].concealedSamples,4800);
 assert.equal(q.inbound[0].ssrc,undefined);
 assert.equal(q.inbound[0].ip,undefined);
});
