const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../frontend/node_modules/typescript');
const source = fs.readFileSync(path.join(__dirname, '../../frontend/src/components/voice/standby-drain.ts'), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const sandbox = {exports:{}};
vm.runInNewContext(compiled, sandbox);
const wait = sandbox.exports.waitForStandbyDrain;

async function scenario(state, expected, earliest, timeoutMs=30000) {
  let time=0;
  const result=await wait(() => ({active:true,generating:false,playing:false,epoch:0,...state(time)}), {
    now:()=>time, sleep:async ms=>{time+=ms;}, timeoutMs,
  });
  assert.equal(result,expected);
  assert.ok(time>=earliest,`${result} happened too early: ${time}`);
}
(async()=>{
  // response.done is not playback completion: a spoken tail must finish.
  await scenario(t=>({generating:t<200,playing:t<2400}),'drained',2700);
  await scenario(t=>({generating:t<200}),'drained',500);
  // A late-starting audio chunk restarts the quiet tail timer.
  await scenario(t=>({playing:t>=120&&t<800}),'drained',1100);
  await scenario(t=>({playing:true,epoch:t<600?0:1}),'superseded',600);
  await scenario(t=>({playing:true,active:t<400}),'superseded',400);
  await scenario(()=>({playing:true}),'timeout',1000,1000);
  console.log('PASS: speech drain, silent tool, late audio, interruption, disconnect and timeout');
})().catch(error=>{console.error(error);process.exitCode=1;});
