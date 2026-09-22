const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../frontend/node_modules/typescript');
const source = fs.readFileSync(path.join(__dirname,'../../frontend/src/app/api/v1/chat/refresh/atom-pair/route.ts'),'utf8');
const code = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
let refreshStatus=200, reads=0, requests=[];
const box={exports:{},process:{env:{},cwd:()=>'/repo/frontend'},AbortSignal,
  require:name=> name==='node:path'?path:name==='node:fs/promises'?{readFile:async()=>{reads++;return '{"key":"device-secret"}';}}:{NextResponse:{json:(body,init={})=>({body,status:init.status||200,headers:new Headers()})}},
  fetch:async(url,options)=>{
    requests.push({url,options});
    if(url.endsWith('/refresh'))return {ok:refreshStatus===200,status:refreshStatus,json:async()=>({access_token:'access',refresh_token:'renew'}),headers:{getSetCookie:()=>['done_access_token=access; HttpOnly; Path=/']}};
    return {ok:true};
  },
};
vm.runInNewContext(code,box);
const request=(origin='http://localhost:3000',query='')=>({headers:new Headers({origin,host:'localhost:3000',cookie:'done_refresh_token=test'}),nextUrl:new URL('http://localhost:3000/api/v1/chat/refresh/atom-pair'+query)});
(async()=>{
  assert.equal((await box.exports.POST(request('https://unrelated.example'))).status,403);
  assert.equal(requests.length,0);assert.equal(reads,0);
  refreshStatus=401;
  assert.equal((await box.exports.POST(request())).status,401);assert.equal(reads,0);
  refreshStatus=503;
  assert.equal((await box.exports.POST(request())).status,503);assert.equal(reads,0);
  refreshStatus=200;requests=[];
  const paired=await box.exports.POST(request());
  assert.equal(paired.status,200);
  assert.equal(requests[0].options.headers.cookie,'done_refresh_token=test');
  assert.deepEqual(JSON.parse(requests[1].options.body),{key:'device-secret',token:'access',refresh_token:'renew'});
  assert.ok(paired.headers.get('set-cookie').includes('HttpOnly'));
  assert.equal(JSON.stringify(paired.body),'{"ok":true}');
  requests=[];
  await box.exports.POST(request('http://localhost:3000','?action=stop'));
  assert.deepEqual(JSON.parse(requests[1].options.body),{key:'device-secret',action:'stop'});
  console.log('PASS: pairing origin/auth boundaries, cookie forwarding, secret isolation, stop');
})().catch(e=>{console.error(e);process.exitCode=1;});
