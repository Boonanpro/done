const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../../frontend/node_modules/typescript');
const code = ts.transpileModule(fs.readFileSync(require('node:path').join(__dirname, '../../frontend/src/lib/session-refresh.ts'), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
let calls = 0, status = 200;
const box = {exports:{}, AbortSignal, fetch: async()=>{
  calls++;
  await new Promise(resolve=>setTimeout(resolve,5));
  return {ok:status===200,status,json:async()=>({access_token:'renewed'})};
}};
vm.runInNewContext(code,box);
(async()=>{
  let saves=0;
  const save=()=>saves++;
  const results=await Promise.all(Array.from({length:12},()=>box.exports.refreshSession(save)));
  assert.equal(calls,1); assert.equal(saves,1); assert.ok(results.every(x=>x==='renewed'));
  status=503;
  await assert.rejects(box.exports.refreshSession(save),e=>e.status===503);
  status=401;
  await assert.rejects(box.exports.refreshSession(save),e=>e.status===401);
  status=200;
  assert.equal(await box.exports.refreshSession(save),'renewed');
  assert.equal(saves,2);
  console.log('PASS: concurrent refresh, transient failure, expired session, recovery');
})().catch(e=>{console.error(e);process.exitCode=1;});
