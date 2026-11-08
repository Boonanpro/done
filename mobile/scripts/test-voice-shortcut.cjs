const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), ts = require('typescript');
const app = process.argv.includes('--baseline') ? require('node:child_process').execFileSync('git',['show','084e0aef0a6e9502d1d74b52fbdc64fa178c58b2:mobile/App.tsx'],{encoding:'utf8'}) : fs.readFileSync(require('node:path').join(__dirname, '../App.tsx'), 'utf8');
const start = app.indexOf('  // A physical shortcut');
const end = app.indexOf("  // Dan's calls", start);
const code = ts.transpileModule(app.slice(start, end), {compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText;
const tick = () => new Promise(resolve => setImmediate(resolve));
async function scenario({pending=false,state='active',saved='valid',room='hub'}={}) {
  let effect, nativePending=pending, event, change;
  const calls=[], alerts=[];
  const context = {
    useEffect: f=>{effect=f}, Platform:{OS:'android'},
    NativeModules:{DanVoiceCall:{takeVoiceShortcut:async()=>{const p=nativePending;nativePending=false;return p}}},
    AppState:{currentState:state,addEventListener:(_,f)=>{change=f;return{remove(){}}}},
    DeviceEventEmitter:{addListener:(_,f)=>{event=f;return{remove(){}}}},
    SecureStore:{getItemAsync:async key=>key==='token'?saved:room}, TOKEN_KEY:'token', HUB_KEY:'hub',
    tokenFresh:t=>t==='valid', Alert:{alert:(...args)=>alerts.push(args)},
    voiceRef:{current:{start:(c,o)=>calls.push({...c,options:o})}},API_BASE_URL:'https://example.test'
  };
  vm.runInNewContext(code,context);effect();await tick();
  return {calls,alerts, async press(preserveScreen=true){nativePending={preserveScreen};event();await tick()},async resume(){context.AppState.currentState='active';change('active');await tick()},async duplicate(){event();await tick()}};
}
(async()=>{
  let s=await scenario();assert.equal(s.calls.length,0,'ordinary launch must not call');
  s=await scenario({pending:true});assert.equal(s.calls.length,1,'cold shortcut starts');assert.equal(s.calls[0].roomId,'hub');assert.equal(s.calls[0].options?.preserveScreen ?? false,false,'cold opens call screen');assert.equal(s.calls[0].audioEndpoint,undefined,'uses phone/headset');
  await s.duplicate();await s.resume();assert.equal(s.calls.length,1,'resume/event cannot repeat consumed request');
  s=await scenario();await s.press();assert.equal(s.calls.length,1,'warm shortcut starts');assert.equal(s.calls[0].options?.preserveScreen,true,'visible chat must stay visible');
  s=await scenario({state:'background'});await s.press(false);assert.equal(s.calls.length,0);await s.resume();assert.equal(s.calls.length,1,'background request waits for foreground');assert.equal(s.calls[0].options?.preserveScreen ?? false,false,'background opens call screen');
  for (const invalid of [{saved:null},{saved:'expired'},{room:null}]) {s=await scenario({pending:true,...invalid});assert.equal(s.calls.length,0);assert.equal(s.alerts.length,1)}
  console.log('PASS: ordinary launch, cold/warm shortcut, foreground resume, duplicate delivery, missing/expired login and room');
})().catch(e=>{console.error(e);process.exit(1)});
