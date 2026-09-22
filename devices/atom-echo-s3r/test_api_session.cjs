const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../frontend/node_modules/typescript');
const compile=file=>ts.transpileModule(fs.readFileSync(path.join(__dirname,'../../frontend/src/lib',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const storage=new Map([['done-token','expired']]);
let refreshStatus=200, refreshCalls=0, logouts=0;
const common={AbortSignal,URLSearchParams,console:{warn:()=>{}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},window:{location:{pathname:'/chat',href:''}},fetch:async(url,options)=>{
  if(url.endsWith('/refresh')){
    refreshCalls++;await new Promise(r=>setTimeout(r,10));
    return {ok:refreshStatus===200,status:refreshStatus,json:async()=>({access_token:'renewed'})};
  }
  const ok=options.headers.Authorization==='Bearer renewed';
  return {ok,status:ok?200:401,statusText:'Unauthorized',headers:new Headers({'content-type':'application/json'}),json:async()=>ok?{id:'user'}:{detail:'expired'}};
}};
const refresh={...common,exports:{}};vm.runInNewContext(compile('session-refresh.ts'),refresh);
const api={...common,exports:{},require:name=>name==='./session-refresh'?refresh.exports:{useAuthStore:{getState:()=>({setToken:()=>{},logout:()=>logouts++})}}};
vm.runInNewContext(compile('api-client.ts'),api);
(async()=>{
  const users=await Promise.all(Array.from({length:8},()=>api.exports.api.auth.me()));
  assert.ok(users.every(x=>x.id==='user'));assert.equal(refreshCalls,1);assert.equal(logouts,0);
  api.exports.setImmediateToken(null);storage.set('done-token','expired');refreshStatus=503;
  await assert.rejects(api.exports.api.auth.me(),e=>e.status===503);
  assert.equal(logouts,0);assert.equal(storage.get('done-token'),'expired');assert.equal(common.window.location.href,'');
  refreshStatus=401;
  await assert.rejects(api.exports.api.auth.me(),e=>e.status===401);
  assert.equal(logouts,1);assert.equal(common.window.location.href,'/login');assert.equal(storage.has('done-token'),false);
  console.log('PASS: API retry after refresh, shared refresh, outage retains login, revoked login settles');
})().catch(e=>{console.error(e);process.exitCode=1;});
