const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),ts=require('typescript');
const {AbortController,AbortSignal}=require('abort-controller');
// Test the native URL implementation too, rather than Node's browser-compatible URL.
const babel=require('@babel/core');
const native={exports:{},require:name=>name==='./NativeBlobModule'?null:{URLSearchParams}};
vm.runInNewContext(babel.transformSync(fs.readFileSync(require.resolve('react-native/Libraries/Blob/URL'),'utf8'),{babelrc:false,configFile:false,plugins:['@babel/plugin-transform-flow-strip-types','@babel/plugin-transform-modules-commonjs']}).code,native);
const source=fs.readFileSync(require('path').join(__dirname,'../private-artifact.ts'),'utf8');
let clears=0,abortTimeout,mode='ok';
const context={exports:{},URL:native.exports.URL,AbortController,AbortSignal,setTimeout:fn=>(abortTimeout=fn,1),clearTimeout:()=>clears++,fetch:async(url,init)=>{
 assert.equal(url,'https://dan.paina.info/api/x-operation/open');
 assert.equal(init.headers.Authorization,'Bearer test');
 assert.ok(init.signal instanceof AbortSignal);
 if(mode==='timeout'){abortTimeout();assert.equal(init.signal.aborted,true);throw Error('aborted');}
 return {ok:mode!=='denied',json:async()=>({url:(mode==='foreign'?'https://untrusted.example':'https://dan.paina.info')+'/api/x-operation/open#'+'a'.repeat(43)})};
}};
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
(async()=>{
 assert.equal(typeof AbortSignal.timeout,'undefined');
 const {privateArtifactUrl,isXOperation}=context.exports;
 assert.ok(isXOperation('https://dan-site-x-operation-3ef49fba.vercel.app/'));
 assert.ok(!isXOperation('https://untrusted.example/preview/x-operation'));
 for(mode of ['ok','denied','foreign','timeout']){
  if(mode==='ok')assert.ok((await privateArtifactUrl('https://dan.paina.info','test')).includes('#'));
  else await assert.rejects(()=>privateArtifactUrl('https://dan.paina.info','test'));
 }
 assert.equal(clears,4);
 console.log('PASS: RN polyfill, native handoff, rejected response/foreign destination, abort and timer cleanup');
})().catch(e=>{console.error(e);process.exitCode=1});
