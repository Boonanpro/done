const {test}=require('node:test');
const assert=require('node:assert/strict');
const ts=require('../mobile/node_modules/typescript');
const fs=require('node:fs'),vm=require('node:vm');
const context={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('mobile/voice-sdp.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
const {withAudioRecovery}=context.exports;
test('adds NACK to each audio Opus payload only and keeps existing feedback',()=>{
 const s=['v=0','m=audio 9 UDP/TLS/RTP/SAVPF 109 0','a=rtpmap:109 opus/48000/2','a=fmtp:109 useinbandfec=1','a=rtcp-fb:109 transport-cc','m=video 9 UDP/TLS/RTP/SAVPF 111','a=rtpmap:111 VP8/90000','m=application 9 UDP/DTLS/SCTP webrtc-datachannel','a=sctp-port:5000',''].join('\r\n');
 const out=withAudioRecovery(s);
 assert.ok(out.includes('a=rtcp-fb:109 nack\r\nm=video'));
 assert.equal(out.replace('a=rtcp-fb:109 nack\r\n',''),s);
 assert.equal(withAudioRecovery(out),out);
});
test('handles LF and multiple audio sections without touching other codecs',()=>{
 const s='v=0\nm=audio 9 RTP/AVP 0\na=rtpmap:0 PCMU/8000\nm=audio 9 RTP/AVP 112\na=rtpmap:112 opus/48000/2\na=rtcp-fb:112 nack\n';
 assert.equal(withAudioRecovery(s),s);
});
test('keeps a trailing line terminator without introducing an empty SDP line',()=>{
 const s='v=0\r\nm=audio 9 RTP/AVP 111\r\na=rtpmap:111 opus/48000/2\r\n';
 assert.equal(withAudioRecovery(s),s+'a=rtcp-fb:111 nack\r\n');
});
