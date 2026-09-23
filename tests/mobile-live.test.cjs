const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const ts = require('../mobile/node_modules/typescript');
const tick = () => new Promise(resolve => setImmediate(resolve));

test('call setup and the job poll do not depend on paused global fetch; the phone does not speak job results itself',async()=>{
 const job={id:'background-job',task:'Check hours',state:'completed',created_at:new Date(Date.now()+1000).toISOString(),seq:1,
  events:[{seq:1,kind:'result',text:'Open until 20:00'}]};
 const h=harness({pausedFetch:true,jobPollResults:[{jobs:[job]}]});
 try {
  for(let i=0;i<10;i++)await tick();
  assert.ok(h.pc,'native session setup completes');
  h.tickBackground(2000);for(let i=0;i<10;i++)await tick();
  assert.ok(!h.sent.some(e=>e.type==='session.commentary.append' && e.content.includes('20:00')));   // the server's sideband speaks it
  assert.ok(h.requests.some(r=>r.body && r.body.event==='voice-job-received'));
 }finally{h.dispose();}
});
test('completed work is recorded as activity once and never appended by the phone',async()=>{
 const job={id:'j',task:'営業時間の確認',state:'completed',created_at:new Date(Date.now()+1000).toISOString(),seq:1,
  events:[{seq:1,kind:'result',text:'公式ページで24時間営業を確認しました。'}]};
 const h=harness({jobPollResults:[{jobs:[job]},{jobs:[job]}]});
 try{
  for(let i=0;i<8;i++)await tick();
  h.tickBackground(2000);for(let i=0;i<8;i++)await tick();
  h.tickBackground(2000);for(let i=0;i<8;i++)await tick();
  assert.equal(h.sent.filter(e=>e.type==='session.commentary.append' && e.content.includes('24時間営業')).length,0);
  assert.ok(h.requests.some(r=>r.body.event==='voice-job-received' && r.body.extra.job_id==='j'));
 }finally{h.dispose();}
});

function harness({pausedFetch = false, missingSession = false, jobPollResults = [], failSession = false, holdStandby = false, activeJob = false, holdEndpointStats = false, audioBusy = false, audioEndpoint = 'phone', holdAtom = false, failAtom = false, atomHeadset = false, controlClarification = false, holdControl = false, fastControl = false, holdFastControl = false} = {}) {
  const effects = [], requests = [], sent = [], timers = new Set();
  let pc, track, closed = 0, audioStopped = 0;
  let nativeTick, nativeEnd, finishCue, offset = 0;
  let statsReads = 0, endpointReads = 0;
  let releaseAtom;
  let releaseControl;
  let microphone = .2, releaseFastControl;
  const cues = [], audioBindings = [];
  let jobPollIndex = 0;
  const deadlines = [];
  const later = (fn, ms) => {if(ms===5000) deadlines.push(fn); const id = setTimeout(fn, ms); timers.add(id); return id;};
  const React = {createElement: () => ({}), useCallback: fn => fn,
    useEffect: fn => effects.push(fn), useRef: value => ({current: value}),
    useState: value => [value, () => {}], useSyncExternalStore: (_subscribe, get) => get()};
  const Animated = {Value: class {interpolate() {return 0;}}, timing: () => ({start() {}}), loop: () => ({start() {},stop() {}})};
  class PC {
    constructor() {pc = this; this._pcId = 41; this.listeners = {}; this.iceGatheringState = 'complete'; this.connectionState = 'connected';}
    addTrack() {}
    async getStats() {statsReads++; return fastControl ? new Map([['mic',{type:'media-source',kind:'audio',audioLevel:microphone}]]) : new Map();}
    addEventListener(name, listener) {this.listeners[name] = listener;}
    createDataChannel() {return this.dc = {readyState: 'open', addEventListener: (_, fn) => this.receive = fn,
      send: value => sent.push(JSON.parse(value)), close: () => {this.dc.closed = true;}};}
    async createOffer() {return {type: 'offer', sdp: 'offer'};}
    async setLocalDescription(value) {this.localDescription = value;}
    async setRemoteDescription() {
      if(audioEndpoint==='atom') this.listeners.track({track:{kind:'audio',id:'remote-audio',_peerConnectionId:41}});
      this.event({type: 'session.started', session: {id: 'live-test'}});
    }
    event(value) {this.receive({data: JSON.stringify(value)});}
    close() {audioBindings.push(['close',this._pcId]); this.closed = true;}
  }
  const modules = {
    'expo-updates': {updateId:'test-update'},
    'expo-secure-store': {getItemAsync: async () => null, setItemAsync: async () => {}},   // ui-language (display language)
    react: {...React, default: React},
    'react-native': {Animated, DeviceEventEmitter:{addListener:()=>({remove(){}})}, Easing: {linear: 0}, Platform: {OS: 'android',Version: 31}, StyleSheet: {create: x => x},
      PermissionsAndroid: {PERMISSIONS: {BLUETOOTH_CONNECT: 'bt'}, check: async () => true}},
    '@expo/vector-icons': {},
    'react-native-safe-area-context': {useSafeAreaInsets: () => ({top:0,bottom:0,left:0,right:0})},
    'react-native-webrtc': {RTCPeerConnection: PC, mediaDevices: {getUserMedia: async () => {
      track = {enabled:true,stop() {this.stopped = true;}}; return {getTracks: () => [track],getAudioTracks:()=>[track]};
    }}},
    'react-native-incall-manager': {default: {start() {},stop() {audioStopped++;},setForceSpeakerphoneOn() {},setKeepScreenOn() {},chooseAudioRoute:async()=>({selectedAudioDevice:'EARPIECE',availableAudioDeviceList:'["EARPIECE","SPEAKER_PHONE"]'})}},
    './voice-background': {playAtomVoiceCue: async (kind,id) => {
      audioBindings.push(['cueDestination',id,kind]);
      if(!atomHeadset) return;
      cues.push(kind);
      if(kind==='standby' && holdStandby) await new Promise(resolve=>{finishCue=resolve;});
    },muteExternalAudio() {},connectAtomAudio: async () => {if(failAtom) throw Error('Atom unreachable'); if(holdAtom) await new Promise(resolve=>{releaseAtom=resolve;});return true;},audioEndpointStats: async () => {endpointReads++; if(holdEndpointStats) await new Promise(()=>{}); return null;}, bindRemoteAudio: async (id, trackId) => {audioBindings.push(['bind',id,trackId]); return true;},
      unbindRemoteAudio: id => audioBindings.push(['unbind',id]),setWorkWaiting() {},markVoiceConnected() {},playVoiceCue: async kind => {
      cues.push(kind);
      if (kind === 'standby' && holdStandby) await new Promise(resolve => {finishCue = resolve;});
    },startVoiceBackground: async () => {if(audioBusy) throw Error('Audio busy'); return 'test-lease';},stopVoiceBackground() {},
      onVoiceEnd: fn => {nativeEnd=fn; return {remove() {nativeEnd=undefined;}};},
      onVoiceTick: fn => {nativeTick=fn; return {remove() {nativeTick=undefined;}};}},
  };
  function load(file) {
    const context = {exports: {}, console, TextDecoder, AbortController, Date: class extends Date {static now() {return Date.now()+offset;}}, setTimeout: later, clearTimeout, setInterval: later, clearInterval: clearTimeout,
      performance, fetch: async (url, options) => {
        const body = JSON.parse(options.body); requests.push({url,body});
        let data = {};
        if (url.endsWith('/atom-direct')) data={host:'test.invalid',key:'test'};
        if (url.endsWith('/live/session')) data = failSession ? {detail: 'unavailable'} : {session: {id: 'live-test'},transport: {sdp: 'answer'}};
        if (url.endsWith('/command-center') && body.args?.action==='jobs') data={jobs:activeJob ? [{id:'job',task:'write memo',state:'running',created_at:new Date().toISOString(),seq:0,events:[]}] : []};
        if (url.endsWith('/command-center') && body.args?.action==='jobs' && jobPollIndex < jobPollResults.length) {
          const result = jobPollResults[jobPollIndex++];
          if(result==='hang') await new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('timeout'))));
          else data=result;
        }
        if (url.endsWith('/live/backend/stream')) {
          if(missingSession)return new Response(JSON.stringify({detail:'session lost'}),{status:409});
          if(holdControl) await new Promise(resolve=>{releaseControl=resolve;});
          return new Response('data: '+JSON.stringify({type:'completed',output:controlClarification ? [{type:'message',content:[{type:'output_text',text:'この通話を終了しますか？'}]}] : activeJob ? [{type:'message',content:[{type:'output_text',text:'変更を受信しました。'}]}] : [{type: 'function_call',name: 'enter_voice_standby',call_id: 'hangup',arguments: '{}'}]})+'\n\n');
        }
        return {ok: !(failSession && url.endsWith('/live/session')),status: 503,json: async () => data};
      }, require: name => {
        if(name==='expo/fetch')return {fetch:nativeFetch};
        if(modules[name])return modules[name];
        const path=require('node:path');
        const base=path.resolve(path.dirname(file),name);
        const source=['.ts','.tsx'].map(ext=>base+ext).find(candidate=>fs.existsSync(candidate));
        if(!source)throw Error('Unresolved test dependency: '+name);
        return load(source);
      }};
    const nativeFetch=context.fetch;
    if(pausedFetch) context.fetch=()=>new Promise(()=>{});
    vm.runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'), {compilerOptions: {
      module: ts.ModuleKind.CommonJS,target: ts.ScriptTarget.ES2022,jsx: ts.JsxEmit.React,
    }}).outputText, context);
    return context.exports;
  }
  const {VoiceOverlay} = load('mobile/voice.tsx');
  VoiceOverlay({visible: true, roomId: 'room-test',apiBase: 'https://test.invalid',token: 'test',audioEndpoint,onClose: () => closed++});
  const cleanups = effects.map(fn => fn()).filter(Boolean);
  return {requests,sent,cues,audioBindings,finishCue: () => finishCue?.(),get pc() {return pc;},get track() {return track;},get closed() {return closed;},
    expireJobRead:()=>deadlines.shift()?.(),
    releaseAtom:()=>releaseAtom?.(),
    releaseControl:()=>releaseControl?.(),
    microphone:level=>{microphone=level;}, releaseFastControl:()=>releaseFastControl?.(),
    get statsReads() {return statsReads;},get endpointReads() {return endpointReads;},
    get audioStopped() {return audioStopped;},tickBackground(ms) {offset += ms; nativeTick?.();},endFromNotification() {nativeEnd?.();},
    dispose() {for (const cleanup of cleanups) cleanup(); for (const id of timers) clearTimeout(id);}};
}

test('an explicit end request is not acted on by the phone: the server decides (end_call) and closes the session', async () => {
 const h=harness({fastControl:true});
 try {
  for(let i=0;i<8;i++)await tick();
  h.tickBackground(0);await tick();
  h.pc.event({type:'session.input_transcript.delta',delta:'電話切って',start_ms:0,end_ms:300});
  h.microphone(0);
  for(let i=0;i<4;i++){h.tickBackground(200);await tick();}
  for(let i=0;i<30;i++){h.tickBackground(100);await tick();}   // past the transcript flush
  assert.ok(!h.pc.closed);
  assert.equal(h.requests.filter(r=>r.url.endsWith('/live/call-control')).length,0);
 } finally {h.dispose();}
});

test('Atom setup keeps phone mic closed and greeting waits for the same peer attachment', async () => {
  const h=harness({audioEndpoint:'atom',holdAtom:true});
  try {
    for(let i=0;i<8;i++) await tick();
    assert.equal(h.track.enabled,false);
    assert.ok(!h.sent.some(e=>String(e.event_id).startsWith('mobile-greeting')));
    h.releaseAtom(); for(let i=0;i<4;i++) await tick();
    assert.equal(h.track.enabled,true);
    assert.ok(h.sent.some(e=>String(e.event_id).startsWith('mobile-greeting')));
    assert.deepEqual(h.cues,[]); // Atom firmware owns the cues for this route.
    assert.equal(h.requests.filter(r=>r.url.endsWith('/live/session')).length,1);
    h.endFromNotification(); for(let i=0;i<4;i++) await tick();
    assert.equal(h.pc.closed,true); assert.deepEqual(h.cues,[]);
  } finally {h.dispose();}
});

test('Atom headset cues capture route before teardown without delaying paid audio closure', async () => {
  const h=harness({audioEndpoint:'atom',atomHeadset:true,holdStandby:true});
  try {
    for(let i=0;i<8;i++) await tick();
    assert.deepEqual(h.cues,['ready']);
    h.endFromNotification();
    assert.equal(h.pc.closed,true);
    assert.equal(h.track.stopped,true);
    const destination=h.audioBindings.findIndex(x=>x[0]==='cueDestination'&&x[2]==='standby');
    const unbind=h.audioBindings.findIndex(x=>x[0]==='unbind');
    assert.ok(destination>=0 && unbind>destination);
    assert.equal(h.closed,0);
    h.finishCue(); for(let i=0;i<4;i++) await tick();
    assert.equal(h.closed,1);
    assert.deepEqual(h.cues,['ready','standby']);
  } finally {h.dispose();}
});

test('Atom attachment failure closes paid audio instead of falling back to phone mic', async () => {
  const h=harness({audioEndpoint:'atom',failAtom:true});
  try {
    for(let i=0;i<12;i++) await tick();
    assert.equal(h.track.enabled,false); assert.equal(h.track.stopped,true); assert.equal(h.pc.closed,true);
    assert.ok(!h.sent.some(e=>String(e.event_id).startsWith('mobile-greeting')));
  } finally {h.dispose();}
});

test('failed audio reservation never opens or stops another microphone/audio route', async () => {
  const h=harness({audioBusy:true});
  try {
    for(let i=0;i<8;i++) await tick();
    assert.equal(h.pc,undefined); assert.equal(h.track,undefined);
    assert.equal(h.audioStopped,0);
    assert.ok(!h.requests.some(r=>r.url.endsWith('/live/session')));
  } finally {h.dispose();}
});

test('slow native diagnostics do not stall mic sampling or notification hangup', async () => {
  const h=harness({holdEndpointStats:true});
  try {
    for(let i=0;i<8;i++) await tick();
    h.tickBackground(5001); await tick();
    const first=h.statsReads;
    assert.ok(first>0); assert.equal(h.endpointReads,1);
    h.tickBackground(5001); await tick();
    assert.ok(h.statsReads>first); assert.equal(h.endpointReads,1);
    h.endFromNotification();
    for(let i=0;i<4;i++) await tick();
    assert.equal(h.pc.closed,true); assert.equal(h.closed,1);
  } finally {h.dispose();}
});

test('remote audio attaches to its peer, detaches before close, and ignores late track events', async () => {
  const h = harness();
  try {
    for (let i=0;i<8;i++) await tick();
    const event = {track:{kind:'audio',id:'remote-audio',_peerConnectionId:41}};
    h.pc.listeners.track(event);
    await tick();
    assert.deepEqual(h.audioBindings, [['bind',41,'remote-audio']]);
    h.endFromNotification();
    for (let i=0;i<4;i++) await tick();
    const unbind = h.audioBindings.findIndex(e => e[0] === 'unbind');
    const close = h.audioBindings.findIndex(e => e[0] === 'close');
    assert.ok(unbind >= 0 && close > unbind);
    h.pc.listeners.track(event); await tick();
    assert.equal(h.audioBindings.filter(e => e[0] === 'bind').length, 1);
  } finally {h.dispose();}
});

test('mobile uses Live with room context; delegated hangup stops microphone, peer, channel and native route', async () => {
  const h = harness();
  try {
    for (let i=0;i<8;i++) await tick();
    const session = h.requests.find(r => r.url.endsWith('/live/session'));
    assert.equal(session.body.room_id, 'room-test'); assert.equal(session.body.device, true); assert.equal(session.body.provider, 'openai');
    assert.ok(h.sent.some(e => e.type === 'session.instructions.append'));
    h.pc.event({type: 'session.input_transcript.delta',delta: '電話を切ってください',start_ms: 0,end_ms: 1000});
    h.pc.event({type: 'session.delegation.created',delegation: {id: 'end-request'}});
    h.pc.event({type: 'session.closed'});   // the server's end_call closes the session; the phone follows
    for (let i=0;i<8;i++) await tick();
    assert.equal(h.closed,1); assert.equal(h.track.stopped,true); assert.equal(h.pc.closed,true); assert.equal(h.pc.dc.closed,true);
    assert.ok(h.requests.some(r => r.url.endsWith('/live/backend/close')));
    assert.ok(h.requests.some(r => r.url.endsWith('/room-test') && r.body.content === '電話を切ってください'));
    assert.ok(!h.requests.some(r => r.url.endsWith('/live/backend/stream')));   // the phone never answers delegations
    assert.equal(h.requests.find(r => r.url.endsWith('/live/session')).body.server_delegation, true);
    assert.ok(!h.requests.some(r => /realtime|\/voicelog\/session$/.test(r.url)));
  } finally {h.dispose();}
});

test('failed Live setup releases microphone and native audio without leaving a paid connection', async () => {
  const h = harness({failSession: true});
  try {
    for (let i=0;i<8;i++) await tick();
    assert.equal(h.track.stopped,true); assert.equal(h.pc.closed,true); assert.equal(h.pc.dc.closed,true);
    assert.equal(h.audioStopped,1); assert.equal(h.closed,0);
  } finally {h.dispose();}
});

test('notification action closes the same microphone and paid connection', async () => {
  const h = harness();
  try {
    for(let i=0;i<8;i++) await tick();
    h.endFromNotification(); await tick();
    assert.equal(h.closed,1); assert.equal(h.track.stopped,true); assert.equal(h.pc.closed,true);
  } finally {h.dispose();}
});

test('ending closes paid audio immediately but preserves the route until standby cue completes', async () => {
  const h = harness({holdStandby:true});
  try {
    for(let i=0;i<8;i++) await tick();
    assert.deepEqual(h.cues,['ready']);
    const before = h.audioStopped;
    h.endFromNotification(); await tick();
    assert.equal(h.pc.closed,true); assert.equal(h.track.stopped,true);
    assert.equal(h.audioStopped,before); assert.equal(h.closed,0);
    assert.deepEqual(h.cues,['ready','standby']);
    h.endFromNotification(); await tick();
    assert.deepEqual(h.cues,['ready','standby']);
    h.finishCue(); await tick();
    assert.ok(h.audioStopped > before); assert.equal(h.closed,1);
  } finally {h.finishCue(); h.dispose();}
});

 test('a stalled status read times out and later polls recover without starting another job',async()=>{
  const h=harness({activeJob:true,jobPollResults:['hang',{error:'offline'},{jobs:[]}]});
  try{
   for(let i=0;i<8;i++)await tick();
   h.tickBackground(2000);await tick();
   const polls=()=>h.requests.filter(r=>r.body.args?.action==='jobs');
   assert.equal(polls().length,1);
   h.tickBackground(2000);await tick();assert.equal(polls().length,1);
   h.expireJobRead();for(let i=0;i<4;i++)await tick();
   h.tickBackground(2000);for(let i=0;i<4;i++)await tick();
   h.tickBackground(2000);for(let i=0;i<4;i++)await tick();
   assert.equal(polls().length,3);
   assert.equal(h.requests.filter(r=>['work','delegate'].includes(r.body.args?.action)).length,0);
   assert.ok(!h.pc.closed);
  }finally{h.dispose();}
 });


