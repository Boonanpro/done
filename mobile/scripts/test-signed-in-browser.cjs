const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),ts=require('typescript');
const {AbortController,AbortSignal}=require('abort-controller');
const babel=require('@babel/core');
const native={exports:{},require:name=>name==='./NativeBlobModule'?null:{URLSearchParams}};
vm.runInNewContext(babel.transformSync(fs.readFileSync(require.resolve('react-native/Libraries/Blob/URL'),'utf8'),{babelrc:false,configFile:false,plugins:['@babel/plugin-transform-flow-strip-types','@babel/plugin-transform-modules-commonjs']}).code,native);
const source=fs.readFileSync(require('path').join(__dirname,'../private-artifact.ts'),'utf8');
let clears=0,mode='ok',sent;
const context={exports:{},URL:native.exports.URL,AbortController,AbortSignal,setTimeout:()=>1,clearTimeout:()=>clears++,fetch:async(url,init)=>{
 assert.equal(url,'https://dan.paina.info/enter');
 assert.equal(init.headers.Authorization,'Bearer test');
 sent=JSON.parse(init.body);
 if(mode==='throw')throw Error('offline');
 const host=mode==='foreign'?'https://untrusted.example':'https://dan.paina.info';
 const hash=mode==='badhash'?'#short':'#'+'b'.repeat(43);
 return {ok:mode!=='denied',json:async()=>({url:host+'/enter'+hash})};
}};
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
(async()=>{
 const {signedInBrowserUrl}=context.exports;
 const to='https://dan.paina.info/preview/dev-lead';
 assert.equal(await signedInBrowserUrl('https://dan.paina.info','test','r1',to),'https://dan.paina.info/enter#'+'b'.repeat(43));
 assert.deepEqual(sent,{to,refresh_token:'r1'});
 await signedInBrowserUrl('https://dan.paina.info','test',null,to);
 assert.deepEqual(sent,{to});
 for(mode of ['denied','foreign','badhash','throw'])assert.equal(await signedInBrowserUrl('https://dan.paina.info','test','r1',to),null);
 assert.equal(clears,6);
 console.log('PASS: signed-in browser link, refresh token passed, rejected/foreign/malformed/offline fall back to the plain URL');
})().catch(e=>{console.error(e);process.exitCode=1});
