const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),ts=require('typescript');
const slots=[];let cursor=0;
const React={createElement:(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity)}),Fragment:'Fragment',useState(initial){const i=cursor++;if(!(i in slots))slots[i]=initial;return[slots[i],v=>slots[i]=typeof v==='function'?v(slots[i]):v]},useRef(initial){const i=cursor++;return slots[i]||(slots[i]={current:initial})},useEffect(){},useCallback:f=>f};
const moduleBox={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(require('path').join(__dirname,'../collab-rooms.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText,{exports:moduleBox.exports,require:name=>name==='react'?React:name==='react-native'?new Proxy({StyleSheet:{create:x=>x}},{get:(o,k)=>o[k]||k}):name==='@expo/vector-icons'?{Ionicons:'Icon'}:name==='./ui-language'?{ui:en=>en,useUiLanguage(){}}:{doneColors:{}},setInterval,clearInterval});
let tree,calls=[],opened=[],fail=false,release;
const request=async(path,options)=>{calls.push([path,JSON.parse(options.body)]);if(fail)throw Error('offline');if(release!==undefined)await new Promise(resolve=>release=resolve);return{id:'created-room',title:'New room'}};
const render=()=>{cursor=0;tree=moduleBox.exports.CollabRoomsScreen({request,onOpenRoom:r=>opened.push(r),topInset:0})};
function all(n,p){if(!n||typeof n!=='object')return[];return[p(n)?n:null,...(n.children||[]).flatMap(x=>all(x,p))].filter(Boolean)}
const label=s=>all(tree,n=>n.props.accessibilityLabel===s)[0];
const submit=()=>all(tree,n=>n.type==='Pressable'&&n.children.some(c=>c&&c.children&&c.children.includes('Create chat')))[0];
(async()=>{
 render();label('New collab chat').props.onPress();render();assert.equal(submit().props.disabled,true);
 label('Chat name').props.onChangeText(' New room ');render();assert.equal(submit().props.disabled,false);
 fail=true;submit().props.onPress();await new Promise(r=>setImmediate(r));render();assert.equal(label('Chat name').props.value,' New room ');assert.equal(opened.length,0);assert.ok(all(tree,n=>n.props.accessibilityRole==='alert').length);
 fail=false;release=null;submit().props.onPress();submit().props.onPress();assert.equal(calls.length,2);release();await new Promise(r=>setImmediate(r));release=undefined;render();assert.equal(opened[0].id,'created-room');assert.deepEqual(calls[1],['/collab/rooms',{title:'New room'}]);
 label('Your profile').props.onPress();render();label('Display name').props.onChangeText(' Sample ');render();
 const save=()=>all(tree,n=>n.type==='Pressable'&&n.children.some(c=>c&&c.children&&c.children.includes('Save')))[0];
 fail=true;save().props.onPress();await new Promise(r=>setImmediate(r));render();assert.equal(label('Display name').props.value,' Sample ');
 fail=false;save().props.onPress();await new Promise(r=>setImmediate(r));render();label('Your profile').props.onPress();render();assert.equal(label('Display name').props.value,'Sample');assert.deepEqual(calls.at(-1),['/chat/profile',{display_name:'Sample'}]);
 console.log('PASS: create/save contracts, blank guard, duplicate-submit guard, failure keeps draft, retry succeeds (mock requests; no real rooms/messages).');
})().catch(e=>{console.error(e);process.exitCode=1});
