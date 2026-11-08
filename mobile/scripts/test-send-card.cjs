const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const ts = require('typescript');
const tick = () => new Promise(r => setImmediate(r));
const root = path.join(__dirname, '..');
function mount(source, name, props, mocks = {}) {
  const states = [], deps = [], effects = [];
  let cursor = 0, pending = [], timer;
  const react = {
    useState(value) { const i = cursor++; if (!(i in states)) states[i] = value; return [states[i], v => { states[i] = typeof v === 'function' ? v(states[i]) : v; }]; },
    useRef(value) { const i = cursor++; return states[i] ||= {current: value}; },
    useEffect(fn, next) { const i = cursor++; if (!deps[i] || next.some((v,j) => v !== deps[i][j])) {pending.push(() => {effects[i]?.(); effects[i] = fn();});deps[i] = next;} },
  };
  const native = Object.fromEntries(['Text', 'TextInput', 'Pressable', 'View'].map(k => [k,k])); native.StyleSheet = {create: x=>x}; native.TextInput = 'DraftBodyEditor';
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, {compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText, {
    exports, require(name) {return mocks[name] || ({react, 'react-native': native, '@expo/vector-icons': {Ionicons:'Ionicons'}, './copy-body-button':{CopyBodyButton:'CopyBodyButton'}, './draft-body-editor':{DraftBodyEditor:'DraftBodyEditor'}, './ui-language':{ui:(_,ja)=>ja}, 'react/jsx-runtime': {jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}})[name] || {};},
    setInterval(fn) {timer = fn; return 1;}, clearInterval() {}, console,
  });
  return {render() {cursor=0; const tree=exports[name](props); const run=pending; pending=[]; run.forEach(f=>f());return tree;},poll() {timer?.();},props};
}
function find(tree, type) {
  if (!tree) return [];
  if (Array.isArray(tree)) return tree.flatMap(x=>find(x,type));
  if (typeof tree !== 'object') return [];
  return [...(tree.type===type?[tree]:[]),...find(tree.props?.children,type)];
}
function label(tree) {return find(tree,'Text').map(n=>n.props.children).flat().join('');}
function button(tree, text) {const result=find(tree,'Pressable').find(x=>label(x).includes(text));assert.ok(result,`button ${text}`);return result;}
const source = process.argv.includes('--before') ? execFileSync('git',['show','084e0aef0a6e9502d1d74b52fbdc64fa178c58b2:mobile/send-card.tsx'],{cwd:root,encoding:'utf8'}) : fs.readFileSync(path.join(root,'send-card.tsx'),'utf8');
async function card() {
  let proposal={id:'test',status:'pending',content:'Original\nhttps://example.test',action_data:{to:'test'}};
  const requests=[]; let hold=false, reject=false, rejectGet=false; const waiting=[];
  const request=async (url,init) => {requests.push([url,init]); if(rejectGet && !init) throw Error('offline'); if(reject && init) throw Error('offline'); if(!init && hold) return new Promise(resolve=>waiting.push(resolve)); return init?.method==='POST'?{...proposal,status:url.endsWith('discard')?'rejected':'sent'}:{...proposal};};
  const ui=mount(source,'SendCard',{id:'test',request});ui.render();await tick();ui.render();
  return {ui,requests,edit(text){find(ui.render(),'DraftBodyEditor')[0].props.onChangeText(text);ui.render();},body(){return find(ui.render(),'DraftBodyEditor')[0]?.props.value},hold(){hold=true;ui.poll();},resolve(){waiting.shift()?.({...proposal});},fail(){reject=true;},failGet(){rejectGet=true;},remote(text){proposal.content=text;}};
}
(async()=>{
  const edited='編集した本文\n\nhttps://example.test/a?q=1\n末尾😀  ';
  let c=await card();c.edit(edited);c.ui.poll();await tick();assert.equal(c.body(),edited,'poll must preserve edited text and cursor value');
  if(process.argv.includes('--before')) throw Error('expected old implementation to fail');
  c=await card();find(c.ui.render(),'DraftBodyEditor')[0].props.onFocus();c.remote('Remote changed');c.ui.poll();await tick();assert.equal(c.body(),'Original\nhttps://example.test','focused IME input is never replaced by polling');find(c.ui.render(),'DraftBodyEditor')[0].props.onBlur();await tick();assert.equal(c.body(),'Remote changed','untouched draft refreshes after blur');
  c=await card();find(c.ui.render(),'DraftBodyEditor')[0].props.onFocus();c.remote('Remote changed');c.ui.poll();await tick();await button(c.ui.render(),'送信').props.onPress();assert.equal(JSON.parse(c.requests.find(([,i])=>i?.method==='PATCH')[1].body).body,'Original\nhttps://example.test','send must use visible text when remote changed during focus');
  c=await card();c.edit(edited);c.failGet();c.ui.poll();await tick();assert.equal(c.body(),edited,'GET error keeps existing draft visible');
  c=await card();c.hold();c.edit(edited);c.resolve();await tick();assert.equal(c.body(),edited,'edit during pending GET survives');
  assert.equal(find(c.ui.render(),'CopyBodyButton')[0].props.body,edited,'copy receives current unsaved body');
  c=await card();c.edit(edited);c.hold();const send=button(c.ui.render(),'直した文で送る').props.onPress;const one=send(),two=send();await Promise.all([one,two]);c.resolve();await tick();assert.equal(find(c.ui.render(),'DraftBodyEditor').length,0,'late poll cannot revert sent status');
  assert.equal(c.requests.filter(([,i])=>i?.method==='POST').length,1,'double tap sends once');assert.equal(JSON.parse(c.requests.find(([,i])=>i?.method==='PATCH')[1].body).body,edited);
  c=await card();c.edit(edited);c.fail();await button(c.ui.render(),'直した文で送る').props.onPress();assert.equal(c.body(),edited,'failed save leaves draft');assert.equal(c.requests.filter(([,i])=>i?.method==='POST').length,0,'failed save never sends');
  c=await card();c.edit(edited);await button(c.ui.render(),'破棄').props.onPress();assert.equal(c.ui.render(),null);assert.equal(c.requests.filter(([,i])=>i?.method==='PATCH').length,0,'discard never saves edited body');
  const copySource=fs.readFileSync(path.join(root,'copy-body-button.tsx'),'utf8');const writes=[];let fail=false;
  const props={body:edited};const copy=mount(copySource,'CopyBodyButton',props,{'expo-clipboard':{setStringAsync:async t=>{if(fail)throw Error('denied');writes.push(t);return true;}}});copy.render();await copy.render().props.onPress();assert.deepEqual(writes,[edited]);assert.match(label(copy.render()),/コピーしました/);
  props.body='次の本文';copy.render();assert.equal(label(copy.render()),'コピー');fail=true;await copy.render().props.onPress();assert.match(label(copy.render()),/失敗/);fail=false;await copy.render().props.onPress();assert.equal(writes.at(-1),'次の本文');
  console.log('PASS: edited text polling/in-flight GET, newest copy, send race/double tap, failed save preservation, discard, verbatim clipboard and retry');
})().catch(e=>{console.error(e);process.exit(1)});
