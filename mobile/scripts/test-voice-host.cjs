const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),ts=require('typescript');
const source=fs.readFileSync(require('node:path').join(__dirname,'../voice-host.tsx'),'utf8');
let slots=[],index=0,provider;
const React={createContext:()=>({Provider:'provider'}),useContext:()=>null,useState:init=>{const i=index++;if(!(i in slots))slots[i]=init;return[slots[i],value=>slots[i]=typeof value==='function'?value(slots[i]):value]},createElement:(type,props,...children)=>{if(type==='provider')provider=props.value;return{type,props,children}}};
const modules={'react':React,'react-native':{View:'view'},'./voice':{VoiceOverlay:'call'},'./ui-language':{useUiLanguage(){}}};
const context={exports:{},require:name=>modules[name]};
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText,context);
function render(){index=0;return context.exports.VoiceHost({children:'chat with unsent text'})}
const call={roomId:'hub',token:'test'};
render();provider.start(call,{preserveScreen:true});let tree=render();assert.equal(provider.minimized,true,'warm shortcut keeps chat exposed');assert.equal(tree.children[0].children[1].children[0],'chat with unsent text');
const first=slots[0];provider.start({roomId:'other'},{preserveScreen:true});render();assert.equal(slots[0],first,'no duplicate or switched call');assert.equal(provider.minimized,true,'repeated shortcut stays minimized');
provider.start(call);render();assert.equal(provider.minimized,false,'explicit open expands');provider.start(call,{preserveScreen:true});render();assert.equal(provider.minimized,false,'already open call stays open');
provider.stop();render();provider.start(call);render();assert.equal(provider.minimized,false,'cold launch opens call');
provider.stop();render();provider.start(call,{preserveScreen:true});render();assert.equal(provider.minimized,true,'new warm call after ending remains compact');
console.log('PASS: VoiceHost warm/cold, repeated and existing calls, unchanged chat child, explicit expand, stop/restart');
